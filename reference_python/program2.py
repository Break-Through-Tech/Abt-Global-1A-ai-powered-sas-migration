"""Program 2: weighted summary score, reporting eligibility, K-means stars, national averages.

Reference Python implementation of the July 2025 SAS Program 2 and its macros
(%report, %kmeans, %nation_avg0, %nation_avg_peer, %nation_avg).

Review status: this implementation was not written by a team member. It is pending
teammate review and must not be labeled as a human reference until that review is recorded.

Inputs: the five Program 1 domain CSVs and Program 0's std_data_2025jul_analysis.csv.
Trusted SAS outputs are never read here. Clustering reuses the repository FASTCLUS helpers
in sasguard.semantics, which raise UnresolvedSASBehavior instead of guessing when the SAS
documentation does not determine a result (exact ties, empty clusters, MAXITER).
"""

from __future__ import annotations

import argparse
import os
import runpy
from pathlib import Path

import numpy as np
import pandas as pd

from sasguard.semantics.fastclus_iteration import program2_two_pass

PROVIDER = "PROVIDER_ID"

# Program 1 file stem -> Program 2 score column, in the SAS merge order.
DOMAIN_SCORE_COLUMNS: dict[str, str] = {
    "OUTCOME_MORTALITY": "Std_Outcomes_Mortality_score",
    "OUTCOME_READMISSION": "Std_Outcomes_Readmission_score",
    "OUTCOME_SAFETY": "Std_Outcomes_Safety_score",
    "PTEXP": "Std_PatientExp_score",
    "PROCESS": "Std_Process_score",
}

# SAS array order for weights: patient experience, readmission, mortality, safety, process.
WEIGHT_ORDER: tuple[tuple[str, str, str, float], ...] = (
    ("Std_PatientExp_score", "std_weight_PatientExperience", "weight_PatientExperience", 0.22),
    (
        "Std_Outcomes_Readmission_score",
        "std_weight_Readmission",
        "weight_Outcomes_Readmission",
        0.22,
    ),
    ("Std_Outcomes_Mortality_score", "std_weight_Mortality", "weight_Outcomes_Mortality", 0.22),
    ("Std_Outcomes_Safety_score", "std_weight_safety", "weight_Outcomes_Safety", 0.22),
    ("Std_Process_score", "std_weight_Process", "weight_Process", 0.12),
)

# %report count column -> Program 1 domain whose Program 0 measure list it counts.
COUNT_DOMAINS: dict[str, str] = {
    "Outcomes_Mortality_cnt": "OUTCOME_MORTALITY",
    "Outcomes_safety_cnt": "OUTCOME_SAFETY",
    "Outcomes_Readmission_cnt": "OUTCOME_READMISSION",
    "Patient_Experience_cnt": "PTEXP",
    "Process_cnt": "PROCESS",
}

# SAS CNT_GRP text without the fixed-width trailing padding.
PEER_LABELS = {3: "1) # of groups=3", 4: "2) # of groups=4", 5: "3) # of groups=5"}

NATIONAL_DOMAIN_COLUMNS: dict[str, str] = {
    "OUTCOME_MORTALITY": "Out_Mrt_Grp_Score_Nat",
    "OUTCOME_SAFETY": "Out_Sft_Grp_Score_Nat",
    "OUTCOME_READMISSION": "Out_Readm_grp_Score_Nat",
    "PTEXP": "Pt_Exp_Grp_Score_Nat",
    "PROCESS": "Prc_of_Care_Grp_Score_Nat",
}


def _measure_lists() -> dict[str, tuple[str, ...]]:
    """The Program 1 measure lists, which are the macro lists the %report macro counts."""
    path = Path(__file__).with_name("domain_scoring.py")
    return dict(runpy.run_path(str(path))["DOMAIN_MEASURES"])


def _upper(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data.columns = [str(name).upper() for name in data.columns]
    if data.columns.duplicated().any():
        raise ValueError("input columns collide ignoring case")
    if PROVIDER not in data.columns:
        raise ValueError("PROVIDER_ID column is required")
    providers = data[PROVIDER]
    if providers.isna().any() or providers.duplicated().any():
        raise ValueError("provider IDs must be present and unique")
    data[PROVIDER] = providers.astype(str)
    return data


def merge_group_scores(domains: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Full outer merge of the five GRP_SCORE columns by PROVIDER_ID (SAS data step MERGE)."""
    merged: pd.DataFrame | None = None
    for name, column in DOMAIN_SCORE_COLUMNS.items():
        data = _upper(domains[name])
        if "GRP_SCORE" not in data.columns:
            raise ValueError(f"{name} needs a GRP_SCORE column")
        part = data.loc[:, [PROVIDER, "GRP_SCORE"]].rename(columns={"GRP_SCORE": column})
        part[column] = part[column].astype(float)
        merged = part if merged is None else merged.merge(part, on=PROVIDER, how="outer")
    assert merged is not None
    return merged.sort_values(PROVIDER, kind="stable").reset_index(drop=True)


def add_summary_score(scores: pd.DataFrame) -> pd.DataFrame:
    """Standard CMS weights, redistributed over the groups present, then the weighted sum.

    Operation order follows the SAS data step: the denominator is
    1 - I1*W1 - I2*W2 - ... evaluated left to right, a missing group has a missing weight,
    and SAS sum() adds the per-group terms in array order (a missing group adds 0).
    """
    result = scores.copy()
    for _, std_name, _, weight in WEIGHT_ORDER:
        result[std_name] = weight
    missing = {score: result[score].isna().to_numpy() for score, *_ in WEIGHT_ORDER}
    denominator = np.ones(len(result))
    for score, _, _, weight in WEIGHT_ORDER:
        denominator = denominator - missing[score].astype(float) * weight
    total = np.zeros(len(result))
    for score, _, weight_name, weight in WEIGHT_ORDER:
        with np.errstate(divide="ignore", invalid="ignore"):
            weight_values = np.where(missing[score], np.nan, weight / denominator)
        result[weight_name] = weight_values
        term = np.where(missing[score], 0.0, weight_values * result[score].to_numpy())
        total = total + term
    result["summary_score"] = total
    return result


def report_counts(analysis: pd.DataFrame) -> pd.DataFrame:
    """%report: measures per group, groups with at least 3, and the reporting indicator."""
    data = _upper(analysis)
    lists = _measure_lists()
    out = pd.DataFrame({PROVIDER: data[PROVIDER]})
    for column, domain in COUNT_DOMAINS.items():
        names = [name.upper() for name in lists[domain]]
        absent = [name for name in names if name not in data.columns]
        if absent:
            raise ValueError(f"analysis file is missing measures: {absent}")
        out[column] = data.loc[:, names].notna().sum(axis=1).astype(int)
    group_counts = out.loc[:, list(COUNT_DOMAINS)]
    out["Total_measure_group_cnt"] = (group_counts >= 3).sum(axis=1).astype(int)
    out["MortSafe_Group_cnt"] = (
        (out["Outcomes_Mortality_cnt"] >= 3).astype(int)
        + (out["Outcomes_safety_cnt"] >= 3).astype(int)
    ).astype(int)
    out["report_indicator"] = (
        (out["MortSafe_Group_cnt"] >= 1) & (out["Total_measure_group_cnt"] >= 3)
    ).astype(int)
    return out.sort_values(PROVIDER, kind="stable").reset_index(drop=True)


def assign_stars(frame: pd.DataFrame) -> pd.DataFrame:
    """CNT_GRP and STAR: K-means per peer group over reporting hospitals only."""
    result = frame.copy()
    result["cnt_grp"] = pd.Series([None] * len(result), dtype=object)
    result["star"] = np.nan
    reporting = result["report_indicator"] == 1
    for groups, label in PEER_LABELS.items():
        selected = reporting & (result["Total_measure_group_cnt"] == groups)
        result.loc[selected, "cnt_grp"] = label
        if not selected.any():
            continue
        values = [float(value) for value in result.loc[selected, "summary_score"]]
        clustering = program2_two_pass(values)
        result.loc[selected, "star"] = [float(star) for star in clustering.stars]
    return result


def national_averages(frame: pd.DataFrame, domains: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row: means over reporting hospitals, per peer group, and per domain (>=3 measures)."""
    reporting = frame.loc[frame["report_indicator"] == 1]
    row: dict[str, float] = {"Summary_Score_Nat": float(reporting["summary_score"].mean())}
    peers = reporting.groupby("Total_measure_group_cnt")["summary_score"].mean()
    for groups in sorted(peers.index):
        row[f"Summary_Score_Nat_peer{int(groups)}"] = float(peers[groups])
    for domain, column in NATIONAL_DOMAIN_COLUMNS.items():
        data = _upper(domains[domain])
        row[column] = float(data.loc[data["TOTAL_CNT"] >= 3, "GRP_SCORE"].mean())
    return pd.DataFrame([row])


def calculate_program2(
    domains: dict[str, pd.DataFrame], analysis: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    """Both Program 2 outputs from Program 1 domain tables and the Program 0 analysis table."""
    scores = add_summary_score(merge_group_scores(domains))
    counts = report_counts(analysis)
    merged = scores.merge(counts, on=PROVIDER, how="outer").sort_values(PROVIDER, kind="stable")
    star = assign_stars(merged.reset_index(drop=True))
    columns = [
        PROVIDER,
        *DOMAIN_SCORE_COLUMNS.values(),
        *(std for _, std, _, _ in WEIGHT_ORDER),
        *(weight for _, _, weight, _ in WEIGHT_ORDER),
        "summary_score",
        *COUNT_DOMAINS,
        "Total_measure_group_cnt",
        "MortSafe_Group_cnt",
        "report_indicator",
        "cnt_grp",
        "star",
    ]
    star = star.loc[:, columns]
    star.columns = [name.upper() for name in star.columns]
    average = national_averages(merged, domains)
    average.columns = [name.upper() for name in average.columns]
    return {"STAR_2025JUL": star, "NATIONAL_AVERAGE_2025JUL": average}


def _find(directory: Path, filename: str) -> Path:
    """A file in the directory, matched ignoring case like the other pipeline stages."""
    for path in sorted(directory.iterdir()):
        if path.name.casefold() == filename and path.is_file():
            return path
    raise FileNotFoundError(f"{filename} not found in {directory}")


def read_inputs(
    program1_directory: Path, program0_directory: Path
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Read the Program 1 CSVs and the Program 0 analysis CSV with text IDs and exact floats."""
    domains = {
        name: pd.read_csv(
            _find(program1_directory, f"{name.lower()}.csv"),
            converters={PROVIDER: str},
            float_precision="round_trip",
        )
        for name in DOMAIN_SCORE_COLUMNS
    }
    analysis = pd.read_csv(
        _find(program0_directory, "std_data_2025jul_analysis.csv"),
        converters={PROVIDER: str},
        float_precision="round_trip",
    )
    return domains, analysis


def main() -> None:
    """Read Program 0 and Program 1 CSVs and write the two Program 2 CSVs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--program0-dir", type=Path, default=Path(os.environ.get("SASGUARD_PROGRAM0_DIR", "."))
    )
    parser.add_argument(
        "--program1-dir", type=Path, default=Path(os.environ.get("SASGUARD_INPUT_DIR", "."))
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path(os.environ.get("SASGUARD_OUTPUT_DIR", "."))
    )
    arguments = parser.parse_args()
    domains, analysis = read_inputs(arguments.program1_dir, arguments.program0_dir)
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    for name, table in calculate_program2(domains, analysis).items():
        output = arguments.output_dir / f"{name.lower()}.csv"
        table.to_csv(output, index=False, float_format="%.17g")
        print(f"Saved {output}: {len(table)} rows, {len(table.columns)} columns")


if __name__ == "__main__":
    main()
