"""Tests for the supplied human-reference Mortality calculation."""

from __future__ import annotations

import math
import runpy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sasguard.config import load_project_configuration
from sasguard.data import ArtifactFormat, LoadedArtifact, load_artifact
from sasguard.prototypes.mortality import mortality_policy
from sasguard.verification import compare_artifacts

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REFERENCE_MODULE = runpy.run_path(PROJECT_ROOT / "reference_python" / "mortality.py")
MORTALITY_MEASURES = _REFERENCE_MODULE["MORTALITY_MEASURES"]
calculate_mortality = _REFERENCE_MODULE["calculate_mortality"]


def _cohort() -> pd.DataFrame:
    values = [[score] * len(MORTALITY_MEASURES) for score in (3.0, 5.0, 7.0)]
    values.append([np.nan] * len(MORTALITY_MEASURES))
    return pd.DataFrame(
        {
            "provider_id": ["00001", "00002", "00003", "00004"],
            **{
                name: [row[index] for row in values]
                for index, name in enumerate(MORTALITY_MEASURES)
            },
        }
    )


def _partial_cohort() -> pd.DataFrame:
    frame = _cohort()
    frame.loc[0, list(MORTALITY_MEASURES[2:])] = np.nan
    frame.loc[1, list(MORTALITY_MEASURES[:2])] = np.nan
    frame.loc[1, list(MORTALITY_MEASURES[3:])] = np.nan
    frame.loc[2, list(MORTALITY_MEASURES[:6])] = np.nan
    return frame


def test_calculation_scores_and_retains_all_missing_provider() -> None:
    source = _cohort()
    before = source.copy(deep=True)

    result = calculate_mortality(source)

    assert source.equals(before)
    assert result.columns.tolist() == [
        "PROVIDER_ID",
        *MORTALITY_MEASURES,
        *(f"C{number}" for number in range(1, 8)),
        "TOTAL_CNT",
        "MEASURE_WT",
        "SCORE_BEFORE_STD",
        "MEAN",
        "STDDEV",
        "GRP_SCORE",
    ]
    assert result.shape == (4, 21)
    assert result["PROVIDER_ID"].tolist() == ["00001", "00002", "00003", "00004"]
    assert result["TOTAL_CNT"].tolist() == [7, 7, 7, 0]
    assert result[[f"C{number}" for number in range(1, 8)]].values.tolist() == [
        [1] * 7,
        [1] * 7,
        [1] * 7,
        [0] * 7,
    ]
    assert result["MEASURE_WT"].iloc[:3].tolist() == [1 / 7] * 3
    assert pd.isna(result["MEASURE_WT"].iloc[3])
    assert result["SCORE_BEFORE_STD"].iloc[:3].tolist() == [3.0, 5.0, 7.0]
    assert result["SCORE_BEFORE_STD"].iloc[3] != result["SCORE_BEFORE_STD"].iloc[3]
    assert result["MEAN"].tolist() == [5.0] * 4
    assert result["STDDEV"].tolist() == [2.0] * 4
    assert result["GRP_SCORE"].iloc[:3].tolist() == [-1.0, 0.0, 1.0]
    assert math.isnan(result["GRP_SCORE"].iloc[3])


def test_partial_measure_availability_uses_row_specific_weights() -> None:
    result = calculate_mortality(_partial_cohort())

    assert result["TOTAL_CNT"].tolist() == [2, 1, 1, 0]
    assert result[[f"C{number}" for number in range(1, 8)]].values.tolist() == [
        [1, 1, 0, 0, 0, 0, 0],
        [0, 0, 1, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 1],
        [0, 0, 0, 0, 0, 0, 0],
    ]
    assert result["MEASURE_WT"].iloc[:3].tolist() == [0.5, 1.0, 1.0]
    assert pd.isna(result["MEASURE_WT"].iloc[3])
    assert result["SCORE_BEFORE_STD"].iloc[:3].tolist() == [3.0, 5.0, 7.0]
    assert result["GRP_SCORE"].iloc[:3].tolist() == [-1.0, 0.0, 1.0]


def test_full_human_reference_replay_matches_supplied_binary_artifact() -> None:
    config = load_project_configuration(
        PROJECT_ROOT / "configs" / "cms_2025jul.yaml", project_root=PROJECT_ROOT
    )
    paths = config.resolve_paths(PROJECT_ROOT)
    input_artifact = load_artifact(
        paths.reference_sas7bdat["STD_DATA_2025JUL_ANALYSIS"], key=config.project.key
    )
    generated_frame = calculate_mortality(input_artifact.frame)
    actual = LoadedArtifact(
        frame=generated_frame,
        source_path=Path("human-reference-OUTCOME_MORTALITY.csv"),
        format=ArtifactFormat.CSV,
        key_column="PROVIDER_ID",
    )
    expected = load_artifact(paths.reference_sas7bdat["OUTCOME_MORTALITY"], key=config.project.key)

    comparison = compare_artifacts(
        actual,
        expected,
        artifact="OUTCOME_MORTALITY",
        policy=mortality_policy(PROJECT_ROOT),
    )

    assert comparison.passed
    assert comparison.expected_rows == comparison.actual_rows == 4566
    assert len(comparison.expected_columns) == len(comparison.actual_columns) == 21


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda frame: frame.assign(provider_id=["00001", "00001", "00003", "00004"]),
            "present and unique",
        ),
        (lambda frame: frame.assign(provider_id=["00001", "", "00003", "00004"]), "non-empty text"),
        (
            lambda frame: frame.assign(provider_id=["00001", None, "00003", "00004"]),
            "present and unique",
        ),
        (lambda frame: frame.assign(provider_id=[1, 2, 3, 4]), "non-empty text"),
        (lambda frame: frame.assign(STD_MORT_30_AMI=np.inf), "finite or missing"),
        (lambda frame: frame.drop(columns=["STD_MORT_30_AMI"]), "required Mortality columns"),
    ],
)
def test_invalid_inputs_are_rejected(change, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_mortality(change(_cohort()))


def test_case_insensitive_column_collision_is_rejected() -> None:
    frame = _cohort()
    frame["PROVIDER_ID"] = frame["provider_id"]

    with pytest.raises(ValueError, match="collide ignoring case"):
        calculate_mortality(frame)


def test_constant_score_cohort_is_rejected() -> None:
    frame = _cohort()
    frame.loc[:2, list(MORTALITY_MEASURES)] = 5.0

    with pytest.raises(ValueError, match="at least two varying"):
        calculate_mortality(frame)


def test_entirely_missing_score_cohort_is_rejected() -> None:
    frame = _cohort()
    frame.loc[:, list(MORTALITY_MEASURES)] = np.nan

    with pytest.raises(ValueError, match="at least two varying"):
        calculate_mortality(frame)


@pytest.mark.parametrize("mutation", ["changed_score", "fixed_divisor", "population_std"])
def test_committed_policy_rejects_changed_scoring_rules(mutation: str) -> None:
    expected_frame = calculate_mortality(_partial_cohort())
    actual_frame = expected_frame.copy()
    if mutation == "changed_score":
        actual_frame.loc[0, "GRP_SCORE"] = -0.75
    elif mutation == "fixed_divisor":
        values = _partial_cohort().loc[:, list(MORTALITY_MEASURES)].sum(axis=1) / 7
        actual_frame["SCORE_BEFORE_STD"] = values
        actual_frame["MEAN"] = values.iloc[:3].mean()
        actual_frame["STDDEV"] = values.iloc[:3].std(ddof=1)
        actual_frame["GRP_SCORE"] = (values - values.mean()) / values.std(ddof=1)
    else:
        scores = actual_frame["SCORE_BEFORE_STD"]
        actual_frame["STDDEV"] = scores.std(ddof=0)
        actual_frame["GRP_SCORE"] = (scores - scores.mean()) / scores.std(ddof=0)
    expected = LoadedArtifact(
        frame=expected_frame,
        source_path=Path("trusted.sas7bdat"),
        format=ArtifactFormat.SAS7BDAT,
        key_column="PROVIDER_ID",
    )
    actual = LoadedArtifact(
        frame=actual_frame,
        source_path=Path("reference.csv"),
        format=ArtifactFormat.CSV,
        key_column="PROVIDER_ID",
    )

    comparison = compare_artifacts(
        actual,
        expected,
        artifact="OUTCOME_MORTALITY",
        policy=mortality_policy(PROJECT_ROOT),
    )

    assert not comparison.passed
    assert "GRP_SCORE" in comparison.mismatched_columns
    if mutation == "changed_score":
        assert comparison.mismatched_columns == ["GRP_SCORE"]
        assert comparison.mismatched_cells == 1
