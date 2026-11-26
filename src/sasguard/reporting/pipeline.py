"""Reports for ``validate-pipeline`` run directories.

Reads the saved ``pipeline-validation.json`` only. It reruns nothing, calls no model and
re-hashes only files already inside the run directory. A run that cannot be confirmed
against its own record is labelled FAILED, never VERIFIED.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from sasguard.data import load_artifact
from sasguard.provenance.hashing import sha256_file
from sasguard.reporting.reader import report_runs_directory
from sasguard.verification.pipeline import (
    TOTAL_ARTIFACTS,
    PipelineValidation,
    StageResult,
    derive_status,
    render_summary,
)
from sasguard.verification.program1 import find_output_file

RECORD = "pipeline-validation.json"
ORIGINS = {
    "human_reference": "human reference",
    "direct_model_output": "direct model output",
    "helper_assisted_model_output": "helper-assisted model output",
    "manually_corrected_model_output": "manually corrected model output",
}
POLICY_FILES = {
    0: "program0-comparison-policies.json",
    1: "program1-comparison-policies.json",
    2: "program2-comparison-policies.json",
}
# Only these environment keys are rendered; values are also scrubbed of key-like strings.
ENVIRONMENT_KEYS = (
    "git_commit",
    "python_version",
    "python_implementation",
    "operating_system",
    "architecture",
)
SECRET = re.compile(
    r"(?i)(sk-[a-z0-9_-]{8,}|gh[pousr]_[a-z0-9]{8,}|xox[a-z]-[a-z0-9-]{8,}|AKIA[0-9A-Z]{8,}"
    r"|bearer\s+\S+|[a-z0-9_]*(?:key|token|secret|password)[a-z0-9_]*\s*[=:]\s*\S+"
    r"|[A-Za-z0-9+/_-]{40,})"
)
HEX = re.compile(r"[0-9a-fA-F]{40,}")


def is_pipeline_run(run: Path) -> bool:
    return (run / RECORD).is_file()


def _clean(value: object, limit: int = 300) -> str:
    text = SECRET.sub("[redacted]", str(value)).replace("\r", " ").replace("\n", " ")
    return text[:limit]


class ArtifactRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    program: str
    artifact: str
    status: Literal["passed", "failed", "not_compared"]
    expected_rows: int | None = None
    actual_rows: int | None = None
    expected_columns: int | None = None
    actual_columns: int | None = None
    mismatched_cells: int | None = None
    missingness_mismatches: int | None = None
    policy: str
    error: str | None = None


class StageRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    program: str
    code_origin: str
    status: str
    own_status: str
    artifacts_passed: int
    artifacts_total: int
    handoff: Literal["not_applicable", "passed", "failed"]
    handoff_artifacts_checked: int
    note: str
    output_files_rechecked: int
    output_directory: str


class PipelineRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    report_kind: Literal["pipeline"] = "pipeline"
    scope_status: Literal["VERIFIED", "NOT VERIFIED", "FAILED"]
    record_status: str
    full_pipeline_parity: bool
    input_release: str
    scope: str
    run_date: str
    run_date_source: str
    run_command: str
    artifacts_passed: int
    artifacts_total: int
    passed_by_program: dict[str, int]
    star_mismatches: int | None
    stages: tuple[StageRow, ...]
    artifacts: tuple[ArtifactRow, ...]
    earliest_divergence: str | None
    integrity_before: str
    integrity_after: str
    policy_audit: tuple[str, ...]
    hospitals_processed: int | None
    hospitals_eligible: int | None
    star_distribution: dict[str, int] | None
    counts_note: str
    evidence_issues: tuple[str, ...]
    record_hashes: dict[str, str]
    environment: dict[str, str]
    environment_sha256: str
    policy_hashes: dict[str, str]
    sas_reference_hashes: dict[str, str]
    stage_output_hashes: dict[str, dict[str, str]]
    human_review: Literal["not_recorded"] = "not_recorded"
    client_release_approved: Literal[False] = False


def _integrity_text(values: dict[str, int | bool]) -> str:
    return (
        f"{values.get('checked_files')}/{values.get('expected_files')} "
        f"({'passed' if values.get('passed') else 'failed'})"
    )


def _recheck(run: Path, stage: StageResult, issues: list[str]) -> tuple[int, Path | None]:
    """Re-hash recorded stage outputs that are inside the run directory."""
    name = Path(stage.output_directory).name
    directory = run / name
    if not name or directory.is_symlink() or not directory.is_dir():
        return 0, None
    checked = 0
    for filename, digest in stage.output_hashes.items():
        path = find_output_file(directory, filename)
        if path is None:
            issues.append(f"{stage.program}:{filename}:recorded_output_missing")
            continue
        checked += 1
        if sha256_file(path, normalize_text=False) != digest:
            issues.append(f"{stage.program}:{filename}:output_changed_since_record")
    return checked, directory


def _consistency(record: PipelineValidation, issues: list[str]) -> None:
    passed = sum(stage.artifacts_passed for stage in record.stages)
    integrity = bool(record.integrity_before.get("passed")) and bool(
        record.integrity_after.get("passed")
    )
    expected = derive_status(
        artifacts_passed=passed,
        handoffs_passed=all(stage.handoff_passed for stage in record.stages),
        integrity_passed=integrity,
        audit_passed=not record.policy_audit,
    )
    if passed != record.artifacts_passed or expected != record.status:
        issues.append("record_status_disagrees_with_its_artifact_results")
    if record.full_pipeline_parity != (record.status == "PASS"):
        issues.append("record_parity_flag_disagrees_with_status")
    if len(record.stages) != 3 or record.artifacts_total != TOTAL_ARTIFACTS:
        issues.append("record_does_not_describe_three_stages_and_ten_artifacts")


def _totals(
    directory: Path | None, stage: StageResult, record: PipelineValidation
) -> tuple[int, int, dict[str, int]] | None:
    expected = stage.output_hashes.get("star_2025jul.csv")
    if directory is None or expected is None or stage.own_status != "passed":
        return None
    path = find_output_file(directory, "star_2025jul.csv")
    if path is None or sha256_file(path, normalize_text=False) != expected:
        return None
    frame = load_artifact(path, key="PROVIDER_ID").frame
    if sha256_file(path, normalize_text=False) != expected:
        return None
    return (
        len(frame),
        int(frame["REPORT_INDICATOR"].eq(1).sum()),
        {str(rating): int(frame["STAR"].eq(rating).sum()) for rating in range(1, 6)},
    )


def read_pipeline_report(project_root: Path, run_directory: Path) -> PipelineRunReport:
    root = project_root.resolve()
    runs = report_runs_directory(root)
    run = run_directory if run_directory.is_absolute() else root / run_directory
    run = run.resolve()
    if run.parent != runs:
        raise ValueError("report input must be a top-level saved run inside reports/runs")
    record_path = run / RECORD
    if record_path.is_symlink() or not record_path.is_file():
        raise ValueError(f"{RECORD} is missing or unsafe")
    try:
        record = PipelineValidation.model_validate_json(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as error:
        raise ValueError("pipeline-validation.json is not a valid pipeline record") from error

    issues: list[str] = []
    _consistency(record, issues)
    summary = run / "summary.md"
    if summary.is_file() and summary.read_text(encoding="utf-8") != render_summary(record):
        issues.append("summary_md_disagrees_with_record")
    rechecked: dict[str, int] = {}
    directories: dict[int, Path | None] = {}
    for stage in record.stages:
        count, directory = _recheck(run, stage, issues)
        rechecked[stage.program] = count
        directories[stage.stage] = directory

    rows: list[ArtifactRow] = []
    for stage in record.stages:
        policy = f"{POLICY_FILES.get(stage.stage, 'unknown')}; fixed 1e-12 contract"
        if record.policy_audit:
            policy += " (audit FAILED)"
        for outcome in stage.artifacts:
            comparison = outcome.comparison
            rows.append(
                ArtifactRow(
                    program=stage.program,
                    artifact=outcome.artifact,
                    status=("passed" if outcome.passed else "failed")
                    if comparison is not None
                    else "not_compared",
                    expected_rows=comparison.expected_rows if comparison else None,
                    actual_rows=comparison.actual_rows if comparison else None,
                    expected_columns=len(comparison.expected_columns) if comparison else None,
                    actual_columns=len(comparison.actual_columns) if comparison else None,
                    mismatched_cells=comparison.mismatched_cells if comparison else None,
                    missingness_mismatches=comparison.missingness_mismatches
                    if comparison
                    else None,
                    policy=policy,
                    error=_clean(outcome.error) if outcome.error else None,
                )
            )
    stage_rows = tuple(
        StageRow(
            program=stage.program,
            code_origin=ORIGINS[stage.source.value],
            status=stage.status,
            own_status=stage.own_status,
            artifacts_passed=stage.artifacts_passed,
            artifacts_total=len(stage.artifacts),
            handoff="not_applicable"
            if stage.stage == 0
            else ("passed" if stage.handoff_passed else "failed"),
            handoff_artifacts_checked=len(stage.handoff),
            note=_clean(stage.note),
            output_files_rechecked=rechecked[stage.program],
            output_directory=_clean(stage.output_directory),
        )
        for stage in record.stages
    )

    integrity_ok = bool(record.integrity_before.get("passed")) and bool(
        record.integrity_after.get("passed")
    )
    if issues or record.status == "FAIL":
        scope_status: Literal["VERIFIED", "NOT VERIFIED", "FAILED"] = "FAILED"
    elif record.status == "PASS" and integrity_ok and not record.policy_audit:
        scope_status = "VERIFIED"
    else:
        scope_status = "NOT VERIFIED"

    totals = (
        _totals(directories.get(2), record.stages[2], record) if len(record.stages) == 3 else None
    )
    counts_note = "Program 2 output was not found in the run directory or did not match its record."
    processed = eligible = None
    distribution = None
    if totals is not None:
        processed, eligible, ratings = totals
        counts_note = "Aggregates from the hash-checked Program 2 star_2025jul.csv."
        if scope_status == "VERIFIED":
            distribution = ratings
        else:
            counts_note += " Star distribution is withheld because the run is not VERIFIED."
    mtime = datetime.fromtimestamp(record_path.stat().st_mtime, UTC).isoformat(timespec="seconds")
    divergence = record.earliest_divergence
    divergence_text = (
        None
        if divergence is None
        else _clean(
            f"{divergence.program}, artifact {divergence.artifact}, {divergence.kind}; "
            f"column {divergence.column or 'n/a'}, key {divergence.key or 'n/a'}. "
            f"{divergence.detail}"
        )
    )
    return PipelineRunReport(
        scope_status=scope_status,
        record_status=record.status,
        full_pipeline_parity=record.full_pipeline_parity and not issues,
        input_release="CMS Hospital Star Ratings, July 2025",
        scope=_clean(record.scope),
        run_date=mtime,
        run_date_source=f"modification time of {RECORD} (UTC); the record has no date field",
        run_command="not recorded",
        artifacts_passed=record.artifacts_passed,
        artifacts_total=record.artifacts_total,
        passed_by_program=record.passed_by_program,
        star_mismatches=record.star_mismatches,
        stages=stage_rows,
        artifacts=tuple(rows),
        earliest_divergence=divergence_text,
        integrity_before=_integrity_text(record.integrity_before),
        integrity_after=_integrity_text(record.integrity_after),
        policy_audit=tuple(_clean(item) for item in record.policy_audit),
        hospitals_processed=processed,
        hospitals_eligible=eligible,
        star_distribution=distribution,
        counts_note=counts_note,
        evidence_issues=tuple(sorted(set(issues))),
        record_hashes={RECORD: sha256_file(record_path, normalize_text=False)},
        environment={
            key: _clean(record.environment[key])
            for key in ENVIRONMENT_KEYS
            if key in record.environment
        }
        | {
            key: _clean(value)
            for key, value in record.environment.items()
            if key.startswith("package_")
        },
        environment_sha256=record.environment_sha256,
        policy_hashes=record.policy_hashes,
        sas_reference_hashes=record.sas_reference_hashes,
        stage_output_hashes={stage.program: dict(stage.output_hashes) for stage in record.stages},
    )


def _md(value: object) -> str:
    if value is None:
        return "n/a"
    text = _clean(value).replace("|", "\\|")
    return text


def render_pipeline_handoff(report: PipelineRunReport) -> str:
    label = report.scope_status
    lines = [
        "# CMS July 2025 hospital star ratings: pipeline validation summary",
        "",
        "Internal draft. Abt review and approval are required before sharing with CMS.",
        "",
        f"Validation status: {label}",
        f"Input release: {report.input_release}",
        f"Run date: {report.run_date} ({report.run_date_source})",
        (
            f"{report.artifacts_passed} of {report.artifacts_total} SAS artifact comparisons "
            "passed."
            if not report.evidence_issues
            else f"The record claims {report.artifacts_passed} of {report.artifacts_total} SAS "
            "artifact comparisons passed, but the record could not be confirmed, so that count "
            "is not relied on."
        ),
        "",
    ]
    if label == "VERIFIED":
        lines.append(
            "Programs 0, 1 and 2 were run as Python and every output, every handoff between "
            "programs, and every individual star assignment matched the supplied SAS artifacts."
        )
    elif label == "NOT VERIFIED":
        lines.append(
            "Only part of the pipeline matched SAS. These are not CMS star ratings and must "
            "not be used as such."
        )
    else:
        lines.append(
            "The run FAILED validation or its record could not be confirmed. These are not CMS "
            "star ratings and must not be used as such."
        )
    lines.extend(
        [
            "",
            "## Stages and code origin",
            "",
            "| Stage | Code origin | Result | Note |",
            "|---|---|---|---|",
        ]
    )
    lines.extend(
        f"| {_md(s.program)} | {_md(s.code_origin)} | {_md(s.status)} "
        f"({s.artifacts_passed}/{s.artifacts_total} artifacts) | {_md(s.note) or 'none'} |"
        for s in report.stages
    )
    if any(s.code_origin != ORIGINS["human_reference"] for s in report.stages):
        lines.extend(
            [
                "",
                "Stages not marked as human reference were not written by a team member and "
                "have no recorded human review. A matching result does not replace that review.",
            ]
        )
    lines.extend(["", "## Hospitals", ""])
    if report.hospitals_processed is None:
        lines.append("Hospital counts are unavailable. " + _md(report.counts_note))
    else:
        lines.append(
            f"Processed {report.hospitals_processed:,} hospitals; "
            f"{report.hospitals_eligible or 0:,} met the rating criteria."
        )
        if report.star_distribution is not None:
            lines.extend(["", "| Star rating | Hospitals |", "|---|---:|"])
            lines.extend(f"| {k} | {v:,} |" for k, v in report.star_distribution.items())
            unrated = report.hospitals_processed - sum(report.star_distribution.values())
            lines.append(f"| Unrated | {unrated:,} |")
        else:
            lines.append("Star distribution is not shown for a run that is not VERIFIED.")
    lines.extend(["", "## What was and was not checked", ""])
    lines.extend(
        [
            (
                "* Verified against the supplied SAS artifacts: the ten comparison artifacts and "
                "the copied handoffs between programs, within the fixed 1e-12 tolerance."
                if label == "VERIFIED"
                else "* Compared against the supplied SAS artifacts: the ten comparison artifacts "
                "and the copied handoffs between programs, within the fixed 1e-12 tolerance. "
                "This run did not verify them; see the status above."
            ),
            "* Trusted, not independently verified: the supplied SAS outputs and the CMS input "
            "data themselves.",
            "* Not checked: any release other than July 2025, SAS runtime behaviour, statistical "
            "correctness of the CMS method, and generated-code quality.",
            "* Human review and Abt approval: not recorded.",
        ]
    )
    if report.evidence_issues:
        lines.extend(["", "Record problems: " + ", ".join(_md(i) for i in report.evidence_issues)])
    if report.earliest_divergence:
        lines.extend(["", f"Earliest divergence: {_md(report.earliest_divergence)}"])
    return "\n".join(lines) + "\n"


def render_pipeline_technical(report: PipelineRunReport) -> str:
    lines = [
        "# Abt technical validation record: full pipeline",
        "",
        "Internal draft summarizing a saved record. Nothing was rerun. Abt confirmation of the "
        "required fields is pending.",
        "",
        f"Validation status: {report.scope_status} (record status {report.record_status})",
        "Full-pipeline parity: "
        + ("established" if report.full_pipeline_parity else "NOT established"),
        f"Scope: {_md(report.scope)}",
        f"Run date: {report.run_date} ({report.run_date_source})",
        f"Run command: {report.run_command}",
        f"Input release: {report.input_release}",
        f"STAR mismatches: {_md(report.star_mismatches)}",
        f"Protected-file integrity before: {report.integrity_before}; "
        f"after: {report.integrity_after}",
        "Policy audit: " + ("; ".join(map(_md, report.policy_audit)) or "passed"),
        "Human review: not recorded",
        "",
        "## Stages",
        "",
        "| Stage | Code origin | Status | Own status | Artifacts | Handoff | Outputs re-hashed | "
        "Output directory | Note |",
        "|---|---|---|---|---:|---|---:|---|---|",
    ]
    lines.extend(
        f"| {_md(s.program)} | {_md(s.code_origin)} | {_md(s.status)} | {_md(s.own_status)} "
        f"| {s.artifacts_passed}/{s.artifacts_total} | {s.handoff} ({s.handoff_artifacts_checked}) "
        f"| {s.output_files_rechecked} | {_md(s.output_directory)} | {_md(s.note) or 'none'} |"
        for s in report.stages
    )
    lines.extend(
        [
            "",
            "## Artifact comparisons",
            "",
            "| Program | Artifact | Status | Rows actual / SAS | Columns actual / SAS | "
            "Mismatched cells | Missingness mismatches | Policy |",
            "|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    lines.extend(
        f"| {_md(a.program)} | {_md(a.artifact)} | {a.status} | {_md(a.actual_rows)} / "
        f"{_md(a.expected_rows)} | {_md(a.actual_columns)} / {_md(a.expected_columns)} "
        f"| {_md(a.mismatched_cells)} | {_md(a.missingness_mismatches)} | {_md(a.policy)} |"
        for a in report.artifacts
    )
    lines.extend(["", "Earliest divergence: " + _md(report.earliest_divergence or "none")])
    lines.extend(
        [
            "Evidence issues: "
            + (", ".join(map(_md, report.evidence_issues)) or "none found by these checks"),
            "",
            "## Hashes",
            "",
            "| Item | SHA-256 |",
            "|---|---|",
        ]
    )
    groups = {
        "record": report.record_hashes,
        "policy": report.policy_hashes,
        "SAS reference": report.sas_reference_hashes,
        **{f"{p} output": h for p, h in report.stage_output_hashes.items()},
    }
    lines.extend(
        f"| {_md(group)}: {_md(name)} | {_md(digest)} |"
        for group, hashes in groups.items()
        for name, digest in sorted(hashes.items())
    )
    lines.extend(["", "## Environment", ""])
    lines.extend(f"* {_md(k)}: {_md(v)}" for k, v in sorted(report.environment.items()))
    lines.append(f"* environment_sha256: {_md(report.environment_sha256)}")
    lines.extend(
        [
            "",
            "Only an allowlist of environment fields is shown and key-like strings are "
            "redacted. This is not a general secret scanner; Abt must review before release.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_pipeline_report(project_root: Path, run_directory: Path, target: Path) -> None:
    """Write into the already validated, newly created ``target`` directory."""
    report = read_pipeline_report(project_root, run_directory)
    payload = report.model_dump(mode="json")
    payload["pipeline_status"] = report.scope_status
    (target / "report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (target / "handoff.md").write_text(render_pipeline_handoff(report), encoding="utf-8")
    (target / "technical.md").write_text(render_pipeline_technical(report), encoding="utf-8")
