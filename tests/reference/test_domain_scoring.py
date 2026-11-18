"""Tests for the Program 1 reference: synthetic scoring rules and real-data SAS comparison."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sasguard.config import load_project_configuration
from sasguard.data import ArtifactFormat, LoadedArtifact, load_artifact
from sasguard.verification import ArtifactComparisonPolicy, compare_artifacts

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REFERENCE = runpy.run_path(str(PROJECT_ROOT / "reference_python" / "domain_scoring.py"))
DOMAIN_MEASURES = _REFERENCE["DOMAIN_MEASURES"]
calculate_domain = _REFERENCE["calculate_domain"]
calculate_all_domains = _REFERENCE["calculate_all_domains"]

POLICY_PATH = PROJECT_ROOT / "configs" / "program1-comparison-policies.json"


def load_program1_policies() -> dict[str, ArtifactComparisonPolicy]:
    """Load the committed per-domain comparison policies (same format as Program 0)."""
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    return {
        name: ArtifactComparisonPolicy.model_validate(policy)
        for name, policy in payload["artifacts"].items()
    }


def example_hospitals() -> pd.DataFrame:
    """Three hospitals with values and one hospital with nothing reported."""
    return pd.DataFrame(
        {
            "provider_id": ["00001", "00002", "00003", "00004"],
            "STD_A": [3.0, 5.0, 7.0, np.nan],
            "STD_B": [3.0, np.nan, 7.0, np.nan],
        }
    )


def test_counts_weights_missing_and_scores() -> None:
    result = calculate_domain(example_hospitals(), ("STD_A", "STD_B"))

    assert len(result) == 4  # Keep even the hospital with no measures.
    assert result["TOTAL_CNT"].tolist() == [2, 1, 2, 0]
    assert result["MEASURE_WT"].iloc[:3].tolist() == [0.5, 1.0, 0.5]
    assert pd.isna(result["MEASURE_WT"].iloc[3])
    assert result["SCORE_BEFORE_STD"].iloc[:3].tolist() == [3.0, 5.0, 7.0]
    assert pd.isna(result["GRP_SCORE"].iloc[3])
    assert result["GRP_SCORE"].iloc[:3].tolist() == [-1.0, 0.0, 1.0]


def test_sample_standard_deviation() -> None:
    result = calculate_domain(example_hospitals(), ("STD_A", "STD_B"))
    assert result["MEAN"].iloc[0] == 5.0
    assert result["STDDEV"].iloc[0] == 2.0  # sample std, not population std


def test_does_not_change_input() -> None:
    original = example_hospitals()
    before = original.copy(deep=True)
    calculate_domain(original, ("STD_A", "STD_B"))
    pd.testing.assert_frame_equal(original, before)


def test_rejects_missing_column() -> None:
    with pytest.raises(ValueError, match="required columns"):
        calculate_domain(example_hospitals(), ("STD_DOES_NOT_EXIST",))


def test_rejects_duplicate_hospitals() -> None:
    hospitals = example_hospitals()
    hospitals.loc[1, "provider_id"] = "00001"
    with pytest.raises(ValueError, match="present and unique"):
        calculate_domain(hospitals, ("STD_A", "STD_B"))


def test_each_domain_has_a_measure_list() -> None:
    assert set(DOMAIN_MEASURES) == {
        "OUTCOME_MORTALITY",
        "OUTCOME_SAFETY",
        "OUTCOME_READMISSION",
        "PTEXP",
        "PROCESS",
    }
    assert [len(measures) for measures in DOMAIN_MEASURES.values()] == [7, 8, 11, 8, 12]


def test_all_five_domains_run() -> None:
    # Give every measure the same easy-to-check toy data.
    hospitals = pd.DataFrame({"PROVIDER_ID": ["A", "B", "C"]})
    for measures in DOMAIN_MEASURES.values():
        for name in measures:
            hospitals[name] = [1.0, 2.0, 3.0]
    outputs = calculate_all_domains(hospitals)
    assert len(outputs) == 5
    for output in outputs.values():
        assert output["GRP_SCORE"].tolist() == [-1.0, 0.0, 1.0]


def test_policies_cover_every_domain_column() -> None:
    """Each domain policy names every output column except the PROVIDER_ID key."""
    policies = load_program1_policies()
    assert set(policies) == set(DOMAIN_MEASURES)
    hospitals = pd.DataFrame({"PROVIDER_ID": ["A", "B", "C"]})
    for measures in DOMAIN_MEASURES.values():
        for name in measures:
            hospitals[name] = [1.0, 2.0, 3.0]
    for domain, output in calculate_all_domains(hospitals).items():
        policy_columns = [rule.name for rule in policies[domain].columns]
        assert sorted(policy_columns) == sorted(output.columns.drop("PROVIDER_ID"))
        exact = {rule.name for rule in policies[domain].columns if rule.kind == "exact"}
        flags = {f"C{number}" for number in range(1, len(DOMAIN_MEASURES[domain]) + 1)}
        assert exact == flags | {"TOTAL_CNT"}


# real-data checks: compare each Python output with its trusted SAS output.


@pytest.fixture(scope="module")
def real_data():
    """Run all five domains once on the real Program 0 input, then share the results."""
    config = load_project_configuration(
        PROJECT_ROOT / "configs" / "cms_2025jul.yaml", project_root=PROJECT_ROOT
    )
    paths = config.resolve_paths(PROJECT_ROOT)
    key = config.project.key
    program0 = load_artifact(paths.reference_sas7bdat["STD_DATA_2025JUL_ANALYSIS"], key=key)
    return paths, key, calculate_all_domains(program0.frame)


@pytest.mark.parametrize("domain", list(DOMAIN_MEASURES))
def test_domain_matches_trusted_sas_output(domain: str, real_data) -> None:
    paths, key, outputs = real_data
    actual = LoadedArtifact(
        frame=outputs[domain],
        source_path=Path(f"human-reference-{domain}.csv"),
        format=ArtifactFormat.CSV,
        key_column="PROVIDER_ID",
    )
    expected = load_artifact(paths.reference_sas7bdat[domain], key=key)
    policy = load_program1_policies()[domain]

    comparison = compare_artifacts(actual, expected, artifact=domain, policy=policy)

    # Same hospitals, same columns, same missing values, numbers within 1e-12.
    assert comparison.passed, comparison.mismatched_columns
    assert comparison.expected_rows == comparison.actual_rows == 4566
    measure_count = len(DOMAIN_MEASURES[domain])
    # PROVIDER_ID + measures + one C flag per measure + 6 score columns
    assert len(comparison.actual_columns) == 1 + 2 * measure_count + 6


def test_comparison_catches_a_wrong_score(real_data) -> None:
    """Make sure the real-data check would actually fail on a bad value."""
    paths, key, outputs = real_data
    wrong = outputs["PTEXP"].copy()
    wrong.loc[wrong["GRP_SCORE"].notna().idxmax(), "GRP_SCORE"] += 0.01
    actual = LoadedArtifact(
        frame=wrong,
        source_path=Path("wrong-PTEXP.csv"),
        format=ArtifactFormat.CSV,
        key_column="PROVIDER_ID",
    )
    expected = load_artifact(paths.reference_sas7bdat["PTEXP"], key=key)
    policy = load_program1_policies()["PTEXP"]

    comparison = compare_artifacts(actual, expected, artifact="PTEXP", policy=policy)

    assert not comparison.passed
    assert comparison.mismatched_columns == ["GRP_SCORE"]
