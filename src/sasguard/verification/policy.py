"""Deterministic policies for comparing generated and reference artifacts."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _clean_name(value: str) -> str:
    """Return a non-blank comparison name without changing its case."""
    name = value.strip()
    if not name:
        raise ValueError("comparison column names must not be blank")
    return name


def _require_casefold_unique(values: tuple[str, ...], label: str) -> None:
    """Reject names that would be ambiguous under SAS-style matching."""
    canonical = [value.casefold() for value in values]
    if len(canonical) != len(set(canonical)):
        raise ValueError(f"{label} must be unique ignoring case")


class StrictPolicyModel(BaseModel):
    """Base model for immutable policies with no undocumented fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ComparisonKind(StrEnum):
    """Supported cell-level comparison strategies."""

    EXACT = "exact"
    NUMERIC = "numeric"


class StructuralMismatchAction(StrEnum):
    """Whether a reported structural mismatch makes comparison fail."""

    FAIL = "fail"
    REPORT = "report"


class MissingValueMode(StrEnum):
    """Supported missing-value equivalence rules."""

    STRICT = "strict"


class NumericTolerance(StrictPolicyModel):
    """Absolute and relative tolerances for numeric comparisons."""

    absolute: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    relative: float = Field(default=0.0, ge=0, allow_inf_nan=False)


class ColumnComparisonPolicy(StrictPolicyModel):
    """An optional comparison override for one non-key column."""

    name: str
    kind: ComparisonKind
    tolerance: NumericTolerance | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _clean_name(value)

    @model_validator(mode="after")
    def validate_tolerance_kind(self) -> Self:
        if self.kind is ComparisonKind.EXACT and self.tolerance is not None:
            raise ValueError("exact column rules cannot define a numeric tolerance")
        return self


class StructuralPolicy(StrictPolicyModel):
    """Pass or fail behavior for structural differences."""

    missing_columns: StructuralMismatchAction = StructuralMismatchAction.FAIL
    extra_columns: StructuralMismatchAction = StructuralMismatchAction.FAIL
    missing_keys: StructuralMismatchAction = StructuralMismatchAction.FAIL
    extra_keys: StructuralMismatchAction = StructuralMismatchAction.FAIL


class ArtifactComparisonPolicy(StrictPolicyModel):
    """Versioned contract consumed by deterministic artifact comparators."""

    schema_version: Literal[1] = 1
    keys: tuple[str, ...] = Field(min_length=1)
    row_alignment: Literal["keyed"] = "keyed"
    column_name_matching: Literal["case_insensitive"] = "case_insensitive"
    missing_values: MissingValueMode = MissingValueMode.STRICT
    structural: StructuralPolicy = Field(default_factory=StructuralPolicy)
    default_numeric_tolerance: NumericTolerance = Field(default_factory=NumericTolerance)
    columns: tuple[ColumnComparisonPolicy, ...] = ()

    @field_validator("keys")
    @classmethod
    def validate_keys(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        keys = tuple(_clean_name(value) for value in values)
        _require_casefold_unique(keys, "comparison keys")
        return keys

    @field_validator("columns")
    @classmethod
    def validate_column_rules(
        cls, values: tuple[ColumnComparisonPolicy, ...]
    ) -> tuple[ColumnComparisonPolicy, ...]:
        _require_casefold_unique(tuple(rule.name for rule in values), "column rules")
        return tuple(sorted(values, key=lambda rule: rule.name.casefold()))

    @model_validator(mode="after")
    def prevent_key_overrides(self) -> Self:
        key_names = {key.casefold() for key in self.keys}
        overridden_keys = [rule.name for rule in self.columns if rule.name.casefold() in key_names]
        if overridden_keys:
            names = ", ".join(overridden_keys)
            raise ValueError(
                f"comparison keys are always exact and cannot have column rules: {names}"
            )
        return self

    def to_json(self) -> str:
        """Serialize the policy in a stable, reviewable representation."""
        payload = self.model_dump(mode="json")
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def resolve_column_name(requested: str, available: tuple[str, ...] | list[str]) -> str:
    """Resolve one requested name case-insensitively and preserve source casing."""
    name = _clean_name(requested)
    matches = [candidate for candidate in available if candidate.casefold() == name.casefold()]
    if not matches:
        raise KeyError(f"comparison column not found: {name}")
    if len(matches) > 1:
        rendered = ", ".join(repr(match) for match in matches)
        raise ValueError(f"ambiguous case-insensitive column {name!r}: {rendered}")
    return matches[0]
