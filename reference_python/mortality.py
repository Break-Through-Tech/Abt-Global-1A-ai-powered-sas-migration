"""Human-reference reproduction of the July 2025 Mortality grp_score macro.

This program consumes only the supplied Program 0 standardized intermediate.
It neither loads nor derives constants from the trusted Mortality output.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat

MORTALITY_MEASURES = (
    "STD_MORT_30_AMI",
    "STD_MORT_30_CABG",
    "STD_MORT_30_COPD",
    "STD_MORT_30_HF",
    "STD_MORT_30_PN",
    "STD_MORT_30_STK",
    "STD_PSI_4_SURG_COMP",
)


def calculate_mortality(frame: pd.DataFrame) -> pd.DataFrame:
    """Reproduce availability flags, equal weighting, and sample standardization.

    All hospitals remain in the artifact. All-missing measure rows have zero
    flags/count and missing weight and scores. Degenerate cohorts are rejected
    explicitly because their SAS standardization behavior is outside this prototype.
    """
    names = [str(name).upper() for name in frame.columns]
    if len(set(names)) != len(names):
        raise ValueError("input columns collide ignoring case")
    data = frame.copy(deep=False)
    data.columns = names
    required = ["PROVIDER_ID", *MORTALITY_MEASURES]
    missing = [name for name in required if name not in data.columns]
    if missing:
        raise ValueError("required Mortality columns are missing: " + ", ".join(missing))
    providers = data["PROVIDER_ID"]
    if providers.isna().any() or providers.duplicated().any():
        raise ValueError("provider identifiers must be present and unique")
    if not providers.map(lambda value: isinstance(value, str) and bool(value)).all():
        raise ValueError("provider identifiers must be non-empty text")

    measures = data.loc[:, list(MORTALITY_MEASURES)].astype(float)
    if np.isinf(measures.to_numpy()).any():
        raise ValueError("Mortality measures must be finite or missing")
    flags = measures.notna().astype(int)
    counts = flags.sum(axis=1)
    weights = 1.0 / counts.replace(0, np.nan)
    # Match SAS SUM times the dynamic measure weight, rather than a fixed divisor.
    average = measures.sum(axis=1, min_count=1) * weights
    mean = float(average.mean())
    standard_deviation = float(average.std(ddof=1))
    if not np.isfinite(standard_deviation) or standard_deviation <= 0:
        raise ValueError("Mortality prototype requires at least two varying non-missing scores")

    result = data.loc[:, ["PROVIDER_ID", *MORTALITY_MEASURES]].copy()
    result["PROVIDER_ID"] = providers.astype("string")
    for number, name in enumerate(MORTALITY_MEASURES, start=1):
        result[f"C{number}"] = flags[name]
    result["TOTAL_CNT"] = counts
    result["MEASURE_WT"] = weights
    result["SCORE_BEFORE_STD"] = average
    result["MEAN"] = mean
    result["STDDEV"] = standard_deviation
    result["GRP_SCORE"] = (average - mean) / standard_deviation
    return result


def main() -> None:
    """Read a standardized input and write a Mortality CSV for separate validation."""
    input_directory = Path(os.environ.get("SASGUARD_INPUT_DIR", "."))
    output_directory = Path(os.environ.get("SASGUARD_OUTPUT_DIR", "."))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=input_directory / "std_data_2025jul_analysis.sas7bdat",
    )
    parser.add_argument("--output", type=Path, default=output_directory / "OUTCOME_MORTALITY.csv")
    arguments = parser.parse_args()
    if arguments.input.suffix.casefold() == ".sas7bdat":
        frame, _ = pyreadstat.read_sas7bdat(arguments.input)
    else:
        raise ValueError("this reference entry point requires a SAS7BDAT intermediate")
    result = calculate_mortality(frame)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(arguments.output, index=False, float_format="%.17g")
    print(
        f"Human-reference Mortality artifact written: {len(result)} rows, "
        f"{len(result.columns)} columns"
    )


if __name__ == "__main__":
    main()
