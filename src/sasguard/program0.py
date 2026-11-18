"""Python translation of the supplied July 2025 Program 0 data steps."""

from dataclasses import dataclass

import pandas as pd

MORTALITY = (
    "MORT_30_AMI",
    "MORT_30_CABG",
    "MORT_30_COPD",
    "MORT_30_HF",
    "MORT_30_PN",
    "MORT_30_STK",
    "PSI_4_SURG_COMP",
)
SAFETY = (
    "COMP_HIP_KNEE",
    "HAI_1",
    "HAI_2",
    "HAI_3",
    "HAI_4",
    "HAI_5",
    "HAI_6",
    "PSI_90_SAFETY",
)
READMISSION = (
    "EDAC_30_AMI",
    "EDAC_30_HF",
    "EDAC_30_PN",
    "OP_32",
    "READM_30_CABG",
    "READM_30_COPD",
    "READM_30_HIP_KNEE",
    "READM_30_HOSP_WIDE",
    "OP_35_ADM",
    "OP_35_ED",
    "OP_36",
)
PATIENT_EXPERIENCE = (
    "H_COMP_1_STAR_RATING",
    "H_COMP_2_STAR_RATING",
    "H_COMP_3_STAR_RATING",
    "H_COMP_5_STAR_RATING",
    "H_COMP_6_STAR_RATING",
    "H_COMP_7_STAR_RATING",
    "H_GLOB_STAR_RATING",
    "H_INDI_STAR_RATING",
)
PROCESS = (
    "HCP_COVID_19",
    "IMM_3",
    "OP_10",
    "OP_13",
    "OP_18B",
    "OP_22",
    "OP_23",
    "OP_29",
    "OP_8",
    "PC_01",
    "SAFE_USE_OF_OPIOIDS",
    "SEP_1",
)


@dataclass(frozen=True, slots=True)
class Program0Spec:
    """Measure rules from one release of the SAS program."""

    measures: tuple[str, ...]
    reversed_measures: frozenset[str]
    minimum_reporting_count: int = 101

    def __post_init__(self) -> None:
        if not self.measures or len({name.upper() for name in self.measures}) != len(self.measures):
            raise ValueError("measure names must be nonempty and unique ignoring case")
        if any(name != name.upper() for name in self.measures):
            raise ValueError("measure names must use canonical uppercase SAS names")
        if not self.reversed_measures.issubset(self.measures):
            raise ValueError("reversed measures must be in the measure list")
        if self.minimum_reporting_count < 1:
            raise ValueError("minimum reporting count must be positive")


CMS_2025_JUL = Program0Spec(
    measures=MORTALITY + SAFETY + READMISSION + PATIENT_EXPERIENCE + PROCESS,
    reversed_measures=frozenset(
        MORTALITY
        + SAFETY
        + READMISSION
        + ("OP_10", "OP_13", "OP_18B", "OP_22", "OP_8", "PC_01", "SAFE_USE_OF_OPIOIDS")
    ),
)


@dataclass(frozen=True, slots=True)
class Program0Result:
    """Three permanent Program 0 outputs and the active measure list."""

    excluded_measures: pd.DataFrame
    raw_statistics: pd.DataFrame
    analysis: pd.DataFrame
    active_measures: tuple[str, ...]


def translate_program0(
    input_data: pd.DataFrame, *, spec: Program0Spec = CMS_2025_JUL
) -> Program0Result:
    """Run Program 0 semantics using only the hospital input, never gold outputs."""
    if not all(isinstance(name, str) for name in input_data.columns):
        raise ValueError("input column names must be strings")
    original_names = list(input_data.columns)
    canonical_names = [name.upper() for name in original_names]
    if len(set(canonical_names)) != len(canonical_names):
        raise ValueError("input columns collide ignoring case")
    if "PROVIDER_ID" not in canonical_names:
        raise ValueError("input is missing PROVIDER_ID")
    missing_measures = sorted(set(spec.measures) - set(canonical_names))
    if missing_measures:
        raise ValueError(f"input is missing measures: {missing_measures}")
    generated_names = {"TOTAL_M_CNT", *(f"STD_{name}" for name in spec.measures)}
    generated_collisions = sorted(set(canonical_names) & generated_names)
    if generated_collisions:
        raise ValueError(f"input already has generated columns: {generated_collisions}")

    data = input_data.copy(deep=True)
    data.columns = canonical_names
    for name in spec.measures:
        data[name] = pd.to_numeric(data[name], errors="raise")

    reporting_counts = data.loc[:, spec.measures].count()
    excluded_names = tuple(
        name for name in spec.measures if reporting_counts[name] < spec.minimum_reporting_count
    )
    active_names = tuple(name for name in spec.measures if name not in excluded_names)
    if not active_names:
        raise ValueError("no measures remain after the reporting-count filter")
    excluded = pd.DataFrame(
        {
            "freq": [float(reporting_counts[name]) for name in excluded_names],
            "measure_name": list(excluded_names),
        }
    )

    data = data.drop(columns=list(excluded_names))
    total_count = data.loc[:, active_names].count(axis=1)
    data = data.loc[total_count >= 1].copy()
    data["Total_m_cnt"] = total_count.loc[data.index]

    raw = data.loc[:, active_names]
    statistics = pd.DataFrame(
        {
            "_TYPE_": [0.0] * 5,
            "_FREQ_": [float(len(data))] * 5,
            "_STAT_": ["N", "MIN", "MAX", "MEAN", "STD"],
        }
    )
    analysis = data.drop(columns=list(active_names))
    for name in active_names:
        values = raw[name]
        mean = values.mean()
        std = values.std(ddof=1)
        if pd.isna(std) or std == 0:
            raise ValueError(
                f"SAS standardization is not established for {name} with zero variance"
            )
        statistics[name] = [float(values.count()), values.min(), values.max(), mean, std]
        standardized = (values - mean) / std
        if name in spec.reversed_measures:
            standardized = -standardized
        analysis[f"std_{name}"] = standardized

    return Program0Result(excluded, statistics, analysis, active_names)
