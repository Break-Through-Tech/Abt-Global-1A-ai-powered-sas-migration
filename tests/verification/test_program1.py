"""Host-side Program 1 validator: SAS controls, wrong values, copied inputs and structure."""

from __future__ import annotations

from pathlib import Path

import pytest

from sasguard.config import load_project_configuration
from sasguard.data import load_artifact
from sasguard.verification.program1 import (
    PROGRAM1_ARTIFACTS,
    load_program1_policies,
    validate_program1_outputs,
)

ROOT = Path(__file__).resolve().parents[2]
PATHS = load_project_configuration(
    ROOT / "configs/cms_2025jul.yaml", project_root=ROOT
).resolve_paths(ROOT)


@pytest.fixture
def sas_control(tmp_path: Path) -> Path:
    """Host-only copy of the SAS domain outputs; it proves acceptance, never feeds a model."""
    for filename, artifact in PROGRAM1_ARTIFACTS.items():
        load_artifact(PATHS.reference_sas7bdat[artifact], key="PROVIDER_ID").frame.to_csv(
            tmp_path / filename, index=False, float_format="%.17g"
        )
    return tmp_path


def test_policies_cover_five_domains_with_fixed_tolerance() -> None:
    policies = load_program1_policies(ROOT)
    assert set(policies) == set(PROGRAM1_ARTIFACTS.values())
    for policy in policies.values():
        assert policy.keys == ("PROVIDER_ID",)
        numeric = [rule for rule in policy.columns if rule.tolerance is not None]
        assert numeric
        assert all(
            rule.tolerance.absolute == rule.tolerance.relative == 1e-12  # type: ignore[union-attr]
            for rule in numeric
        )


def test_sas_control_passes_all_five(sas_control: Path) -> None:
    result = validate_program1_outputs(ROOT, sas_control)
    assert result.status == "passed"
    assert set(result.artifact_results) == set(PROGRAM1_ARTIFACTS)
    assert all(item.actual_rows == 4566 for item in result.artifact_results.values())
    assert len(result.output_hashes) == 5


def test_missing_file_is_reported_without_comparing(sas_control: Path) -> None:
    (sas_control / "ptexp.csv").unlink()
    result = validate_program1_outputs(ROOT, sas_control)
    assert result.status == "missing_outputs"
    assert result.errors == {"ptexp.csv": "file is missing"}


@pytest.mark.parametrize("column", ["TOTAL_CNT", "C1", "GRP_SCORE"])
def test_wrong_values_fail_and_keep_other_comparisons(sas_control: Path, column: str) -> None:
    path = sas_control / "outcome_safety.csv"
    frame = load_artifact(path, key="PROVIDER_ID").frame
    index = frame.index[frame[column].notna()][0]
    frame[column] = frame[column].astype(float)
    frame.loc[index, column] += 1e-9 if column == "GRP_SCORE" else 1
    frame.to_csv(path, index=False, float_format="%.17g")
    result = validate_program1_outputs(ROOT, sas_control)
    assert result.status == "failed"
    assert column in result.artifact_results["outcome_safety.csv"].mismatched_columns
    assert result.artifact_results["process.csv"].passed


def test_missing_values_must_match(sas_control: Path) -> None:
    path = sas_control / "process.csv"
    frame = load_artifact(path, key="PROVIDER_ID").frame
    frame.loc[frame["GRP_SCORE"].notna().idxmax(), "GRP_SCORE"] = float("nan")
    frame.to_csv(path, index=False, float_format="%.17g")
    result = validate_program1_outputs(ROOT, sas_control)
    assert result.status == "failed"
    assert result.artifact_results["process.csv"].missingness_mismatches == 1


def test_dropped_hospital_is_a_key_failure(sas_control: Path) -> None:
    path = sas_control / "outcome_mortality.csv"
    frame = load_artifact(path, key="PROVIDER_ID").frame
    removed = frame.loc[0, "PROVIDER_ID"]
    frame.iloc[1:].to_csv(path, index=False, float_format="%.17g")
    result = validate_program1_outputs(ROOT, sas_control)
    assert result.status == "failed"
    assert result.artifact_results["outcome_mortality.csv"].missing_keys == [removed]


def test_copied_measures_must_equal_program0_output_exactly(
    sas_control: Path, tmp_path: Path
) -> None:
    analysis = load_artifact(
        PATHS.reference_sas7bdat["STD_DATA_2025JUL_ANALYSIS"], key="PROVIDER_ID"
    )
    consumed = tmp_path / "analysis.csv"
    analysis.frame.to_csv(consumed, index=False, float_format="%.17g")
    assert validate_program1_outputs(ROOT, sas_control, consumed).passed
    frame = analysis.frame.copy()
    column = "STD_MORT_30_AMI"
    index = frame.index[frame[column].notna()][0]
    frame.loc[index, column] *= 1 + 1e-14  # far inside the SAS tolerance
    frame.to_csv(consumed, index=False, float_format="%.17g")
    result = validate_program1_outputs(ROOT, sas_control, consumed)
    assert result.status == "handoff_failed"
    assert all(item.passed for item in result.artifact_results.values())
    assert not result.input_passthrough["outcome_mortality.csv"].passed


def test_unreadable_output_is_malformed_and_retains_others(sas_control: Path) -> None:
    (sas_control / "process.csv").write_text("X,Y\n1,2\n", encoding="utf-8")
    result = validate_program1_outputs(ROOT, sas_control)
    assert result.status == "malformed_outputs"
    assert "process.csv" in result.errors
    assert result.artifact_results["outcome_mortality.csv"].passed
