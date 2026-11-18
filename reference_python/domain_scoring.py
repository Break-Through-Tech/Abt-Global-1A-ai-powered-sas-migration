"""Program 1: score each hospital in each of the five CMS domains.
The input must already contain standardized measures from Program 0.

Flow:
1. Take Program 0's output (std_data_2025jul_analysis.sas7bdat)
2. For each of the 5 domains: count -> weight -> average -> standardize
3. These measures are condensed into 5 CSV files:
(OUTCOME_MORTALITY, OUTCOME_SAFETY, OUTCOME_READMISSION, PTEXP, PROCESS)
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat

# Names come from the July 2025 Program 1 analysis.
# Prefix STD_ means these are already standardized by Program 0.
DOMAIN_MEASURES: dict[str, tuple[str, ...]] = {
    "OUTCOME_MORTALITY": (
        "STD_MORT_30_AMI",
        "STD_MORT_30_CABG",
        "STD_MORT_30_COPD",
        "STD_MORT_30_HF",
        "STD_MORT_30_PN",
        "STD_MORT_30_STK",
        "STD_PSI_4_SURG_COMP",
    ),
    "OUTCOME_SAFETY": (
        "STD_COMP_HIP_KNEE",
        "STD_HAI_1",
        "STD_HAI_2",
        "STD_HAI_3",
        "STD_HAI_4",
        "STD_HAI_5",
        "STD_HAI_6",
        "STD_PSI_90_SAFETY",
    ),
    "OUTCOME_READMISSION": (
        "STD_EDAC_30_AMI",
        "STD_EDAC_30_HF",
        "STD_EDAC_30_PN",
        "STD_OP_32",
        "STD_READM_30_CABG",
        "STD_READM_30_COPD",
        "STD_READM_30_HIP_KNEE",
        "STD_READM_30_HOSP_WIDE",
        "STD_OP_35_ADM",
        "STD_OP_35_ED",
        "STD_OP_36",
    ),
    "PTEXP": (
        "STD_H_COMP_1_STAR_RATING",
        "STD_H_COMP_2_STAR_RATING",
        "STD_H_COMP_3_STAR_RATING",
        "STD_H_COMP_5_STAR_RATING",
        "STD_H_COMP_6_STAR_RATING",
        "STD_H_COMP_7_STAR_RATING",
        "STD_H_GLOB_STAR_RATING",
        "STD_H_INDI_STAR_RATING",
    ),
    "PROCESS": (
        "STD_HCP_COVID_19",
        "STD_IMM_3",
        "STD_OP_10",
        "STD_OP_13",
        "STD_OP_18B",
        "STD_OP_22",
        "STD_OP_23",
        "STD_OP_29",
        "STD_OP_8",
        "STD_PC_01",
        "STD_SAFE_USE_OF_OPIOIDS",
        "STD_SEP_1",
    ),
}


def calculate_domain(frame: pd.DataFrame, measures: tuple[str, ...]) -> pd.DataFrame:
    """Calculate one domain's scores for every hospital.
    Keeps hospitals that have zero reported measures, with missing scores.
    It does not read the SAS expected results (those are for validation only).
    """
    if not measures or len(set(measures)) != len(measures):
        raise ValueError("measure list must be non-empty and unique")

    # Make column names consistent (PROVIDER_ID and provider_id both work).
    column_names = [str(name).upper() for name in frame.columns]
    if len(set(column_names)) != len(column_names):
        raise ValueError("input columns collide ignoring case")
    data = frame.copy()
    data.columns = column_names

    names = tuple(name.upper() for name in measures)
    required = ["PROVIDER_ID", *names]
    missing_columns = [name for name in required if name not in data.columns]
    if missing_columns:
        raise ValueError(f"required columns are missing: {missing_columns}")

    # Hospital IDs are text, so IDs like 010001 keep the leading zero.
    providers = data["PROVIDER_ID"]
    if providers.isna().any() or providers.duplicated().any():
        raise ValueError("provider IDs must be present and unique")
    if not providers.map(lambda value: isinstance(value, str) and bool(value)).all():
        raise ValueError("provider IDs must be non-empty text")

    values = data.loc[:, list(names)].astype(float)
    if np.isinf(values.to_numpy()).any():
        raise ValueError("measure values cannot be infinity")

    # A flag of 1 means the measure exists for this hospital.
    flags = values.notna().astype(int)
    counts = flags.sum(axis=1)

    # A hospital with 3 available measures gives each measure weight 1/3.
    # Zero available measures means missing weight (not a zero score).
    weights = 1.0 / counts.replace(0, np.nan)
    averages = values.sum(axis=1, min_count=1) * weights

    # Domain standardization uses ALL hospitals with a non-missing average.
    # ddof=1 is the sample standard deviation used in the SAS prototype.
    mean = float(averages.mean())
    stddev = float(averages.std(ddof=1))
    if not np.isfinite(stddev) or stddev <= 0:
        raise ValueError("need at least two different non-missing domain averages")

    # Keep the same detailed columns/order as the Mortality reference.
    result = data.loc[:, required].copy()
    result["PROVIDER_ID"] = providers.astype("string")
    for number, name in enumerate(names, start=1):
        result[f"C{number}"] = flags[name]
    result["TOTAL_CNT"] = counts
    result["MEASURE_WT"] = weights
    result["SCORE_BEFORE_STD"] = averages
    result["MEAN"] = mean
    result["STDDEV"] = stddev
    result["GRP_SCORE"] = (averages - mean) / stddev
    return result


def calculate_all_domains(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Run the same calculation once for each of the five domains."""
    return {
        domain: calculate_domain(frame, measures) for domain, measures in DOMAIN_MEASURES.items()
    }


def main() -> None:
    """Read Program 0's standardized input and write the five domain CSVs."""
    input_directory = Path(os.environ.get("SASGUARD_INPUT_DIR", "."))
    output_directory = Path(os.environ.get("SASGUARD_OUTPUT_DIR", "."))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=input_directory / "std_data_2025jul_analysis.sas7bdat",
    )
    parser.add_argument("--output-dir", type=Path, default=output_directory)
    arguments = parser.parse_args()
    if arguments.input.suffix.casefold() != ".sas7bdat":
        raise ValueError("this reference entry point requires a SAS7BDAT intermediate")

    # Read standardized scores only. Never use the trusted SAS outputs as inputs.
    frame, _ = pyreadstat.read_sas7bdat(arguments.input)
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    for name, table in calculate_all_domains(frame).items():
        output = arguments.output_dir / f"{name}.csv"
        table.to_csv(output, index=False, float_format="%.17g")
        print(f"Saved {output}: {len(table)} rows, {len(table.columns)} columns")


if __name__ == "__main__":
    main()
