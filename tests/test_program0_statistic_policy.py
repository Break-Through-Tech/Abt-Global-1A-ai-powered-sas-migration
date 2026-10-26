"""Exact statistic rows and tolerant moments share the existing artifact diagnostics."""

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from sasguard.data import ArtifactFormat, LoadedArtifact
from sasguard.verification.program0 import _compare_statistics, load_program0_policies

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def expected() -> LoadedArtifact:
    return LoadedArtifact(
        frame=pd.DataFrame(
            {
                "_STAT_": ["N", "MIN", "MAX", "MEAN", "STD"],
                "_TYPE_": [0.0] * 5,
                "_FREQ_": [2002.0] * 5,
                "SCORE": [2002.0, 1.0, 3.0, 2.0, 0.5],
            }
        ),
        source_path=Path("expected.sas7bdat"),
        format=ArtifactFormat.SAS7BDAT,
        key_column="_STAT_",
    )


@pytest.mark.parametrize(
    "statistic,delta,passed",
    [
        ("N", 1e-9, False),
        ("MIN", 1e-13, False),
        ("MAX", 1e-13, False),
        ("N", 1.0, False),
        ("MEAN", 1e-13, True),
        ("STD", 1e-13, True),
        ("MEAN", 1e-3, False),
        ("STD", 1e-3, False),
    ],
)
def test_statistic_specific_rules(
    expected: LoadedArtifact, statistic: str, delta: float, passed: bool
) -> None:
    frame = expected.frame.copy()
    frame.loc[frame["_STAT_"].eq(statistic), "SCORE"] += delta
    actual = replace(expected, frame=frame, format=ArtifactFormat.CSV)
    result = _compare_statistics(
        actual, expected, load_program0_policies(ROOT)["MEASURE_AVERAGE_STDDEV_2025JUL"]
    )
    assert result.passed is passed
    assert result.mismatched_cells == (0 if passed else 1)
    assert result.mismatched_columns == ([] if passed else ["SCORE"])
    assert result.expected_rows == result.actual_rows == 5
    assert result.reference_source.value == "sas7bdat"


def test_row_alignment_and_mixed_diagnostics(expected: LoadedArtifact) -> None:
    frame = expected.frame.copy()
    frame.loc[0, "SCORE"] += 1e-9
    frame.loc[3, "SCORE"] += 1.0
    frame.loc[2, "SCORE"] = float("nan")
    frame = frame.iloc[::-1]
    actual = replace(expected, frame=frame, format=ArtifactFormat.CSV)
    result = _compare_statistics(
        actual, expected, load_program0_policies(ROOT)["MEASURE_AVERAGE_STDDEV_2025JUL"]
    )
    assert not result.passed
    assert result.mismatched_cells == 3
    assert result.missingness_mismatches == 1
    assert result.mismatched_columns == ["SCORE"]
    assert result.exact_cells == 12
    assert result.max_abs_error == 1.0


def test_missing_statistic_remains_a_structural_failure(expected: LoadedArtifact) -> None:
    actual = replace(expected, frame=expected.frame.iloc[1:], format=ArtifactFormat.CSV)
    result = _compare_statistics(
        actual, expected, load_program0_policies(ROOT)["MEASURE_AVERAGE_STDDEV_2025JUL"]
    )
    assert not result.passed
    assert result.missing_keys == ["N"]
    assert result.expected_rows == 5 and result.actual_rows == 4
