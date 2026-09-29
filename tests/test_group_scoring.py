"""Verify Mortality scores and prove that invalid comparisons fail."""

from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat
import pytest

from sasguard.group_scoring import (
    MORTALITY_MEASURES,
    PROVIDER_ID_COLUMN,
    calculate_group_score,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "Project_1" / "SAS Output"
CALCULATED_COLUMNS = (
    "total_cnt",
    "measure_wt",
    "score_before_std",
    "Mean",
    "StdDev",
    "grp_score",
)
# Binary references avoid rounding in the supplied CSV exports. Match the
# computed-column tolerance used by the bounded Mortality validator in PR #31.
NUMERIC_TOLERANCE = 1e-12


@pytest.fixture(scope="module")
def mortality_artifacts() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate scores using only input data; load gold separately for checks."""
    std_data, _ = pyreadstat.read_sas7bdat(DATA_DIR / "std_data_2025jul_analysis.sas7bdat")
    trusted, _ = pyreadstat.read_sas7bdat(DATA_DIR / "outcome_mortality.sas7bdat")
    computed = calculate_group_score(std_data, MORTALITY_MEASURES)
    return computed, trusted


def assert_matches_reference(computed: pd.DataFrame, trusted: pd.DataFrame) -> None:
    """Check the seven-column prototype, including keys and missingness.

    The SAS artifact also contains passthrough measures and availability flags.
    This helper verifies only the columns produced by calculate_group_score;
    it does not claim full 21-column artifact parity or Docker integration.
    """
    columns = [PROVIDER_ID_COLUMN, *CALCULATED_COLUMNS]
    assert computed.columns.is_unique, "computed column names must be unique"
    assert trusted.columns.is_unique, "reference column names must be unique"
    assert set(computed.columns) == set(columns), "unexpected computed output schema"
    assert set(columns).issubset(trusted.columns), "reference columns are missing"
    for label, frame in (("computed", computed), ("reference", trusted)):
        identifiers = frame[PROVIDER_ID_COLUMN]
        assert identifiers.notna().all(), f"{label} provider identifiers must be present"
        assert identifiers.map(lambda value: isinstance(value, str) and bool(value)).all(), (
            f"{label} provider identifiers must be non-empty text"
        )
        assert identifiers.is_unique, f"{label} provider identifiers must be unique"

    # An inner join can hide missing providers, even when input row counts agree.
    merged = computed.merge(
        trusted[columns],
        on=PROVIDER_ID_COLUMN,
        how="outer",
        validate="one_to_one",
        indicator=True,
        suffixes=("_py", "_sas"),
    )
    assert len(merged) == len(computed) == len(trusted), "provider identifier sets differ"
    assert merged["_merge"].eq("both").all(), "provider identifier sets differ"
    for column in CALCULATED_COLUMNS:
        actual = merged[f"{column}_py"]
        expected = merged[f"{column}_sas"]
        np.testing.assert_array_equal(
            actual.isna(), expected.isna(), err_msg=f"{column}: missingness differs"
        )
        if column == "total_cnt":
            np.testing.assert_array_equal(actual, expected, err_msg=f"{column}: values differ")
        else:
            np.testing.assert_allclose(
                actual,
                expected,
                atol=NUMERIC_TOLERANCE,
                rtol=NUMERIC_TOLERANCE,
                equal_nan=True,
                err_msg=f"{column}: values differ",
            )


def test_matches_binary_reference(
    mortality_artifacts: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    computed, trusted = mortality_artifacts
    assert_matches_reference(computed, trusted)


def test_comparison_ignores_row_order(
    mortality_artifacts: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    computed, trusted = mortality_artifacts
    assert_matches_reference(computed.iloc[::-1], trusted)


def test_missing_mortality_data(
    mortality_artifacts: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    computed, trusted = mortality_artifacts
    actual = computed.loc[computed["total_cnt"] == 0].set_index(PROVIDER_ID_COLUMN).sort_index()
    expected = trusted.loc[trusted["total_cnt"] == 0].set_index(PROVIDER_ID_COLUMN).sort_index()
    np.testing.assert_array_equal(actual.index, expected.index)
    assert actual[["measure_wt", "score_before_std", "grp_score"]].isna().all().all()


def test_dynamic_weights_and_sample_standardization() -> None:
    """Cover leading-zero IDs, unequal availability, and a fully missing row."""
    frame = pd.DataFrame(
        {
            PROVIDER_ID_COLUMN: ["000001", "000002", "000003", "000004"],
            "measure_a": [1.0, 3.0, np.nan, np.nan],
            "measure_b": [3.0, np.nan, 6.0, np.nan],
        }
    )
    computed = calculate_group_score(frame, ["measure_a", "measure_b"])
    np.testing.assert_array_equal(computed[PROVIDER_ID_COLUMN], frame[PROVIDER_ID_COLUMN])
    np.testing.assert_array_equal(computed["total_cnt"], [2, 1, 1, 0])
    np.testing.assert_allclose(computed["measure_wt"], [0.5, 1.0, 1.0, np.nan])
    np.testing.assert_allclose(computed["score_before_std"], [2.0, 3.0, 6.0, np.nan])
    mean = np.mean([2.0, 3.0, 6.0])
    standard_deviation = np.std([2.0, 3.0, 6.0], ddof=1)
    np.testing.assert_allclose(computed["Mean"], mean)
    np.testing.assert_allclose(computed["StdDev"], standard_deviation)
    np.testing.assert_allclose(
        computed["grp_score"], (np.array([2.0, 3.0, 6.0, np.nan]) - mean) / standard_deviation
    )


@pytest.mark.parametrize("column", CALCULATED_COLUMNS)
def test_comparison_rejects_missing_computed_values(
    mortality_artifacts: tuple[pd.DataFrame, pd.DataFrame], column: str
) -> None:
    computed, trusted = mortality_artifacts
    invalid = computed.copy(deep=True)
    invalid[column] = np.nan
    with pytest.raises(AssertionError, match="missingness differs"):
        assert_matches_reference(invalid, trusted)


@pytest.mark.parametrize("column", CALCULATED_COLUMNS)
def test_comparison_rejects_wrong_computed_values(
    mortality_artifacts: tuple[pd.DataFrame, pd.DataFrame], column: str
) -> None:
    computed, trusted = mortality_artifacts
    invalid = computed.copy(deep=True)
    row = invalid[column].first_valid_index()
    invalid.loc[row, column] += 1
    with pytest.raises(AssertionError, match="values differ"):
        assert_matches_reference(invalid, trusted)


def test_comparison_rejects_one_unexpected_missing_score(
    mortality_artifacts: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    computed, trusted = mortality_artifacts
    invalid = computed.copy(deep=True)
    row = invalid["grp_score"].first_valid_index()
    invalid.loc[row, "grp_score"] = np.nan
    with pytest.raises(AssertionError, match="missingness differs"):
        assert_matches_reference(invalid, trusted)


def test_comparison_rejects_unexpected_nonmissing_score(
    mortality_artifacts: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    computed, trusted = mortality_artifacts
    invalid = computed.copy(deep=True)
    row = invalid.index[invalid["grp_score"].isna()][0]
    invalid.loc[row, "grp_score"] = 0.0
    with pytest.raises(AssertionError, match="missingness differs"):
        assert_matches_reference(invalid, trusted)


@pytest.mark.parametrize("side", ["computed", "reference"])
@pytest.mark.parametrize("defect", ["wrong", "missing", "extra", "duplicate", "null", "numeric"])
def test_comparison_rejects_invalid_provider_identifiers(
    mortality_artifacts: tuple[pd.DataFrame, pd.DataFrame], side: str, defect: str
) -> None:
    computed, trusted = (frame.copy(deep=True) for frame in mortality_artifacts)
    invalid = computed if side == "computed" else trusted
    if defect == "wrong":
        invalid[PROVIDER_ID_COLUMN] = "WRONG_" + invalid[PROVIDER_ID_COLUMN]
    elif defect == "missing":
        invalid.drop(index=invalid.index[0], inplace=True)
    elif defect == "extra":
        extra = invalid.iloc[0].copy()
        extra[PROVIDER_ID_COLUMN] = "EXTRA_PROVIDER"
        invalid.loc[len(invalid)] = extra
    elif defect == "duplicate":
        invalid.loc[invalid.index[0], PROVIDER_ID_COLUMN] = invalid.iloc[1][PROVIDER_ID_COLUMN]
    elif defect == "null":
        invalid.loc[invalid.index[0], PROVIDER_ID_COLUMN] = None
    else:
        invalid[PROVIDER_ID_COLUMN] = np.arange(len(invalid))
    with pytest.raises(AssertionError, match="provider identifier"):
        assert_matches_reference(computed, trusted)


def test_comparison_rejects_empty_overlap() -> None:
    computed = pd.DataFrame(columns=[PROVIDER_ID_COLUMN, *CALCULATED_COLUMNS])
    trusted = pd.DataFrame({PROVIDER_ID_COLUMN: ["000001"], **dict.fromkeys(CALCULATED_COLUMNS, 0)})
    with pytest.raises(AssertionError, match="provider identifier"):
        assert_matches_reference(computed, trusted)


def test_comparison_rejects_missing_output_column(
    mortality_artifacts: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    computed, trusted = mortality_artifacts
    with pytest.raises(AssertionError, match="output schema"):
        assert_matches_reference(computed.drop(columns="grp_score"), trusted)
