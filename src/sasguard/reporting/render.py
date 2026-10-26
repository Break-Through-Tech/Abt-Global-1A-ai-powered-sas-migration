"""Markdown and JSON rendering without model calls or candidate execution."""

from __future__ import annotations

import html
import json
from pathlib import Path
from uuid import uuid4

from sasguard.reporting.models import RunReport, ScopeStatus
from sasguard.reporting.reader import read_run_report, report_runs_directory


def _md(value: object) -> str:
    if value is None:
        return "Not recorded"
    text = html.escape(str(value), quote=False).replace("\r", " ").replace("\n", " ")
    for character in ("\\", "|", "`", "*", "_", "[", "]", "#"):
        text = text.replace(character, "\\" + character)
    return text


def _mortality_match_summary(report: RunReport) -> str | None:
    if report.scope_status is not ScopeStatus.VERIFIED:
        return None
    artifact = next((item for item in report.artifacts if item.name == "OUTCOME_MORTALITY"), None)
    if artifact is None:
        return None
    if (
        artifact.actual_rows is not None
        and artifact.actual_rows >= 0
        and artifact.actual_rows == artifact.expected_rows
        and artifact.actual_columns
        and artifact.actual_columns == artifact.expected_columns
    ):
        return (
            "The saved comparison matched the Mortality output to the supplied SAS reference "
            f"across {artifact.actual_rows:,} provider rows and "
            f"{len(artifact.actual_columns):,} columns, within the configured tolerances."
        )
    return (
        "The saved Mortality comparison passed against the supplied SAS reference "
        "under the configured comparison policy."
    )


def render_handoff(report: RunReport) -> str:
    """Only a bounded, privacy-limited summary, never a final ratings handoff."""
    date = report.run_timestamp.isoformat() if report.run_timestamp else "Not recorded"
    lines = [
        "# Migration run summary",
        "",
        "Internal draft. Abt review and approval are required before sharing with CMS.",
        "",
        f"Scope status: {report.scope_status.value}",
        "Full-pipeline status: NOT VERIFIED",
        "",
        f"Run: {_md(report.run_id)}",
        f"Run date: {_md(date)}",
        f"Input release: {_md(report.input_release)}",
        "",
        f"Scope: {_md(report.scope)}",
        "",
    ]
    summary = _mortality_match_summary(report)
    if summary is not None:
        lines.extend([summary, ""])
    lines.extend(
        [
            "Code origin: "
            + (
                "human-written reference Python."
                if report.code_origin == "human_reference"
                else "model-generated candidate Python."
                if report.code_origin == "model_generated"
                else "not recorded; do not infer AI generation or human authorship."
            ),
            f"Recorded execution: {_md(report.execution_status)}.",
            f"Recorded comparison: {_md(report.validation_status)}.",
            "Human review of this run: not recorded.",
            "",
            "Hospital processing totals, eligibility totals, and final ratings are not available "
            "from this partial run. This is not a CMS ratings report.",
            "",
        ]
    )
    if report.report_kind == "program0":
        outcome_description = {
            "passed": "All three declared outputs passed the recorded SAS comparison.",
            "failed": "At least one artifact failed its recorded SAS comparison.",
            "not_run": "No SAS comparison was recorded.",
            "hash_mismatch": "The validator reported an output changed after collection.",
            "missing_outputs": "The validator reported missing output files.",
            "malformed_outputs": "The validator could not read or align output files.",
            "validator_error": "The validator did not complete; no comparison pass is established.",
        }.get(report.validation_outcome or "", "Validation outcome was not recorded.")
        lines.extend(
            [
                "",
                f"Input source: {_md(report.input_format)}.",
                f"Recorded generation: {_md(report.generation_status)}.",
                f"Collection outcome: {_md(report.collection_status)}.",
                f"Recorded validator outcome: {_md(report.validation_outcome)}.",
                outcome_description,
                "",
                "## Program 0 artifact results",
                "",
            ]
        )
        lines.extend(f"* {_md(item.name)}: {_md(item.status)}." for item in report.artifacts)
        lines.extend(
            [
                "",
                "This is a Program 0 demonstration, not a verified full-pipeline "
                "or CMS ratings report.",
            ]
        )
        if report.scope_status is ScopeStatus.VERIFIED:
            lines.extend(
                [
                    "",
                    "All three declared Program 0 outputs matched their supplied SAS references "
                    "under the recorded comparison rules.",
                ]
            )
    lines.extend(["", "## Limits", ""])
    lines.extend(f"* {_md(limit)}" for limit in report.limitations)
    if report.evidence_integrity != "matched":
        lines.extend(
            [
                "",
                "The recorded evidence could not be fully confirmed. "
                "Do not use a recorded pass as current verification.",
            ]
        )
    if report.report_kind == "synthetic":
        lines.extend(
            [
                "",
                "Any passing comparison is against handwritten synthetic expectations, "
                "not trusted SAS outputs.",
            ]
        )
    return "\n".join(lines) + "\n"


def render_technical(report: RunReport) -> str:
    model_identifier = report.model_name or (
        "Not recorded" if report.code_origin == "not_recorded" else "Not applicable"
    )
    lines = [
        "# Abt technical validation record",
        "",
        "Internal draft. This summarizes saved evidence without rerunning code or comparisons.",
        "",
        f"Scope status: {report.scope_status.value}",
        f"Scope: {_md(report.scope)}",
        f"Evidence integrity: {_md(report.evidence_integrity)}",
        "",
        "## Separate claims",
        "",
        "| Event | Recorded result |",
        "|---|---|",
        f"| Code origin | {_md(report.code_origin)} |",
        f"| Model generation | {_md(report.generation_status)} |",
        f"| Execution | {_md(report.execution_status)} |",
        f"| Deterministic comparison | {_md(report.validation_status)} |",
        "| Human review of run | Not recorded |",
        "",
        f"Model identifier: {_md(model_identifier)}",
        f"Input source: {_md(report.input_format)}",
        f"Collection outcome: {_md(report.collection_status)}",
        f"Recorded validator outcome: {_md(report.validation_outcome)}",
        "Validator failure artifacts: "
        + (", ".join(_md(name) for name in report.validation_failure_files) or "None recorded"),
        "Exact statistic rows: "
        + (", ".join(_md(name) for name in report.exact_statistic_rows) or "Not recorded"),
        "Validation contract: "
        + _md(report.validation_policy_version or "Recorded artifact policy"),
        f"Docker image ID: {_md(report.docker_image_id or 'Not recorded')}",
        f"Execution time in seconds: {_md(report.runtime_seconds)}",
        f"Process exit code: {_md(report.exit_code)}",
        "",
        "Original invocation: not recorded. No invocation is inferred from a successful exit.",
        f"Repair attempts: {_md(report.repair_attempts)}. Manual changes: not recorded.",
        "",
        "## Artifact checks",
        "",
        "Rows below are artifact rows, not hospital processing or eligibility totals.",
        "",
        "| Artifact | Check | Reference authority | Expected rows | Actual rows | "
        "Missing keys | Extra keys | Mismatched cells | Missingness mismatches |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for artifact in report.artifacts:
        values = (
            artifact.name,
            artifact.status,
            artifact.reference_authority,
            artifact.expected_rows,
            artifact.actual_rows,
            artifact.missing_key_count,
            artifact.extra_key_count,
            artifact.mismatched_cells,
            artifact.missingness_mismatches,
        )
        lines.append("| " + " | ".join(_md(value) for value in values) + " |")
    for artifact in report.artifacts:
        lines.extend(
            [
                "",
                f"### {_md(artifact.name)}",
                "",
                "Expected columns: "
                + (", ".join(_md(name) for name in artifact.expected_columns) or "Not recorded"),
                "Actual columns: "
                + (", ".join(_md(name) for name in artifact.actual_columns) or "Not recorded"),
                "Missing columns: "
                + (", ".join(_md(name) for name in artifact.missing_columns) or "None recorded"),
                "Extra columns: "
                + (", ".join(_md(name) for name in artifact.extra_columns) or "None recorded"),
                "Mismatched columns: "
                + (", ".join(_md(name) for name in artifact.mismatched_columns) or "None recorded"),
                f"Maximum absolute error: {_md(artifact.max_abs_error)}",
                f"Mean absolute error: {_md(artifact.mean_abs_error)}",
                "",
            ]
        )
        if artifact.policy is not None:
            lines.extend(
                [
                    "Policy from saved evidence:",
                    "",
                    "```json",
                    artifact.policy.to_json().rstrip(),
                    "```",
                ]
            )
        else:
            lines.append("Comparison policy not available.")
    lines.extend(
        [
            "",
            "## Failures and unchecked work",
            "",
            "First observed failed artifact checkpoints: "
            + (", ".join(_md(name) for name in report.first_observed_failures) or "None recorded"),
            "Unchecked artifact checkpoints: "
            + (
                ", ".join(_md(name) for name in report.not_checked) or "No lineage detail available"
            ),
            "Evidence issues: "
            + (
                ", ".join(_md(issue) for issue in report.evidence_issues)
                or "None found by these report checks"
            ),
            "",
            "A failed process and an analytical mismatch are different outcomes. "
            "Missing comparison details do not imply a pass.",
            "",
            "## Recorded evidence hashes",
            "",
            "These are recorded digests. Evidence issues above override any verified claim.",
            "",
            "| Evidence | SHA-256 |",
            "|---|---|",
        ]
    )
    lines.extend(
        f"| {_md(name)} | {_md(digest)} |"
        for name, digest in sorted(report.evidence_hashes.items())
    )
    lines.extend(
        [
            "",
            "Raw stdout, stderr, prompts, responses, generated code, and row-level provider "
            "identifiers are intentionally omitted. This is not a general secret scanner; "
            "Abt must review metadata and both summaries before release.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_run_report(
    project_root: Path,
    run_directory: Path,
    *,
    output_directory: Path | None = None,
) -> Path:
    """Write a new report directory, never overwrite source records or existing output."""
    root = project_root.resolve()
    run = (run_directory if run_directory.is_absolute() else root / run_directory).resolve()
    report = read_run_report(root, run)
    target = output_directory or Path("reports/runs") / f"handoff-{uuid4()}"
    target = (target if target.is_absolute() else root / target).resolve()
    if (
        target.parent != report_runs_directory(root)
        or target.is_relative_to(run)
        or run.is_relative_to(target)
    ):
        raise ValueError(
            "report output must be a separate new directory directly under reports/runs"
        )
    target.mkdir(parents=True, exist_ok=False)
    payload = report.model_dump(mode="json")
    payload["scope_status"] = report.scope_status.value
    payload["pipeline_status"] = "NOT VERIFIED"
    (target / "report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (target / "handoff.md").write_text(render_handoff(report), encoding="utf-8")
    (target / "technical.md").write_text(render_technical(report), encoding="utf-8")
    return target
