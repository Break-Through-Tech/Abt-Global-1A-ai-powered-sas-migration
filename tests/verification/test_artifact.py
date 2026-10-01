"""Tests for machine-readable artifact comparison results."""

import json

import pytest
from pydantic import ValidationError

from sasguard.verification.artifact import ArtifactComparison, ReferenceSource


def passing_comparison() -> ArtifactComparison:
    """Return a minimal, internally consistent passing result."""
    return ArtifactComparison(
        artifact="STAR_2025JUL",
        passed=True,
        reference_source=ReferenceSource.SAS7BDAT,
        expected_rows=4566,
        actual_rows=4566,
        expected_columns=["PROVIDER_ID", "star"],
        actual_columns=["star", "PROVIDER_ID"],
        exact_cells=9132,
        max_abs_error=0.0,
        mean_abs_error=0.0,
    )


def test_passing_comparison_serializes_to_json() -> None:
    result = passing_comparison()

    payload = json.loads(result.model_dump_json())

    assert payload["artifact"] == "STAR_2025JUL"
    assert payload["reference_source"] == "sas7bdat"
    assert payload["missing_keys"] == []
    assert payload["max_abs_error"] == 0.0


def test_failing_comparison_records_structured_diagnostics() -> None:
    result = ArtifactComparison(
        artifact="OUTCOME_MORTALITY",
        passed=False,
        reference_source="csv",
        expected_rows=4566,
        actual_rows=4565,
        expected_columns=["PROVIDER_ID", "total_cnt", "grp_score"],
        actual_columns=["PROVIDER_ID", "total_cnt", "unexpected"],
        missing_keys=["000001"],
        missing_columns=["grp_score"],
        extra_columns=["unexpected"],
        mismatched_columns=["total_cnt"],
        exact_cells=9000,
        mismatched_cells=3,
        missingness_mismatches=1,
        max_abs_error=0.25,
        mean_abs_error=0.10,
    )

    assert not result.passed
    assert result.missing_keys == ["000001"]
    assert result.reference_source is ReferenceSource.CSV


def test_numeric_errors_may_be_absent_when_not_applicable() -> None:
    result = ArtifactComparison(
        artifact="SCHEMA_ONLY",
        passed=False,
        reference_source="csv",
        expected_rows=1,
        actual_rows=0,
        expected_columns=["PROVIDER_ID"],
        actual_columns=[],
        missing_columns=["PROVIDER_ID"],
    )

    assert result.max_abs_error is None
    assert result.mean_abs_error is None


def test_passing_result_rejects_structural_mismatch() -> None:
    with pytest.raises(ValidationError, match="passing comparison"):
        ArtifactComparison(
            artifact="STAR_2025JUL",
            passed=True,
            reference_source="sas7bdat",
            expected_rows=10,
            actual_rows=9,
            expected_columns=["PROVIDER_ID"],
            actual_columns=["PROVIDER_ID"],
        )


def test_error_pair_and_order_are_validated() -> None:
    base = passing_comparison().model_dump()

    with pytest.raises(ValidationError, match="recorded together"):
        ArtifactComparison.model_validate({**base, "max_abs_error": 0.1, "mean_abs_error": None})

    with pytest.raises(ValidationError, match="cannot exceed"):
        ArtifactComparison.model_validate({**base, "max_abs_error": 0.1, "mean_abs_error": 0.2})
