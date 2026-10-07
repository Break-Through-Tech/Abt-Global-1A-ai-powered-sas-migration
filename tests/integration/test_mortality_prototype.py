"""Opt-in Docker replay of the supplied human-reference Mortality calculation."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from sasguard.prototypes.mortality import run_mortality_prototype

pytestmark = pytest.mark.docker_integration


def require_docker_tests() -> None:
    """Skip unless the explicit integration-test switch and Docker are available."""
    if os.environ.get("SASGUARD_RUN_DOCKER_TESTS") != "1":
        pytest.skip("set SASGUARD_RUN_DOCKER_TESTS=1 to run Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is unavailable")


@pytest.fixture(autouse=True)
def docker_required() -> None:
    require_docker_tests()


def test_human_reference_replay_compares_mortality_output() -> None:
    project_root = Path(__file__).resolve().parents[2]

    comparison, report_path = run_mortality_prototype(project_root)

    assert comparison.passed
    assert comparison.artifact == "OUTCOME_MORTALITY"
    assert comparison.expected_rows == 4566
    assert comparison.actual_rows == 4566
    assert len(comparison.expected_columns) == 21
    assert len(comparison.actual_columns) == 21
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["implementation"] == "human_reference"
    assert report["scope"] == "Program 1 Mortality only, supplied Program 0 intermediate"
    assert report["input_artifact"] == "STD_DATA_2025JUL_ANALYSIS"
    assert report["reference_artifact"] == "OUTCOME_MORTALITY"
    assert report["comparison"]["passed"] is True
    assert report["comparison"]["expected_rows"] == 4566
    assert len(report["comparison"]["actual_columns"]) == 21
    assert report["trace_report"] == "trace.json"
    trace = json.loads((report_path.parent / "trace.json").read_text(encoding="utf-8"))
    assert trace["all_checked_passed"] is True
    assert trace["scope_complete"] is False
    assert trace["first_divergences"] == []
    assert len(trace["checkpoints"]) == 11
    assert len(trace["not_checked_artifacts"]) == 10
    checkpoints = {item["artifact"]: item for item in trace["checkpoints"]}
    assert checkpoints["OUTCOME_MORTALITY"]["status"] == "passed"
    assert checkpoints["STD_DATA_2025JUL_ANALYSIS"]["status"] == "not_checked"
    assert checkpoints["STD_DATA_2025JUL_ANALYSIS"]["supplied_reference_input"] is True

    run_directory = report_path.parent
    manifest = json.loads((run_directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["reference_sources"] == {"OUTCOME_MORTALITY": "sas7bdat"}
    assert set(manifest["artifact_results"]) == {"OUTCOME_MORTALITY"}
    assert set(manifest["input_hashes"]) == {
        "data/Project_1/SAS Output/std_data_2025jul_analysis.sas7bdat"
    }
    assert manifest["source_hashes"]
    assert "configs/cms-artifact-lineage.json" in manifest["source_hashes"]
    assert all(len(digest) == 64 for digest in manifest["source_hashes"].values())
    assert all(len(digest) == 64 for digest in manifest["input_hashes"].values())
    assert manifest["execution_result"]["status"] == "succeeded"
    assert manifest["execution_result"]["output_files"] == ["OUTCOME_MORTALITY.csv"]
    assert manifest["generated_code_hashes"] == {}
    assert "model" not in manifest
    assert sorted(path.name for path in (run_directory / "source").iterdir()) == ["mortality.py"]
    assert sorted(path.name for path in (run_directory / "input").iterdir()) == [
        "std_data_2025jul_analysis.sas7bdat"
    ]
    output_directory = run_directory / "output"
    assert sorted(path.name for path in output_directory.iterdir() if path.is_file()) == [
        "OUTCOME_MORTALITY.csv"
    ]
    assert sorted(path.name for path in output_directory.iterdir() if path.is_dir()) == [".tmp"]
