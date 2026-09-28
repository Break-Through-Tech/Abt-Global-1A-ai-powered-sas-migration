"""Deterministic lineage-aware summaries of artifact comparisons."""

import json
from collections.abc import Sequence
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from sasguard.verification.artifact import ArtifactComparison, ReferenceSource
from sasguard.verification.lineage import (
    ArtifactLineage,
    ArtifactNode,
    StrictModel,
    canonicalize_identifier,
)


class CheckpointStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_CHECKED = "not_checked"


class Diagnostic(StrictModel):
    """Counts and names that explain a comparison without exposing data values."""

    artifact: str
    reference_source: ReferenceSource
    expected_rows: int = Field(ge=0)
    actual_rows: int = Field(ge=0)
    expected_column_count: int = Field(ge=0)
    actual_column_count: int = Field(ge=0)
    missing_key_count: int = Field(ge=0)
    extra_key_count: int = Field(ge=0)
    missing_columns: tuple[str, ...] = ()
    extra_columns: tuple[str, ...] = ()
    mismatched_columns: tuple[str, ...] = ()
    mismatched_cells: int = Field(ge=0)
    missingness_mismatches: int = Field(ge=0)
    max_abs_error: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    mean_abs_error: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("artifact")
    @classmethod
    def canonical_artifact(cls, value: str) -> str:
        return canonicalize_identifier(value)


class Checkpoint(StrictModel):
    artifact: str
    parents: tuple[str, ...]
    status: CheckpointStatus
    supplied_reference_input: bool

    @field_validator("artifact")
    @classmethod
    def canonical_artifact(cls, value: str) -> str:
        return canonicalize_identifier(value)

    @field_validator("parents")
    @classmethod
    def canonical_parents(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        canonical = tuple(canonicalize_identifier(value) for value in values)
        if len(set(canonical)) != len(canonical):
            raise ValueError("parent names must be unique after canonicalization")
        return tuple(sorted(canonical))

    @model_validator(mode="after")
    def validate_boundary_status(self) -> Self:
        if self.supplied_reference_input and self.status != CheckpointStatus.NOT_CHECKED:
            raise ValueError("supplied reference inputs must be not_checked")
        return self


class FailureLocalization(StrictModel):
    artifact: str
    unchecked_upstream: tuple[str, ...]
    dependent_artifacts: tuple[str, ...]
    confirmed_within_scope: bool
    diagnostic: Diagnostic

    @field_validator("artifact")
    @classmethod
    def canonical_artifact(cls, value: str) -> str:
        return canonicalize_identifier(value)

    @model_validator(mode="after")
    def validate_confirmation(self) -> Self:
        if self.confirmed_within_scope != (not self.unchecked_upstream):
            raise ValueError("confirmation must match unchecked upstream artifacts")
        if self.diagnostic.artifact != self.artifact:
            raise ValueError("diagnostic artifact must match localization artifact")
        return self


class GoldenTraceResult(StrictModel):
    schema_version: Literal[1] = 1
    scope: str
    checkpoints: tuple[Checkpoint, ...]
    first_divergences: tuple[FailureLocalization, ...]
    not_checked_artifacts: tuple[str, ...]
    scope_complete: bool
    all_checked_passed: bool

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("scope must not be blank")
        return value.strip()

    @field_validator("not_checked_artifacts")
    @classmethod
    def canonical_not_checked(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(canonicalize_identifier(value) for value in values)

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        checkpoint_names = [checkpoint.artifact for checkpoint in self.checkpoints]
        if len(checkpoint_names) != len(set(checkpoint_names)):
            raise ValueError("checkpoint artifacts must be unique")
        checked_statuses = [
            checkpoint.status
            for checkpoint in self.checkpoints
            if checkpoint.status != CheckpointStatus.NOT_CHECKED
        ]
        expected_all_passed = bool(checked_statuses) and all(
            status == CheckpointStatus.PASSED for status in checked_statuses
        )
        if self.all_checked_passed != expected_all_passed:
            raise ValueError("all_checked_passed does not match checkpoint statuses")
        listed = tuple(
            checkpoint.artifact
            for checkpoint in self.checkpoints
            if checkpoint.status == CheckpointStatus.NOT_CHECKED
        )
        if self.not_checked_artifacts != listed:
            raise ValueError("not_checked_artifacts must match not_checked checkpoints")
        expected_complete = all(
            checkpoint.supplied_reference_input or checkpoint.status != CheckpointStatus.NOT_CHECKED
            for checkpoint in self.checkpoints
        )
        if self.scope_complete != expected_complete:
            raise ValueError("scope_complete does not match non-boundary checkpoint statuses")
        divergent_names = [item.artifact for item in self.first_divergences]
        if len(divergent_names) != len(set(divergent_names)):
            raise ValueError("first divergence artifacts must be unique")
        failed_names = {
            checkpoint.artifact
            for checkpoint in self.checkpoints
            if checkpoint.status == CheckpointStatus.FAILED
        }
        if not set(divergent_names) <= failed_names:
            raise ValueError("first divergences must reference failed checkpoints")
        declared = ArtifactLineage(
            nodes=tuple(
                ArtifactNode(name=checkpoint.artifact, parents=checkpoint.parents)
                for checkpoint in self.checkpoints
            )
        )
        effective = ArtifactLineage(
            nodes=tuple(
                ArtifactNode(
                    name=checkpoint.artifact,
                    parents=() if checkpoint.supplied_reference_input else checkpoint.parents,
                )
                for checkpoint in self.checkpoints
            )
        )
        expected_frontier = [
            name
            for name in declared.ordered_names()
            if name in failed_names and not (set(effective.ancestors(name)) & failed_names)
        ]
        if divergent_names != expected_frontier:
            raise ValueError(
                "first divergences must include the complete observed failure frontier"
            )
        by_name = {checkpoint.artifact: checkpoint for checkpoint in self.checkpoints}
        ordered = declared.ordered_names()
        for localization in self.first_divergences:
            ancestors = set(effective.ancestors(localization.artifact))
            unchecked = tuple(
                name
                for name in ordered
                if name in ancestors
                and by_name[name].status == CheckpointStatus.NOT_CHECKED
                and not by_name[name].supplied_reference_input
            )
            if localization.unchecked_upstream != unchecked:
                raise ValueError("unchecked upstream artifacts must match checkpoint evidence")
            descendants = set(effective.descendants(localization.artifact))
            if localization.dependent_artifacts != tuple(
                name for name in ordered if name in descendants
            ):
                raise ValueError("dependent artifacts must match the effective lineage")
        return self

    def to_json(self) -> str:
        """Serialize as stable, sorted, indented JSON with a trailing newline."""
        return (
            json.dumps(self.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=False)
            + "\n"
        )


def trace_artifacts(
    lineage: ArtifactLineage,
    comparisons: Sequence[ArtifactComparison],
    *,
    scope: str,
    supplied_reference_inputs: Sequence[str] = (),
) -> GoldenTraceResult:
    """Summarize comparisons and locate the earliest observed failure frontier."""
    by_name = {node.name: node for node in lineage.nodes}
    comparison_by_name: dict[str, ArtifactComparison] = {}
    for comparison in comparisons:
        name = canonicalize_identifier(comparison.artifact)
        if name not in by_name:
            raise ValueError(f"comparison references unknown artifact: {name}")
        if name in comparison_by_name:
            raise ValueError(f"duplicate comparison artifact: {name}")
        comparison_by_name[name] = comparison

    boundaries: set[str] = set()
    for value in supplied_reference_inputs:
        name = canonicalize_identifier(value)
        if name not in by_name:
            raise ValueError(f"unknown supplied reference input: {name}")
        if name in boundaries:
            raise ValueError(f"duplicate supplied reference input: {name}")
        if name in comparison_by_name:
            raise ValueError(f"reference input cannot also have a comparison: {name}")
        boundaries.add(name)

    ordered = lineage.ordered_names()
    # Supplied reference inputs replace their generated counterparts. Keep the
    # declared parents in checkpoint metadata, but cut those incoming edges
    # when reasoning about observed failures and their dependencies.
    effective_parents = {
        name: (() if name in boundaries else by_name[name].parents) for name in ordered
    }
    effective_children: dict[str, list[str]] = {name: [] for name in ordered}
    for child, parents in effective_parents.items():
        for parent in parents:
            effective_children[parent].append(child)

    def effective_ancestors(name: str) -> tuple[str, ...]:
        found: set[str] = set()
        pending = list(effective_parents[name])
        while pending:
            parent = pending.pop()
            if parent not in found:
                found.add(parent)
                pending.extend(effective_parents[parent])
        return tuple(item for item in ordered if item in found)

    def effective_descendants(name: str) -> tuple[str, ...]:
        found: set[str] = set()
        pending = list(effective_children[name])
        while pending:
            child = pending.pop()
            if child not in found:
                found.add(child)
                pending.extend(effective_children[child])
        return tuple(item for item in ordered if item in found)

    failed = {name for name, result in comparison_by_name.items() if not result.passed}
    first_failures = tuple(
        name for name in ordered if name in failed and not (set(effective_ancestors(name)) & failed)
    )

    checkpoints: list[Checkpoint] = []
    for name in ordered:
        checkpoint_comparison = comparison_by_name.get(name)
        status = (
            CheckpointStatus.NOT_CHECKED
            if name in boundaries or checkpoint_comparison is None
            else CheckpointStatus.PASSED
            if checkpoint_comparison.passed
            else CheckpointStatus.FAILED
        )
        checkpoints.append(
            Checkpoint(
                artifact=name,
                parents=by_name[name].parents,
                status=status,
                supplied_reference_input=name in boundaries,
            )
        )

    localizations: list[FailureLocalization] = []
    for name in first_failures:
        comparison = comparison_by_name[name]
        ancestors = effective_ancestors(name)
        unchecked = tuple(
            ancestor
            for ancestor in ancestors
            if ancestor not in comparison_by_name and ancestor not in boundaries
        )
        diagnostic = Diagnostic(
            artifact=name,
            reference_source=comparison.reference_source,
            expected_rows=comparison.expected_rows,
            actual_rows=comparison.actual_rows,
            expected_column_count=len(comparison.expected_columns),
            actual_column_count=len(comparison.actual_columns),
            missing_key_count=len(comparison.missing_keys),
            extra_key_count=len(comparison.extra_keys),
            missing_columns=tuple(comparison.missing_columns),
            extra_columns=tuple(comparison.extra_columns),
            mismatched_columns=tuple(comparison.mismatched_columns),
            mismatched_cells=comparison.mismatched_cells,
            missingness_mismatches=comparison.missingness_mismatches,
            max_abs_error=comparison.max_abs_error,
            mean_abs_error=comparison.mean_abs_error,
        )
        localizations.append(
            FailureLocalization(
                artifact=name,
                unchecked_upstream=unchecked,
                dependent_artifacts=effective_descendants(name),
                confirmed_within_scope=not unchecked,
                diagnostic=diagnostic,
            )
        )

    not_checked = tuple(
        checkpoint.artifact
        for checkpoint in checkpoints
        if checkpoint.status == CheckpointStatus.NOT_CHECKED
    )
    nonboundary = set(by_name) - boundaries
    complete = nonboundary <= comparison_by_name.keys()
    all_passed = bool(comparison_by_name) and all(
        comparison.passed for comparison in comparison_by_name.values()
    )
    return GoldenTraceResult(
        scope=scope,
        checkpoints=tuple(checkpoints),
        first_divergences=tuple(localizations),
        not_checked_artifacts=not_checked,
        scope_complete=complete,
        all_checked_passed=all_passed,
    )
