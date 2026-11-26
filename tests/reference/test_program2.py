"""Program 2 reference: synthetic unit tests plus a run on the actual human Program 0/1 chain.

The reference implementation is pending teammate review; these tests check it against the
SAS source semantics and, on real data, against the supplied SAS artifacts through the
repository validator. The reference itself never reads trusted outputs.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sasguard.prototypes.pipeline_reference import (
    run_human_program0,
    run_human_program1,
    run_human_program2,
)
from sasguard.semantics.fastclus_iteration import UnresolvedSASBehavior
from sasguard.verification.program2 import check_domain_passthrough, validate_program2

ROOT = Path(__file__).resolve().parents[2]
P2 = runpy.run_path(str(ROOT / "reference_python/program2.py"))
P1 = runpy.run_path(str(ROOT / "reference_python/domain_scoring.py"))
MEASURES = P1["DOMAIN_MEASURES"]
SCORE_COLUMNS = list(P2["DOMAIN_SCORE_COLUMNS"].values())
FULL = {
    "OUTCOME_MORTALITY": 7,
    "OUTCOME_SAFETY": 8,
    "OUTCOME_READMISSION": 11,
    "PTEXP": 8,
    "PROCESS": 12,
}
SPREAD = [-4.0, -4.1, -2.0, -2.1, 0.0, 0.1, 2.0, 2.1, 4.0, 4.1]


def domain_tables(values: list[float], total_cnt: list[int] | None = None):
    """Program 1-shaped tables: PROVIDER_ID, TOTAL_CNT, GRP_SCORE for each domain."""
    ids = [f"{i:06d}" for i in range(len(values))]
    return {
        domain: pd.DataFrame(
            {"PROVIDER_ID": ids, "TOTAL_CNT": total_cnt or [3] * len(ids), "GRP_SCORE": values}
        )
        for domain in P2["DOMAIN_SCORE_COLUMNS"]
    }


def score_row(**overrides: float) -> pd.DataFrame:
    row = {column: 1.0 for column in SCORE_COLUMNS}
    row.update(overrides)
    return pd.DataFrame({"PROVIDER_ID": ["a"], **{key: [value] for key, value in row.items()}})


def test_weights_with_all_groups_are_standard() -> None:
    out = P2["add_summary_score"](score_row()).iloc[0]
    assert out["weight_PatientExperience"] == 0.22
    assert out["weight_Process"] == 0.12
    assert out["summary_score"] == pytest.approx(0.22 * 4 + 0.12, abs=1e-15)


def test_missing_group_redistributes_weight_and_missing_gets_missing_weight() -> None:
    scores = score_row(
        Std_Outcomes_Mortality_score=2.0,
        Std_Outcomes_Safety_score=np.nan,
        Std_PatientExp_score=3.0,
        Std_Process_score=-1.0,
    )
    out = P2["add_summary_score"](scores).iloc[0]
    assert np.isnan(out["weight_Outcomes_Safety"])
    assert out["std_weight_safety"] == 0.22  # the standard weight column is always filled
    assert out["weight_Outcomes_Mortality"] == 0.22 / (1 - 0.22)
    assert out["weight_Process"] == 0.12 / (1 - 0.22)
    expected = 0.22 / 0.78 * (3.0 + 1.0 + 2.0) + 0.12 / 0.78 * -1.0
    assert out["summary_score"] == pytest.approx(expected, abs=1e-15)


def test_all_groups_missing_sums_to_zero_like_sas() -> None:
    scores = pd.DataFrame({"PROVIDER_ID": ["a"], **{c: [np.nan] for c in SCORE_COLUMNS}})
    out = P2["add_summary_score"](scores).iloc[0]
    # sum_weight_ave is 0 (not missing) for a missing group, so SAS sum() returns 0.
    assert out["summary_score"] == 0.0


def analysis(rows: list[dict[str, int]]) -> pd.DataFrame:
    """Analysis table where each domain has the requested number of nonmissing measures."""
    frame = pd.DataFrame(
        [
            {
                name: 0.5 if position < counts[domain] else np.nan
                for domain, names in MEASURES.items()
                for position, name in enumerate(names)
            }
            for counts in rows
        ]
    )
    frame.insert(0, "PROVIDER_ID", [f"{i:06d}" for i in range(len(rows))])
    return frame


@pytest.mark.parametrize(
    ("counts", "groups", "mort_safe", "reported"),
    [
        (FULL, 5, 2, 1),
        ({**FULL, "OUTCOME_MORTALITY": 2, "OUTCOME_SAFETY": 0}, 3, 0, 0),
        ({**FULL, "OUTCOME_MORTALITY": 2, "OUTCOME_SAFETY": 3, "PROCESS": 2}, 3, 1, 1),
        (
            {
                "OUTCOME_MORTALITY": 3,
                "OUTCOME_SAFETY": 0,
                "OUTCOME_READMISSION": 3,
                "PTEXP": 0,
                "PROCESS": 0,
            },
            2,
            1,
            0,
        ),
    ],
)
def test_report_counts_and_eligibility(counts, groups, mort_safe, reported) -> None:
    out = P2["report_counts"](analysis([counts])).iloc[0]
    assert out["Outcomes_Mortality_cnt"] == counts["OUTCOME_MORTALITY"]
    assert out["Patient_Experience_cnt"] == counts["PTEXP"]
    assert out["Total_measure_group_cnt"] == groups
    assert out["MortSafe_Group_cnt"] == mort_safe
    assert out["report_indicator"] == reported


def test_cnt_grp_labels_have_no_padding() -> None:
    assert P2["PEER_LABELS"] == {
        3: "1) # of groups=3",
        4: "2) # of groups=4",
        5: "3) # of groups=5",
    }


def program2_frame(summary: list[float], groups: int = 5) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "PROVIDER_ID": [f"{i:06d}" for i in range(len(summary))],
            "summary_score": summary,
            "report_indicator": 1,
            "Total_measure_group_cnt": groups,
        }
    )


def test_clustering_on_a_tiny_peer_group_orders_stars_by_center() -> None:
    out = P2["assign_stars"](program2_frame(SPREAD))
    assert out["star"].tolist() == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert set(out["cnt_grp"]) == {"3) # of groups=5"}


def test_non_reporting_hospitals_have_no_star_or_peer_group() -> None:
    frame = program2_frame([*SPREAD, 9.0])
    frame.loc[10, "report_indicator"] = 0
    out = P2["assign_stars"](frame)
    assert np.isnan(out.loc[10, "star"]) and out.loc[10, "cnt_grp"] is None


def test_exact_tie_raises_instead_of_guessing() -> None:
    # 5.0 is exactly halfway between the seeds 4.0 and 6.0, which SAS documentation leaves open.
    values = [3.0, 3.0, 4.0, 6.0, 6.0, 0.0, 5.0, 3.0, 2.0]
    with pytest.raises(UnresolvedSASBehavior, match="equidistant"):
        P2["assign_stars"](program2_frame(values))


def test_national_averages_use_reporting_hospitals_and_three_measure_domains() -> None:
    domains = domain_tables([1.0, 3.0, 100.0])
    domains["PTEXP"]["TOTAL_CNT"] = [3, 3, 2]  # third hospital is excluded from that mean
    frame = pd.DataFrame(
        {
            "summary_score": [1.0, 5.0, 100.0, 7.0],
            "report_indicator": [1, 1, 0, 1],
            "Total_measure_group_cnt": [3, 3, 5, 4],
        }
    )
    out = P2["national_averages"](frame, domains).iloc[0]
    assert out["Summary_Score_Nat"] == pytest.approx(13.0 / 3)
    assert out["Summary_Score_Nat_peer3"] == 3.0
    assert out["Summary_Score_Nat_peer4"] == 7.0
    assert "Summary_Score_Nat_peer5" not in out.index  # no reporting hospital in that group
    assert out["Pt_Exp_Grp_Score_Nat"] == 2.0
    assert out["Out_Mrt_Grp_Score_Nat"] == pytest.approx(104.0 / 3)


def test_output_columns_are_uppercase_and_ordered_like_sas() -> None:
    n = len(SPREAD)
    result = P2["calculate_program2"](domain_tables(SPREAD, [11] * n), analysis([FULL] * n))
    star = result["STAR_2025JUL"]
    assert star.columns[0] == "PROVIDER_ID" and star.columns[-2:].tolist() == ["CNT_GRP", "STAR"]
    assert all(column == column.upper() for column in star.columns)
    assert star["PROVIDER_ID"].tolist() == [f"{i:06d}" for i in range(n)]
    assert list(result["NATIONAL_AVERAGE_2025JUL"].columns)[:2] == [
        "SUMMARY_SCORE_NAT",
        "SUMMARY_SCORE_NAT_PEER5",
    ]


@pytest.fixture(scope="module")
def chain(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("program2-chain")
    run_human_program0(ROOT, base / "p0")
    run_human_program1(ROOT, base / "p0", base / "p1")
    run_human_program2(ROOT, base / "p0", base / "p1", base / "p2")
    return base


def test_real_chain_matches_sas_with_the_existing_validator(chain: Path) -> None:
    result = validate_program2(ROOT, chain / "p2")
    assert result.status == "passed", {
        name: item.mismatched_columns for name, item in result.comparisons.items()
    }
    assert check_domain_passthrough(chain / "p1", chain / "p2").passed


def test_real_chain_stars_exist_only_for_reporting_hospitals(chain: Path) -> None:
    star = pd.read_csv(chain / "p2/star_2025jul.csv", converters={"PROVIDER_ID": str})
    reporting = star["REPORT_INDICATOR"] == 1
    assert star.loc[reporting, "STAR"].between(1, 5).all()
    assert star.loc[~reporting, "STAR"].isna().all()
