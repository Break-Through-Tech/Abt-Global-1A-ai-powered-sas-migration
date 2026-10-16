"""Tests for keyed, policy-driven artifact comparison."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sasguard.data import ArtifactFormat, LoadedArtifact
from sasguard.verification import (
    ArtifactComparisonPolicy,
    ColumnComparisonPolicy,
    ComparisonInputError,
    ComparisonKind,
    NumericTolerance,
    compare_artifacts,
)


def _artifact(
    frame: pd.DataFrame,
    *,
    name: str,
    artifact_format: ArtifactFormat = ArtifactFormat.CSV,
) -> LoadedArtifact:
    key_column = next(column for column in frame.columns if column.casefold() == "provider_id")
    normalized = frame.copy()
    normalized[key_column] = normalized[key_column].astype("string")
    return LoadedArtifact(
        frame=normalized,
        source_path=Path(name),
        format=artifact_format,
        key_column=key_column,
    )


def test_comparison_aligns_by_key_and_accepts_tolerated_numeric_difference() -> None:
    expected = _artifact(
        pd.DataFrame(
            {
                "PROVIDER_ID": ["00001", "00002", "00003"],
                "SUMMARY_SCORE": [1.0, 2.0, pd.NA],
                "CATEGORY": ["A", "B", "C"],
            }
        ).astype({"SUMMARY_SCORE": "Float64"}),
        name="trusted.sas7bdat",
        artifact_format=ArtifactFormat.SAS7BDAT,
    )
    actual = _artifact(
        pd.DataFrame(
            {
                "provider_id": ["00003", "00001", "00002"],
                "summary_score": [pd.NA, 1.0000004, 2.0],
                "category": ["C", "A", "B"],
            }
        ).astype({"summary_score": "Float64"}),
        name="generated.csv",
    )
    policy = ArtifactComparisonPolicy(
        keys=("PROVIDER_ID",),
        default_numeric_tolerance=NumericTolerance(absolute=1e-6),
    )

    result = compare_artifacts(actual, expected, artifact="OUTCOME_MORTALITY", policy=policy)

    assert result.passed
    assert result.reference_source == "sas7bdat"
    assert result.missing_keys == []
    assert result.extra_keys == []
    assert result.mismatched_cells == 0
    assert result.missingness_mismatches == 0
    assert result.max_abs_error == pytest.approx(4e-7)
    assert result.mean_abs_error == pytest.approx(2e-7)
    assert '"passed":true' in result.model_dump_json()


def test_comparison_reports_structural_value_and_missingness_failures() -> None:
    expected = _artifact(
        pd.DataFrame(
            {
                "PROVIDER_ID": ["00001", "00002", "00003"],
                "SCORE": [1.0, 2.0, 3.0],
                "CATEGORY": ["A", "B", "C"],
                "EXPECTED_ONLY": [1, 1, 1],
            }
        ),
        name="trusted.csv",
    )
    actual = _artifact(
        pd.DataFrame(
            {
                "PROVIDER_ID": ["00001", "00002", "00004"],
                "SCORE": [1.5, pd.NA, 4.0],
                "CATEGORY": ["wrong", "B", "D"],
                "ACTUAL_ONLY": [2, 2, 2],
            }
        ).astype({"SCORE": "Float64"}),
        name="generated.csv",
    )

    result = compare_artifacts(
        actual,
        expected,
        artifact="TEST_ARTIFACT",
        policy=ArtifactComparisonPolicy(keys=("PROVIDER_ID",)),
    )

    assert not result.passed
    assert result.missing_keys == ["00003"]
    assert result.extra_keys == ["00004"]
    assert result.missing_columns == ["EXPECTED_ONLY"]
    assert result.extra_columns == ["ACTUAL_ONLY"]
    assert result.mismatched_columns == ["SCORE", "CATEGORY"]
    assert result.mismatched_cells == 3
    assert result.missingness_mismatches == 1
    assert result.max_abs_error == pytest.approx(0.5)
    assert result.mean_abs_error == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("keys", "match"),
    [
        (["00001", "00001"], "duplicate comparison-key rows"),
        (["00001", pd.NA], "rows with missing comparison keys"),
    ],
)
def test_invalid_keys_are_rejected(keys: list[object], match: str) -> None:
    expected = _artifact(
        pd.DataFrame({"PROVIDER_ID": keys, "SCORE": [1.0, 2.0]}),
        name="trusted.csv",
    )
    actual = _artifact(
        pd.DataFrame({"PROVIDER_ID": ["00001", "00002"], "SCORE": [1.0, 2.0]}),
        name="generated.csv",
    )

    with pytest.raises(ComparisonInputError, match=match):
        compare_artifacts(
            actual,
            expected,
            artifact="TEST_ARTIFACT",
            policy=ArtifactComparisonPolicy(keys=("PROVIDER_ID",)),
        )


def test_case_insensitive_duplicate_columns_are_rejected() -> None:
    expected = _artifact(
        pd.DataFrame(
            [["00001", 1.0, 1.0]],
            columns=["PROVIDER_ID", "SCORE", "score"],
        ),
        name="trusted.csv",
    )
    actual = _artifact(
        pd.DataFrame({"PROVIDER_ID": ["00001"], "SCORE": [1.0]}),
        name="generated.csv",
    )

    with pytest.raises(ComparisonInputError, match="ambiguous case-insensitive columns"):
        compare_artifacts(
            actual,
            expected,
            artifact="TEST_ARTIFACT",
            policy=ArtifactComparisonPolicy(keys=("PROVIDER_ID",)),
        )


def test_missing_key_column_is_rejected() -> None:
    expected = _artifact(
        pd.DataFrame({"PROVIDER_ID": ["00001"], "SCORE": [1.0]}),
        name="trusted.csv",
    )
    actual = LoadedArtifact(
        frame=pd.DataFrame({"OTHER_ID": ["00001"], "SCORE": [1.0]}),
        source_path=Path("generated.csv"),
        format=ArtifactFormat.CSV,
        key_column="OTHER_ID",
    )

    with pytest.raises(ComparisonInputError, match="invalid actual comparison key"):
        compare_artifacts(
            actual,
            expected,
            artifact="TEST_ARTIFACT",
            policy=ArtifactComparisonPolicy(keys=("PROVIDER_ID",)),
        )


def test_non_textual_keys_are_rejected_by_comparator_defense() -> None:
    expected = _artifact(
        pd.DataFrame({"PROVIDER_ID": ["00001"], "SCORE": [1.0]}),
        name="trusted.csv",
    )
    actual = LoadedArtifact(
        frame=pd.DataFrame({"PROVIDER_ID": [1], "SCORE": [1.0]}),
        source_path=Path("generated.csv"),
        format=ArtifactFormat.CSV,
        key_column="PROVIDER_ID",
    )

    with pytest.raises(ComparisonInputError, match="comparison keys must be textual"):
        compare_artifacts(
            actual,
            expected,
            artifact="TEST_ARTIFACT",
            policy=ArtifactComparisonPolicy(keys=("PROVIDER_ID",)),
        )


def test_non_textual_column_names_are_rejected() -> None:
    expected = _artifact(
        pd.DataFrame({"PROVIDER_ID": ["00001"], "SCORE": [1.0]}),
        name="trusted.csv",
    )
    actual = LoadedArtifact(
        frame=pd.DataFrame([["00001", 1.0]], columns=["PROVIDER_ID", 7]),
        source_path=Path("generated.csv"),
        format=ArtifactFormat.CSV,
        key_column="PROVIDER_ID",
    )

    with pytest.raises(ComparisonInputError, match="columns must be non-blank strings"):
        compare_artifacts(
            actual,
            expected,
            artifact="TEST_ARTIFACT",
            policy=ArtifactComparisonPolicy(keys=("PROVIDER_ID",)),
        )


def test_explicit_numeric_rule_rejects_non_numeric_values() -> None:
    expected = _artifact(
        pd.DataFrame({"PROVIDER_ID": ["00001"], "SCORE": ["1.0"]}),
        name="trusted.csv",
    )
    actual = _artifact(
        pd.DataFrame({"PROVIDER_ID": ["00001"], "SCORE": ["1.0"]}),
        name="generated.csv",
    )
    policy = ArtifactComparisonPolicy(
        keys=("PROVIDER_ID",),
        columns=(ColumnComparisonPolicy(name="SCORE", kind=ComparisonKind.NUMERIC),),
    )

    with pytest.raises(ComparisonInputError, match="requires numeric values"):
        compare_artifacts(actual, expected, artifact="TEST_ARTIFACT", policy=policy)


def test_boolean_columns_are_exact_even_with_large_numeric_tolerance() -> None:
    expected = _artifact(
        pd.DataFrame({"PROVIDER_ID": ["00001"], "ELIGIBLE": [True]}),
        name="trusted.csv",
    )
    actual = _artifact(
        pd.DataFrame({"PROVIDER_ID": ["00001"], "ELIGIBLE": [False]}),
        name="generated.csv",
    )
    policy = ArtifactComparisonPolicy(
        keys=("PROVIDER_ID",),
        default_numeric_tolerance=NumericTolerance(absolute=1.0),
    )

    result = compare_artifacts(actual, expected, artifact="TEST_ARTIFACT", policy=policy)

    assert not result.passed
    assert result.mismatched_columns == ["ELIGIBLE"]
    assert result.max_abs_error is None


def test_unknown_policy_column_is_rejected() -> None:
    expected = _artifact(
        pd.DataFrame({"PROVIDER_ID": ["00001"], "SCORE": [1.0]}),
        name="trusted.csv",
    )
    actual = _artifact(
        pd.DataFrame({"PROVIDER_ID": ["00001"], "SCORE": [1.0]}),
        name="generated.csv",
    )
    policy = ArtifactComparisonPolicy(
        keys=("PROVIDER_ID",),
        columns=(ColumnComparisonPolicy(name="UNKNOWN", kind=ComparisonKind.EXACT),),
    )

    with pytest.raises(ComparisonInputError, match="unknown columns"):
        compare_artifacts(actual, expected, artifact="TEST_ARTIFACT", policy=policy)


def test_composite_keys_are_reported_deterministically() -> None:
    expected = _artifact(
        pd.DataFrame(
            {
                "PROVIDER_ID": ["00001", "00001"],
                "PERIOD": ["A", "B"],
                "SCORE": [1.0, 2.0],
            }
        ),
        name="trusted.csv",
    )
    actual = _artifact(
        pd.DataFrame(
            {
                "PROVIDER_ID": ["00001", "00001"],
                "PERIOD": ["A", "C"],
                "SCORE": [1.0, 2.0],
            }
        ),
        name="generated.csv",
    )

    result = compare_artifacts(
        actual,
        expected,
        artifact="TEST_ARTIFACT",
        policy=ArtifactComparisonPolicy(keys=("PROVIDER_ID", "PERIOD")),
    )

    assert result.missing_keys == ['{"PROVIDER_ID":"00001","PERIOD":"B"}']
    assert result.extra_keys == ['{"PROVIDER_ID":"00001","PERIOD":"C"}']
