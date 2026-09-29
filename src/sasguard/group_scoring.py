"""Calculate a group score for each hospital."""

import numpy as np
import pandas as pd

# Mortality measure columns from Program 0 (7 measures for Mortality)
MORTALITY_MEASURES = [
    "std_MORT_30_AMI",
    "std_MORT_30_CABG",
    "std_MORT_30_COPD",
    "std_MORT_30_HF",
    "std_MORT_30_PN",
    "std_MORT_30_STK",
    "std_PSI_4_SURG_COMP",
]

# Column used to identify each hospital
PROVIDER_ID_COLUMN = "PROVIDER_ID"


def calculate_group_score(
    measures: pd.DataFrame,
    measure_cols: list[str],
    provider_id_col: str = PROVIDER_ID_COLUMN,
) -> pd.DataFrame:
    """Calculate one domain score for each hospital.

    Arguments:
        measures: Program 0 output, one row per hospital.
        measure_cols: standardized measure columns for this domain.
        provider_id_col: hospital identifier column.

    Returns:
        DataFrame with total_cnt, measure_wt, score_before_std,
        Mean, StdDev, and grp_score per hospital.
    """

    # Start the output with the hospital ID
    result = measures[[provider_id_col]].copy()

    # Check which measure values are present
    non_missing = measures[measure_cols].notna()

    # Count how many measures each hospital reported
    result["total_cnt"] = non_missing.sum(axis=1)

    # Give each reported measure an equal weight
    # For example: 5 reported measures -> each gets 1/5
    result["measure_wt"] = 1 / result["total_cnt"].replace(0, np.nan)

    # Find the average of the available measure scores
    result["score_before_std"] = measures[measure_cols].mean(axis=1, skipna=True)

    # If the hospital reported no measures, keep the score missing
    result.loc[result["total_cnt"] == 0, "score_before_std"] = np.nan

    # Only use hospitals that have a real score
    valid = result["score_before_std"].notna()

    # Find the mean score across hospitals
    mean = result.loc[valid, "score_before_std"].mean()

    # Find the sample standard deviation across hospitals
    std = result.loc[valid, "score_before_std"].std(ddof=1)

    # Save the same mean and standard deviation on every row
    result["Mean"] = mean
    result["StdDev"] = std

    # Start group scores as missing
    result["grp_score"] = np.nan

    # Calculate the z-score for each hospital
    # default: missing with z scores only calculated for valid hospitals
    result.loc[valid, "grp_score"] = (result.loc[valid, "score_before_std"] - mean) / std

    return result
