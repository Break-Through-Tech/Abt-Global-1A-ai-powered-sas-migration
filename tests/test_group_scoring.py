"""Test the Mortality group score against the SAS output."""

from pathlib import Path

import numpy as np
import pandas as pd

from sasguard.group_scoring import (
    MORTALITY_MEASURES,
    PROVIDER_ID_COLUMN,
    calculate_group_score,
)

# File paths
DATA_DIR = Path("data/Project_1/SAS Output CSV")
STD_DATA_PATH = DATA_DIR / "STD_DATA_2025JUL_ANALYSIS.csv"
TRUSTED_MORTALITY_PATH = DATA_DIR / "OUTCOME_MORTALITY.csv"


# Load the Program 0 output
std_data = pd.read_csv(
    STD_DATA_PATH,
    dtype={PROVIDER_ID_COLUMN: str},
)

# Load truth SAS Mortality output
trusted_mortality = pd.read_csv(
    TRUSTED_MORTALITY_PATH,
    dtype={PROVIDER_ID_COLUMN: str},
)

# Run our Python version
computed_mortality = calculate_group_score(
    std_data,
    MORTALITY_MEASURES,
)


def test_row_count():
    # Python output should have the same number of hospitals as the SAS output
    assert len(computed_mortality) == len(trusted_mortality)


def test_total_count():
    # Match rows by hospital ID
    merged = computed_mortality.merge(
        trusted_mortality,
        on=PROVIDER_ID_COLUMN,
        suffixes=("_py", "_sas"),
    )

    # total_cnt should match exactly
    assert (merged["total_cnt_py"] == merged["total_cnt_sas"]).all()


def test_group_score():
    # Match rows by hospital ID
    merged = computed_mortality.merge(
        trusted_mortality,
        on=PROVIDER_ID_COLUMN,
        suffixes=("_py", "_sas"),
    )

    # Only compare hospitals that have group scores
    scored = merged.dropna(subset=["grp_score_py", "grp_score_sas"])

    # Group scores should match within a tiny tolerance
    assert np.allclose(
        scored["grp_score_py"],
        scored["grp_score_sas"],
        atol=1e-6,
        rtol=0,
    )


def test_missing_mortality_data():
    # Hospitals with no Mortality measures, according to the trusted SAS data
    expected_zero_count = (trusted_mortality["total_cnt"] == 0).sum()

    # Hospitals our Python code says have no Mortality measures
    zero_count = computed_mortality[computed_mortality["total_cnt"] == 0]

    # Python should find the same number of zero-measure hospitals as SAS
    assert len(zero_count) == expected_zero_count

    # These values should stay missing
    assert zero_count["measure_wt"].isna().all()
    assert zero_count["score_before_std"].isna().all()
    assert zero_count["grp_score"].isna().all()


def test_measure_weight_correct():
    # Grab one hospital that actually reported some measures
    has_measures = computed_mortality[computed_mortality["total_cnt"] > 0]
    example = has_measures.iloc[0]

    # measure_wt should be exactly 1 / total_cnt for that hospital
    expected_weight = 1 / example["total_cnt"]
    assert np.isclose(example["measure_wt"], expected_weight)
