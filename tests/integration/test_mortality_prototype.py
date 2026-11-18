"""Opt-in Docker replay of the supplied human-reference Mortality calculation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sasguard.cli import app
from sasguard.execution.manifest import RunManifest
from sasguard.execution.result import ExecutionResult, ExecutionStatus
from sasguard.prototypes.mortality import run_mortality_prototype
from sasguard.provenance.hashing import hash_files
from sasguard.verification import ArtifactComparison, ArtifactComparisonPolicy
from sasguard.verification.golden_trace import CheckpointStatus, GoldenTraceResult
from sasguard.verification.integrity import ProtectedArtifactManifest, load_and_verify_integrity

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
    assert manifest["controller_environment"]["python_version"]
    assert manifest["controller_environment"]["packages"]
    assert "sasguard" in manifest["controller_environment"]["packages"]
    runtime_environment = manifest["execution_result"]["runtime_environment"]
    assert runtime_environment["requested_image"] == report["runner_image"]
    assert runtime_environment["image_id"].startswith("sha256:")
    assert runtime_environment["repo_digests"] == sorted(runtime_environment["repo_digests"])
    assert runtime_environment["python"]["python_version"]
    runtime_packages = runtime_environment["python"]["packages"]
    assert {"numpy", "pandas", "pyreadstat"} <= runtime_packages.keys()
    assert report["runner_environment"] == runtime_environment
    execution = json.loads((run_directory / "execution.json").read_text(encoding="utf-8"))
    assert execution["runtime_environment"] == runtime_environment
    inspected = subprocess.run(
        ["docker", "image", "inspect", "--", report["runner_image"]],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(inspected.stdout)[0]["Id"] == runtime_environment["image_id"]
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


def test_wrong_ddof_executes_successfully_but_fails_verification(tmp_path: Path) -> None:
    """Reject a numerical fault through the real CLI, Docker, comparator, and trace."""
    project_root = Path(__file__).resolve().parents[2]
    protected = ProtectedArtifactManifest.load(project_root / "configs/protected-artifacts.json")
    immutable_paths = [
        *(entry.path for entry in protected.files),
        "configs/protected-artifacts.json",
        "configs/cms_2025jul.yaml",
        "configs/mortality-comparison-policy.json",
        "configs/cms-artifact-lineage.json",
        "pyproject.toml",
        "uv.lock",
        "requirements.lock",
        "requirements-runtime.lock",
        "Dockerfile",
        "Dockerfile.runner",
    ]
    reference_path = "reference_python/mortality.py"
    original_hashes = hash_files(project_root, [*immutable_paths, reference_path])
    fixture_root = tmp_path / "mortality-fixture"
    for relative_path in [*immutable_paths, reference_path]:
        destination = fixture_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Independent copies prevent the test fault from changing the real baseline.
        shutil.copyfile(project_root / relative_path, destination)
    assert hash_files(fixture_root, [*immutable_paths, reference_path]) == original_hashes
    fixture_hashes = hash_files(fixture_root, immutable_paths)

    faulty_source = fixture_root / reference_path
    correct_code = faulty_source.read_text(encoding="utf-8")
    assert correct_code.count("average.std(ddof=1)") == 1
    faulty_source.write_text(
        correct_code.replace("average.std(ddof=1)", "average.std(ddof=0)"), encoding="utf-8"
    )
    assert (
        hash_files(fixture_root, [reference_path])[reference_path]
        != original_hashes[reference_path]
    )

    try:
        result = CliRunner().invoke(
            app,
            ["mortality-prototype", "--project-root", str(fixture_root)],
            catch_exceptions=False,
        )
        assert result.exit_code == 1
        assert "Mortality prototype comparison failed" in result.stdout
        assert "could not run" not in result.stdout
        assert "Other pipeline outputs are not checked" in result.stdout

        run_directories = list((fixture_root / "reports/runs").iterdir())
        assert len(run_directories) == 1
        run_directory = run_directories[0]
        execution = ExecutionResult.model_validate_json(
            (run_directory / "execution.json").read_text(encoding="utf-8")
        )
        manifest = RunManifest.model_validate_json(
            (run_directory / "manifest.json").read_text(encoding="utf-8")
        )
        report = json.loads((run_directory / "comparison.json").read_text(encoding="utf-8"))
        comparison = ArtifactComparison.model_validate(report["comparison"])
        trace = GoldenTraceResult.model_validate_json(
            (run_directory / "trace.json").read_text(encoding="utf-8")
        )

        # The process succeeded. The trusted comparator, not Docker, rejects the result.
        assert execution.status is ExecutionStatus.SUCCEEDED
        assert execution.exit_code == 0
        assert execution.runtime_environment is not None
        assert execution.output_files == ["OUTCOME_MORTALITY.csv"]
        assert manifest.execution_result == execution
        assert manifest.artifact_results["OUTCOME_MORTALITY"] == comparison
        assert (
            manifest.source_hashes[reference_path]
            == hash_files(fixture_root, [reference_path])[reference_path]
        )
        assert not comparison.passed
        assert comparison.expected_rows == comparison.actual_rows == 4566
        assert len(comparison.expected_columns) == len(comparison.actual_columns) == 21
        assert comparison.missing_keys == comparison.extra_keys == []
        assert comparison.missing_columns == comparison.extra_columns == []
        assert comparison.missingness_mismatches == 0
        assert comparison.mismatched_cells > 0
        assert set(comparison.mismatched_columns) == {"STDDEV", "GRP_SCORE"}

        assert not trace.all_checked_passed
        assert not trace.scope_complete
        assert len(trace.not_checked_artifacts) == 10
        assert [failure.artifact for failure in trace.first_divergences] == ["OUTCOME_MORTALITY"]
        failure = trace.first_divergences[0]
        assert failure.confirmed_within_scope
        assert failure.unchecked_upstream == ()
        assert set(failure.diagnostic.mismatched_columns) == {"STDDEV", "GRP_SCORE"}
        assert failure.diagnostic.mismatched_cells == comparison.mismatched_cells
        checkpoints = {checkpoint.artifact: checkpoint for checkpoint in trace.checkpoints}
        assert checkpoints["OUTCOME_MORTALITY"].status is CheckpointStatus.FAILED
        boundary = checkpoints["STD_DATA_2025JUL_ANALYSIS"]
        assert boundary.status is CheckpointStatus.NOT_CHECKED
        assert boundary.supplied_reference_input
        assert report["trace_report"] == "trace.json"
        recorded_policy = ArtifactComparisonPolicy.model_validate(report["policy"])
        original_policy = ArtifactComparisonPolicy.model_validate_json(
            (fixture_root / "configs/mortality-comparison-policy.json").read_text(encoding="utf-8")
        )
        assert recorded_policy == original_policy
    finally:
        assert hash_files(project_root, [*immutable_paths, reference_path]) == original_hashes
        assert hash_files(fixture_root, immutable_paths) == fixture_hashes
        integrity = load_and_verify_integrity(
            fixture_root, fixture_root / "configs/protected-artifacts.json"
        )
        assert integrity.passed
        assert integrity.checked_files == len(protected.files)
