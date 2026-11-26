"""Render draft handoffs from the host-validated July 2025 replay."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sasguard.data import load_artifact
from sasguard.execution.result import ExecutionResult
from sasguard.provenance.hashing import sha256_file
from sasguard.reporting.models import ScopeStatus
from sasguard.reporting.reader import safe_file
from sasguard.verification.artifact import ArtifactComparison

STAGES = (
    "Saved model candidate after two automatic repairs",
    "Human-written Python reference",
    "Saved model candidate with a manual STRICT correction",
)


@dataclass(frozen=True)
class ReplayStage:
    execution: ExecutionResult | None
    validation: str
    comparisons: Mapping[str, ArtifactComparison]


def rating_totals(run: Path, expected_hash: str) -> tuple[int, int, dict[int, int]]:
    """Read only aggregates from the already validated final ratings file."""
    path = safe_file(run, "output/star_2025jul.csv")
    if sha256_file(path, normalize_text=False) != expected_hash:
        raise ValueError("rating output changed after comparison")
    frame = load_artifact(path, key="PROVIDER_ID").frame
    if sha256_file(path, normalize_text=False) != expected_hash:
        raise ValueError("rating output changed while calculating totals")
    return (
        len(frame),
        int(frame["REPORT_INDICATOR"].eq(1).sum()),
        {rating: int(frame["STAR"].eq(rating).sum()) for rating in range(1, 6)},
    )


def write_replay_reports(
    run: Path,
    *,
    run_date: str,
    status: ScopeStatus,
    stages: list[ReplayStage],
    protected_files_checked: int,
    integrity_passed: bool,
    totals: tuple[int, int, dict[int, int]] | None,
) -> None:
    """Publish only run metadata and aggregates from a single replay."""
    passed = sum(item.passed for stage in stages for item in stage.comparisons.values())
    scope = f"{status.value} for the supplied CMS July 2025 release."
    client = [
        "# CMS July 2025 hospital star ratings summary",
        "",
        "Draft for Abt review before sharing with CMS.",
        "",
        f"Run date (UTC): {run_date}",
        "",
        scope,
        f"{passed} of 10 supplied SAS artifact comparisons passed.",
    ]
    if totals is not None and status is ScopeStatus.VERIFIED:
        processed, eligible, ratings = totals
        client.extend(
            [
                "",
                f"Processed {processed:,} hospitals. {eligible:,} met the rating criteria.",
                "All individual star assignments matched SAS.",
                "",
                "| Star rating | Hospitals |",
                "|---|---:|",
                *(f"| {rating} | {count:,} |" for rating, count in ratings.items()),
                f"| Unrated | {processed - sum(ratings.values()):,} |",
            ]
        )
    if len(stages) == 3 and stages[2].execution and stages[2].execution.passed:
        client.extend(
            [
                "",
                "The run used model-generated and human-written Python, including a manual "
                "clustering correction in Program 2.",
            ]
        )
    client.extend(["", "Abt review and approval for release are pending."])

    technical = [
        "# Abt technical validation report",
        "",
        f"{scope} Run date (UTC): {run_date}.",
        "Independent teammate replay and Abt approval are separate from this run record.",
        "",
        "| Program | Code origin | Docker execution | Validation | SAS comparisons passed |",
        "|---|---|---|---|---:|",
    ]
    for program, (origin, expected) in enumerate(zip(STAGES, (3, 5, 2), strict=True)):
        if program >= len(stages):
            technical.append(f"| {program} | {origin} | Not run | Not run | 0/{expected} |")
            continue
        stage = stages[program]
        execution = stage.execution.status.value if stage.execution else "not run"
        if stage.execution and stage.execution.exit_code is not None:
            execution += f" (exit {stage.execution.exit_code})"
        count = sum(item.passed for item in stage.comparisons.values())
        technical.append(
            f"| {program} | {origin} | {execution} | {stage.validation} | {count}/{expected} |"
        )
    technical.extend(
        [
            "",
            f"Protected file integrity: {'passed' if integrity_passed else 'failed'} "
            f"({protected_files_checked} files checked).",
            "",
            "| Artifact | Result | Rows actual / SAS | Columns actual / SAS | "
            "Missing / extra keys | Missingness mismatches | Mismatched cells |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for stage in stages:
        for result in stage.comparisons.values():
            # The national-averages comparator adds a host-only row key.
            host_key = int(result.artifact == "NATIONAL_AVERAGE_2025JUL")
            technical.append(
                f"| {result.artifact} | {'Pass' if result.passed else 'Fail'} "
                f"| {result.actual_rows} / {result.expected_rows} "
                f"| {len(result.actual_columns) - host_key} / "
                f"{len(result.expected_columns) - host_key} "
                f"| {len(result.missing_keys)} / {len(result.extra_keys)} "
                f"| {result.missingness_mismatches} | {result.mismatched_cells} |"
            )
    image_ids = sorted(
        {
            stage.execution.runtime_environment.image_id
            for stage in stages
            if stage.execution and stage.execution.runtime_environment
        }
    )
    if image_ids:
        technical.extend(["", "Docker image IDs", "", *(f"- `{image}`" for image in image_ids)])
    # Report the first failed stage even if it stopped before any artifact could be compared.
    for program, stage in enumerate(stages):
        if stage.validation != "passed":
            failures = [item.artifact for item in stage.comparisons.values() if not item.passed]
            detail = f" ({', '.join(failures)})" if failures else ""
            technical.extend(["", f"First failed stage: Program {program}{detail}."])
            break
    technical.extend(
        [
            "",
            "See `summary.json` for the run status, evidence paths and recorded hashes. "
            "The validator used the fixed per-artifact SAS comparison policies.",
        ]
    )
    (run / "cms-summary.md").write_text("\n".join(client) + "\n", encoding="utf-8")
    (run / "abt-validation.md").write_text("\n".join(technical) + "\n", encoding="utf-8")
