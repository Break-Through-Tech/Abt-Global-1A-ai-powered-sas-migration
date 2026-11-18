"""Reporting facts kept separate from raw logs, prompts, code, and provider identifiers."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sasguard.verification.artifact import ArtifactComparison
from sasguard.verification.policy import ArtifactComparisonPolicy


class ScopeStatus(StrEnum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    NOT_VERIFIED = "NOT VERIFIED"


class ArtifactSummary(BaseModel):
    """Aggregate comparison facts only. Never retain missing/extra provider-key values."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    status: Literal["passed", "failed", "not_checked"]
    reference_authority: Literal["supplied_sas", "handwritten_synthetic", "unknown"]
    expected_rows: int | None = None
    actual_rows: int | None = None
    expected_columns: tuple[str, ...] = ()
    actual_columns: tuple[str, ...] = ()
    missing_columns: tuple[str, ...] = ()
    extra_columns: tuple[str, ...] = ()
    mismatched_columns: tuple[str, ...] = ()
    missing_key_count: int | None = None
    extra_key_count: int | None = None
    mismatched_cells: int | None = None
    missingness_mismatches: int | None = None
    max_abs_error: float | None = None
    mean_abs_error: float | None = None
    policy: ArtifactComparisonPolicy | None = None


class RunReport(BaseModel):
    """An internal draft about a bounded recorded run, never a CMS ratings product."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    report_kind: Literal["mortality", "synthetic"]
    run_id: str
    run_timestamp: datetime | None
    input_release: str
    scope: str
    code_origin: Literal["human_reference", "model_generated"]
    generation_status: Literal["not_applicable", "succeeded", "failed"]
    execution_status: str
    validation_status: Literal["passed", "failed", "not_run"]
    evidence_integrity: Literal["matched", "not_confirmed"]
    evidence_issues: tuple[str, ...] = ()
    model_name: str | None = None
    validation_policy_version: str | None = None
    docker_image_id: str | None = None
    runtime_seconds: float | None = None
    exit_code: int | None = None
    artifacts: tuple[ArtifactSummary, ...]
    evidence_hashes: dict[str, str] = Field(default_factory=dict)
    first_observed_failures: tuple[str, ...] = ()
    not_checked: tuple[str, ...] = ()
    limitations: tuple[str, ...]
    human_review: Literal["not_recorded"] = "not_recorded"
    manual_changes: Literal["not_recorded"] = "not_recorded"
    repair_attempts: int | None = None
    recorded_command: None = None
    pipeline_complete: Literal[False] = False
    client_release_approved: Literal[False] = False
    hospitals_processed: None = None
    hospitals_eligible: None = None
    final_ratings: None = None

    @property
    def scope_status(self) -> ScopeStatus:
        if self.evidence_integrity != "matched":
            return ScopeStatus.NOT_VERIFIED
        if (
            self.generation_status == "failed"
            or self.execution_status not in ("succeeded", "not_recorded")
            or self.validation_status == "failed"
        ):
            return ScopeStatus.FAILED
        if (
            self.report_kind == "mortality"
            and self.execution_status == "succeeded"
            and self.validation_status == "passed"
            and self.artifacts
            and all(
                artifact.status == "passed"
                and artifact.reference_authority == "supplied_sas"
                and artifact.policy is not None
                for artifact in self.artifacts
            )
        ):
            return ScopeStatus.VERIFIED
        return ScopeStatus.NOT_VERIFIED


def summarize_artifact(
    comparison: ArtifactComparison | None,
    *,
    name: str,
    authority: Literal["supplied_sas", "handwritten_synthetic", "unknown"],
    policy: ArtifactComparisonPolicy | None,
    validation_failed: bool = False,
) -> ArtifactSummary:
    """Deliberately omit row-level key lists and arbitrary diagnostic text."""
    if comparison is None:
        return ArtifactSummary(
            name=name,
            reference_authority=authority,
            policy=policy,
            status="failed" if validation_failed else "not_checked",
        )
    return ArtifactSummary(
        name=name,
        status="passed" if comparison.passed else "failed",
        reference_authority=authority,
        expected_rows=comparison.expected_rows,
        actual_rows=comparison.actual_rows,
        expected_columns=tuple(comparison.expected_columns),
        actual_columns=tuple(comparison.actual_columns),
        missing_columns=tuple(comparison.missing_columns),
        extra_columns=tuple(comparison.extra_columns),
        mismatched_columns=tuple(comparison.mismatched_columns),
        missing_key_count=len(comparison.missing_keys),
        extra_key_count=len(comparison.extra_keys),
        mismatched_cells=comparison.mismatched_cells,
        missingness_mismatches=comparison.missingness_mismatches,
        max_abs_error=comparison.max_abs_error,
        mean_abs_error=comparison.mean_abs_error,
        policy=policy,
    )
