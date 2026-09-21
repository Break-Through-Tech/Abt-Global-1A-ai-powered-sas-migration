"""Tests for deterministic artifact-comparison policies."""

import math

import pytest
from pydantic import ValidationError

from sasguard.verification.policy import (
    ArtifactComparisonPolicy,
    ColumnComparisonPolicy,
    ComparisonKind,
    NumericTolerance,
    StructuralMismatchAction,
    StructuralPolicy,
    resolve_column_name,
)


def test_policy_has_strict_safe_defaults_and_stable_json() -> None:
    policy = ArtifactComparisonPolicy(
        keys=("PROVIDER_ID",),
        default_numeric_tolerance=NumericTolerance(absolute=1e-10, relative=1e-8),
        columns=(
            ColumnComparisonPolicy(name="DOMAIN", kind=ComparisonKind.EXACT),
            ColumnComparisonPolicy(
                name="SUMMARY_SCORE",
                kind=ComparisonKind.NUMERIC,
                tolerance=NumericTolerance(absolute=1e-9, relative=1e-7),
            ),
        ),
    )

    assert policy.row_alignment == "keyed"
    assert policy.column_name_matching == "case_insensitive"
    assert policy.missing_values == "strict"
    assert policy.structural == StructuralPolicy()
    assert policy.to_json() == policy.to_json()
    assert '"schema_version": 1' in policy.to_json()
    assert '"PROVIDER_ID"' in policy.to_json()


def test_column_rules_serialize_in_canonical_order() -> None:
    first = ArtifactComparisonPolicy(
        keys=("PROVIDER_ID",),
        columns=(
            ColumnComparisonPolicy(name="z_score", kind=ComparisonKind.NUMERIC),
            ColumnComparisonPolicy(name="Category", kind=ComparisonKind.EXACT),
        ),
    )
    second = ArtifactComparisonPolicy(
        keys=("PROVIDER_ID",),
        columns=tuple(reversed(first.columns)),
    )

    assert [rule.name for rule in first.columns] == ["Category", "z_score"]
    assert first.to_json() == second.to_json()


@pytest.mark.parametrize("value", [-1.0, math.inf, -math.inf, math.nan])
@pytest.mark.parametrize("field", ["absolute", "relative"])
def test_invalid_numeric_tolerances_are_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        NumericTolerance.model_validate({field: value})


@pytest.mark.parametrize(
    "keys",
    [(), ("",), ("PROVIDER_ID", "provider_id")],
)
def test_invalid_keys_are_rejected(keys: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        ArtifactComparisonPolicy(keys=keys)


def test_duplicate_column_rules_are_rejected_ignoring_case() -> None:
    with pytest.raises(ValidationError, match="column rules must be unique ignoring case"):
        ArtifactComparisonPolicy(
            keys=("PROVIDER_ID",),
            columns=(
                ColumnComparisonPolicy(name="score", kind=ComparisonKind.EXACT),
                ColumnComparisonPolicy(name="SCORE", kind=ComparisonKind.NUMERIC),
            ),
        )


def test_key_rules_are_rejected_ignoring_case() -> None:
    with pytest.raises(ValidationError, match="comparison keys are always exact"):
        ArtifactComparisonPolicy(
            keys=("PROVIDER_ID",),
            columns=(ColumnComparisonPolicy(name="provider_id", kind=ComparisonKind.EXACT),),
        )


def test_exact_rule_cannot_define_numeric_tolerance() -> None:
    with pytest.raises(ValidationError, match="exact column rules cannot define"):
        ColumnComparisonPolicy(
            name="DOMAIN",
            kind=ComparisonKind.EXACT,
            tolerance=NumericTolerance(absolute=0.1),
        )


def test_policy_rejects_undocumented_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ArtifactComparisonPolicy.model_validate(
            {"keys": ["PROVIDER_ID"], "silently_ignore_mismatches": True}
        )


def test_structural_mismatches_can_be_reported_without_being_failures() -> None:
    policy = ArtifactComparisonPolicy(
        keys=("PROVIDER_ID",),
        structural=StructuralPolicy(extra_columns=StructuralMismatchAction.REPORT),
    )

    assert policy.structural.extra_columns is StructuralMismatchAction.REPORT
    assert policy.structural.missing_columns is StructuralMismatchAction.FAIL


def test_column_resolution_is_case_insensitive_and_preserves_source_name() -> None:
    available = ["provider_id", "Summary_Score"]

    assert resolve_column_name("PROVIDER_ID", available) == "provider_id"
    assert resolve_column_name("summary_score", available) == "Summary_Score"


def test_column_resolution_reports_missing_and_ambiguous_names() -> None:
    with pytest.raises(KeyError, match="comparison column not found"):
        resolve_column_name("STAR", ["PROVIDER_ID"])

    with pytest.raises(ValueError, match="ambiguous case-insensitive column"):
        resolve_column_name("score", ["score", "SCORE"])
