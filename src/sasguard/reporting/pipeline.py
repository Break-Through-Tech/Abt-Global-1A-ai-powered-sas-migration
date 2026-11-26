"""Reports for ``validate-pipeline`` run directories.

Reads the saved ``pipeline-validation.json`` only. It reruns nothing, calls no model and
re-hashes only files already inside the run directory. A run that cannot be confirmed
against its own record is labelled FAILED, never VERIFIED.
"""

from __future__ import annotations

import html
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
    reviewed_by: str
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
    earliest_divergence_cms: str | None
    integrity_before: str
    integrity_after: str
    policy_audit: tuple[str, ...]
    hospitals_processed: int | None
    hospitals_eligible: int | None
    star_distribution: dict[str, int] | None
    counts_note: str
    evidence_issues: tuple[str, ...]
    unverified_evidence: tuple[str, ...]
    record_hashes: dict[str, str]
    environment: dict[str, str]
    environment_sha256: str
    policy_hashes: dict[str, str]
    sas_reference_hashes: dict[str, str]
    stage_output_hashes: dict[str, dict[str, str]]
    human_review: Literal["not_recorded"] = "not_recorded"
    client_release_approved: Literal[False] = False


FIXED_DETAILS = frozenset(
    {
        "file is missing",
        "file is present but could not be read or compared",
        "copied input differs from the actual upstream output",
        "protected files changed or could not be verified",
        "comparison tolerance differs from the fixed 1e-12 contract",
        "schema differs from the SAS artifact",
        "keys differs from the SAS artifact",
    }
)
COUNT_DETAIL = re.compile(r"\d+ mismatched cells, \d+ missingness mismatches")


def _fixed_wording(kind: str, detail: str) -> bool:
    """True when a divergence detail comes from a fixed template that names no provider."""
    if kind == "value":
        return COUNT_DETAIL.fullmatch(detail) is not None
    return detail in FIXED_DETAILS


def _integrity_text(values: dict[str, int | bool]) -> str:
    return (
        f"{values.get('checked_files')}/{values.get('expected_files')} "
        f"({'passed' if values.get('passed') else 'failed'})"
    )


def _recheck(
    run: Path, stage: StageResult, issues: list[str], unverified: list[str]
) -> tuple[int, Path | None]:
    """Re-hash recorded stage outputs that are inside the run directory.

    Changed or vanished files are record problems. A stage whose outputs cannot be
    re-checked at all, or only in part, is unverified evidence: the run cannot be VERIFIED.
    """
    name = Path(stage.output_directory).name
    directory = run / name
    if not name or directory.is_symlink() or not directory.is_dir():
        unverified.append(f"{stage.program}:output_directory_missing_or_unsafe")
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
    expected = len(stage.artifacts)
    if checked < expected:
        unverified.append(f"{stage.program}:only_{checked}_of_{expected}_outputs_rechecked")
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
    unverified: list[str] = []
    _consistency(record, issues)
    summary = run / "summary.md"
    if summary.is_file() and summary.read_text(encoding="utf-8") != render_summary(record):
        issues.append("summary_md_disagrees_with_record")
    rechecked: dict[str, int] = {}
    directories: dict[int, Path | None] = {}
    for stage in record.stages:
        count, directory = _recheck(run, stage, issues, unverified)
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
            reviewed_by=_clean(stage.reviewed_by),
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
    elif record.status == "PASS" and integrity_ok and not record.policy_audit and not unverified:
        scope_status = "VERIFIED"
    else:
        scope_status = "NOT VERIFIED"

    # Totals are released only when every stage's recorded outputs were re-checked intact.
    totals = (
        _totals(directories.get(2), record.stages[2], record)
        if len(record.stages) == 3 and not unverified and not issues
        else None
    )
    counts_note = (
        "Program 2 output was not found in the run directory or did not match its record."
        if not unverified and not issues
        else "Not every stage's recorded outputs could be re-checked in the run directory."
    )
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
    # The CMS draft names no provider and no header that a candidate output could have
    # introduced: only columns from the SAS reference schema are shown. The key and any
    # unexpected header stay in the technical record.
    trusted_columns = {
        column.upper()
        for stage in record.stages
        for outcome in stage.artifacts
        if outcome.comparison is not None
        for column in outcome.comparison.expected_columns
    }
    if divergence is None or not divergence.column:
        column_cms = "n/a"
    elif divergence.column.upper() in trusted_columns:
        column_cms = divergence.column
    else:
        column_cms = "not in the SAS schema (named in the technical record)"
    divergence_cms = (
        None
        if divergence is None
        else _clean(
            f"{divergence.program}, artifact {divergence.artifact}, {divergence.kind}; "
            f"column {column_cms}. "
            + (
                divergence.detail
                if _fixed_wording(divergence.kind, divergence.detail)
                else "Details are in the technical record."
            )
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
        earliest_divergence_cms=divergence_cms,
        integrity_before=_integrity_text(record.integrity_before),
        integrity_after=_integrity_text(record.integrity_after),
        policy_audit=tuple(_clean(item) for item in record.policy_audit),
        hospitals_processed=processed,
        hospitals_eligible=eligible,
        star_distribution=distribution,
        counts_note=counts_note,
        evidence_issues=tuple(sorted(set(issues))),
        unverified_evidence=tuple(sorted(set(unverified))),
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


def _note(stage: StageRow) -> str:
    parts = [_md(stage.note)] if stage.note else []
    if stage.reviewed_by:
        parts.append(f"reviewed by {_md(stage.reviewed_by)} (as recorded at run time)")
    return "; ".join(parts) or "none"


def _review_summary(report: PipelineRunReport) -> str:
    reviewed = [f"{_md(s.program)} by {_md(s.reviewed_by)}" for s in report.stages if s.reviewed_by]
    return ("recorded for " + ", ".join(reviewed)) if reviewed else "not recorded"


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
        f"({s.artifacts_passed}/{s.artifacts_total} artifacts) | {_note(s)} |"
        for s in report.stages
    )
    unreviewed = [
        s
        for s in report.stages
        if s.code_origin != ORIGINS["human_reference"] and not s.reviewed_by
    ]
    if unreviewed:
        lines.extend(
            [
                "",
                "Stages not marked as human reference were not written by a team member; "
                + ", ".join(_md(s.program) for s in unreviewed)
                + (" has" if len(unreviewed) == 1 else " have")
                + " no recorded human review. A matching result does not replace that "
                "review.",
            ]
        )
    if report.unverified_evidence:
        lines.extend(
            [
                "",
                "Not every stage's outputs could be re-checked against the record, so this run "
                "cannot be VERIFIED: " + ", ".join(_md(i) for i in report.unverified_evidence),
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
            "* Human review: " + _review_summary(report) + ". Abt approval: not recorded.",
        ]
    )
    if report.evidence_issues:
        lines.extend(["", "Record problems: " + ", ".join(_md(i) for i in report.evidence_issues)])
    if report.earliest_divergence_cms:
        lines.extend(["", f"Earliest divergence: {_md(report.earliest_divergence_cms)}"])
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
        "Human review: " + _review_summary(report),
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
        f"| {s.output_files_rechecked} | {_md(s.output_directory)} | {_note(s)} |"
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
            "Unverified evidence: " + (", ".join(map(_md, report.unverified_evidence)) or "none"),
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


HTML_STYLE = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1d2330;--muted:#5b6475;--line:#d9dde5;--bar:#44546a;
--ok:#1b7a43;--ok-bg:#e3f4ea;--warn:#8a5a00;--warn-bg:#fff1d0;--bad:#b3261e;--bad-bg:#fbe4e2}
@media (prefers-color-scheme:dark){:root{--bg:#14171d;--card:#1d222b;--text:#e8ebf0;
--muted:#a3acbb;--line:#363d4a;--bar:#8fa3bf;--ok:#6fd49a;--ok-bg:#16301f;--warn:#f2c35b;
--warn-bg:#35290d;--bad:#ff8f87;--bad-bg:#3a1917}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);line-height:1.5;
font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 40px}
h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.1rem;margin:28px 0 10px}
.sub{color:var(--muted);margin:0 0 20px}
.badge{border-radius:10px;padding:18px 20px;border:2px solid var(--accent);
background:var(--accent-bg);color:var(--accent)}
.badge strong{display:block;font-size:2rem;letter-spacing:.03em;line-height:1.2}
.badge span{color:var(--text)}
.s-verified{--accent:var(--ok);--accent-bg:var(--ok-bg)}
.s-notverified{--accent:var(--warn);--accent-bg:var(--warn-bg)}
.s-failed{--accent:var(--bad);--accent-bg:var(--bad-bg)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;
margin-top:16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.tile b{display:block;font-size:1.6rem}.tile span{color:var(--muted);font-size:.9rem}
.tablewrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line)}
th,td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--line)}
th{font-size:.85rem;color:var(--muted)}
.bars{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.row{display:grid;grid-template-columns:90px 1fr 80px;gap:10px;align-items:center;margin:6px 0}
.track{background:var(--bg);border:1px solid var(--line);height:18px;border-radius:4px}
.fill{background:var(--bar);height:100%;border-radius:3px}
.row output{text-align:right;font-variant-numeric:tabular-nums}
.note{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);
border-radius:6px;padding:10px 14px;margin:10px 0}
ul{padding-left:20px}
footer{margin-top:32px;color:var(--muted);font-size:.85rem}
@media print{body{background:#fff;color:#000}main{max-width:none;padding:0}
.badge,.tile,.note,table,.bars{break-inside:avoid}
.fill{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


def _h(value: object) -> str:
    """Escape a value for HTML after the same secret redaction the handoff applies."""
    return html.escape(_clean(value), quote=True)


def _html_status_sentence(report: PipelineRunReport) -> str:
    if report.scope_status == "VERIFIED":
        return (
            "Programs 0, 1 and 2 were run as Python and every output, every handoff between "
            "programs, and every individual star assignment matched the supplied SAS artifacts."
        )
    if report.scope_status == "NOT VERIFIED":
        return (
            "Only part of the pipeline matched SAS. These are not CMS star ratings and must "
            "not be used as such."
        )
    return (
        "The run FAILED validation or its record could not be confirmed. These are not CMS "
        "star ratings and must not be used as such."
    )


def _html_stage_note(stage: StageRow) -> str:
    parts = [_h(stage.note)] if stage.note else []
    if stage.reviewed_by:
        parts.append(f"reviewed by {_h(stage.reviewed_by)} (as recorded at run time)")
    return "; ".join(parts) or "none"


def _html_distribution(report: PipelineRunReport) -> str:
    if report.hospitals_processed is None:
        return "<p>Hospital counts are unavailable. " + _h(report.counts_note) + "</p>"
    intro = (
        f"<p>Processed {report.hospitals_processed:,} hospitals; "
        f"{report.hospitals_eligible or 0:,} met the rating criteria.</p>"
    )
    if report.star_distribution is None:
        return intro + "<p>Star distribution is not shown for a run that is not VERIFIED.</p>"
    counts = {
        (f"{k} star" if k == "1" else f"{k} stars"): v for k, v in report.star_distribution.items()
    }
    counts["Unrated"] = report.hospitals_processed - sum(report.star_distribution.values())
    peak = max(counts.values(), default=0) or 1
    rows = "".join(
        f'<div class="row"><span>{_h(name)}</span>'
        f'<div class="track"><div class="fill" style="width:{value / peak * 100:.1f}%"></div></div>'
        f"<output>{value:,}</output></div>"
        for name, value in counts.items()
    )
    return (
        intro + f'<div class="bars" role="group" aria-label="Star rating distribution">{rows}</div>'
    )


def render_pipeline_html(report: PipelineRunReport) -> str:
    """Standalone CMS-safe view. Built only from the fields and wording the handoff uses."""
    label = report.scope_status
    css_class = {"VERIFIED": "s-verified", "NOT VERIFIED": "s-notverified"}.get(label, "s-failed")
    confirmed = not report.evidence_issues
    comparisons = (
        f"{report.artifacts_passed} of {report.artifacts_total} SAS artifact comparisons passed."
        if confirmed
        else f"The record claims {report.artifacts_passed} of {report.artifacts_total} SAS "
        "artifact comparisons passed, but the record could not be confirmed, so that count "
        "is not relied on."
    )
    tiles = [
        (
            f"{report.artifacts_passed} / {report.artifacts_total}",
            "artifact comparisons passed" if confirmed else "comparisons claimed (not relied on)",
        )
    ]
    if report.star_mismatches is not None and confirmed:
        tiles.append((f"{report.star_mismatches:,}", "STAR mismatches against SAS"))
    tiles.append(
        (
            "Passed"
            if report.integrity_before == report.integrity_after
            and report.integrity_before.endswith("(passed)")
            else _h(report.integrity_before) + " / " + _h(report.integrity_after),
            "protected-file integrity, before and after the run",
        )
    )
    tile_html = "".join(
        f'<div class="tile"><b>{value}</b><span>{html.escape(text)}</span></div>'
        for value, text in tiles
    )
    stage_rows = "".join(
        f"<tr><td>{_h(s.program)}</td><td>{_h(s.code_origin)}</td>"
        f"<td>{'reviewed by ' + _h(s.reviewed_by) if s.reviewed_by else 'no recorded human review'}"
        f"</td><td>{_h(s.status)} ({s.artifacts_passed}/{s.artifacts_total} artifacts)</td>"
        f"<td>{'not applicable' if s.handoff == 'not_applicable' else s.handoff}</td>"
        f"<td>{_html_stage_note(s)}</td></tr>"
        for s in report.stages
    )
    notes: list[str] = []
    unreviewed = [
        s
        for s in report.stages
        if s.code_origin != ORIGINS["human_reference"] and not s.reviewed_by
    ]
    if unreviewed:
        notes.append(
            "Stages not marked as human reference were not written by a team member; "
            + ", ".join(_h(s.program) for s in unreviewed)
            + (" has" if len(unreviewed) == 1 else " have")
            + " no recorded human review. A matching result does not replace that review."
        )
    if report.unverified_evidence:
        notes.append(
            "Not every stage's outputs could be re-checked against the record, so this run "
            "cannot be VERIFIED: " + ", ".join(_h(i) for i in report.unverified_evidence)
        )
    if report.evidence_issues:
        notes.append("Record problems: " + ", ".join(_h(i) for i in report.evidence_issues))
    if report.earliest_divergence_cms:
        notes.append(f"Earliest divergence: {_h(report.earliest_divergence_cms)}")
    notes.append(
        "Human review: "
        + _h(_review_summary(report))
        + ". Abt approval: not recorded. This is not Abt or CMS approval."
    )
    scope_note = (
        "Verified against the supplied SAS artifacts: the ten comparison artifacts and the "
        "copied handoffs between programs, within the fixed 1e-12 tolerance."
        if label == "VERIFIED"
        else "Compared against the supplied SAS artifacts: the ten comparison artifacts and "
        "the copied handoffs between programs, within the fixed 1e-12 tolerance. This run did "
        "not verify them; see the status above."
    )
    checked = [
        scope_note,
        "Trusted, not independently verified: the supplied SAS outputs and the CMS input "
        "data themselves.",
        "Not checked: any release other than July 2025, SAS runtime behaviour, statistical "
        "correctness of the CMS method, and generated-code quality.",
    ]
    note_html = "".join(f'<div class="note">{n}</div>' for n in notes)
    checked_html = "".join(f"<li>{html.escape(c)}</li>" for c in checked)
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        "<title>SASGuard pipeline validation</title>"
        f"<style>{HTML_STYLE}</style></head>\n"
        f'<body><main class="{css_class}">'
        "<h1>SASGuard pipeline validation</h1>"
        '<p class="sub">CMS July 2025 hospital star ratings. Internal draft. Abt review and '
        "approval are required before sharing with CMS.</p>"
        f'<section class="badge" aria-label="Validation status"><strong>{html.escape(label)}'
        f"</strong><span>{html.escape(_html_status_sentence(report))}</span></section>"
        f'<p>{html.escape(comparisons)}</p><div class="tiles">{tile_html}</div>'
        "<h2>Stages and code origin</h2>"
        '<div class="tablewrap"><table><thead><tr><th>Program</th><th>Code origin</th>'
        "<th>Review</th><th>Outputs passed</th><th>Handoff check</th><th>Note</th></tr></thead>"
        f"<tbody>{stage_rows}</tbody></table></div>"
        f"<h2>Hospitals</h2>{_html_distribution(report)}"
        f"<h2>What was and was not checked</h2><ul>{checked_html}</ul>"
        f"<h2>Caveats</h2>{note_html}"
        f"<footer>Input release: {_h(report.input_release)}. Run date: {_h(report.run_date)} "
        f"({_h(report.run_date_source)}).</footer>"
        "</main></body></html>\n"
    )


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
    (target / "report.html").write_text(render_pipeline_html(report), encoding="utf-8")
