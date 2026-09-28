"""Controller trust-boundary and failure tests without a Docker dependency."""

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import sasguard.prototypes.mortality as prototype
from sasguard.execution.manifest import RunManifest
from sasguard.execution.result import ExecutionResult, ExecutionStatus
from sasguard.provenance.hashing import sha256_file
from sasguard.verification import ArtifactComparison, ReferenceSource


@pytest.fixture
def controller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Make a small repository and instrument the external boundaries."""
    root = tmp_path / "repo"
    for directory in ("configs", "reference_python", "sas", "gold", "gold_csv"):
        (root / directory).mkdir(parents=True)
    policy_path = Path(__file__).resolve().parents[1] / "configs/mortality-comparison-policy.json"
    (root / "configs/mortality-comparison-policy.json").write_bytes(policy_path.read_bytes())
    (root / "configs/cms_2025jul.yaml").write_text("fixture\n", encoding="utf-8")
    (root / "reference_python/mortality.py").write_text("# reference snapshot\n", encoding="utf-8")
    program = root / "sas/program.sas"
    program.write_text("* supplied source;\n", encoding="utf-8")
    intermediate = root / "gold/std_data_2025jul_analysis.sas7bdat"
    reference = root / "gold/outcome_mortality.sas7bdat"
    intermediate.write_bytes(b"standardized input")
    reference.write_bytes(b"trusted output not mounted")
    paths = SimpleNamespace(
        reference_sas7bdat={
            "STD_DATA_2025JUL_ANALYSIS": intermediate,
            "OUTCOME_MORTALITY": reference,
        },
        reference_sas7bdat_directory=root / "gold",
        reference_csv_directory=root / "gold_csv",
        programs=(program,),
        macros=(),
    )
    config = SimpleNamespace(
        project=SimpleNamespace(key="PROVIDER_ID"), resolve_paths=lambda _: paths
    )
    state = SimpleNamespace(
        root=root,
        paths=paths,
        mounts=None,
        loaded=[],
        checks=[],
        status=ExecutionStatus.SUCCEEDED,
        intact=True,
        passed=True,
    )

    def integrity(*args):
        state.checks.append(args)
        return SimpleNamespace(passed=state.intact)

    def execute(self, **mounts):
        state.mounts = mounts
        assert {path.name for path in mounts["input_directory"].iterdir()} == {intermediate.name}
        assert {path.name for path in mounts["source_directory"].iterdir()} == {"mortality.py"}
        assert (
            reference.read_bytes()
            not in (mounts["input_directory"] / intermediate.name).read_bytes()
        )
        assert mounts["forbidden_host_paths"] == (root / "gold", root / "gold_csv")
        output = mounts["output_directory"]
        output.mkdir()
        (output / "OUTCOME_MORTALITY.csv").write_text("PROVIDER_ID\n00001\n", encoding="utf-8")
        return ExecutionResult(
            execution_id=uuid4(),
            status=state.status,
            exit_code=0 if state.status is ExecutionStatus.SUCCEEDED else 7,
            runtime_seconds=0.1,
        )

    def load(path, **kwargs):
        state.loaded.append(path)
        return object()

    def compare(*args, **kwargs):
        return ArtifactComparison(
            artifact="OUTCOME_MORTALITY",
            passed=state.passed,
            reference_source=ReferenceSource.SAS7BDAT,
            expected_rows=1,
            actual_rows=1,
            expected_columns=["PROVIDER_ID"],
            actual_columns=["PROVIDER_ID"],
        )

    monkeypatch.setattr(prototype, "load_project_configuration", lambda *args, **kwargs: config)
    monkeypatch.setattr(prototype, "load_and_verify_integrity", integrity)
    monkeypatch.setattr(prototype.DockerExecutionRunner, "run", execute)
    monkeypatch.setattr(prototype, "load_artifact", load)
    monkeypatch.setattr(prototype, "compare_artifacts", compare)
    return state


@pytest.mark.parametrize("passed", [True, False])
def test_controller_stages_only_inputs_and_preserves_comparison(controller, passed: bool) -> None:
    controller.passed = passed
    comparison, report_path = prototype.run_mortality_prototype(controller.root)
    assert comparison.passed is passed
    assert controller.loaded == [
        report_path.parent / "output/OUTCOME_MORTALITY.csv",
        controller.paths.reference_sas7bdat["OUTCOME_MORTALITY"],
    ]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["implementation"] == "human_reference"
    assert report["comparison"]["passed"] is passed
    assert report["reference_sha256"] == sha256_file(controller.loaded[1])
    manifest = RunManifest.model_validate_json((report_path.parent / "manifest.json").read_text())
    assert manifest.artifact_results["OUTCOME_MORTALITY"].passed is passed
    assert manifest.source_hashes and manifest.input_hashes
    assert manifest.generated_code_hashes == {}
    assert manifest.model_name is None
    assert manifest.execution_result.status is ExecutionStatus.SUCCEEDED
    assert len(controller.checks) == 3


def test_controller_execution_failure_records_result_without_loading_gold(controller) -> None:
    controller.status = ExecutionStatus.FAILED
    with pytest.raises(RuntimeError, match="execution failed"):
        prototype.run_mortality_prototype(controller.root)
    assert controller.loaded == []
    run_directory = next((controller.root / "reports/runs").iterdir())
    manifest = RunManifest.model_validate_json((run_directory / "manifest.json").read_text())
    assert manifest.execution_result.status is ExecutionStatus.FAILED
    assert not (run_directory / "comparison.json").exists()
    assert len(controller.checks) == 2


def test_controller_rejects_changed_protected_artifacts_before_execution(controller) -> None:
    controller.intact = False
    with pytest.raises(ValueError, match="before the Mortality run"):
        prototype.run_mortality_prototype(controller.root)
    assert controller.mounts is None
    assert controller.loaded == []


def test_controller_rejects_postexecution_integrity_failure(controller, monkeypatch) -> None:
    checks = iter([True, False])
    monkeypatch.setattr(
        prototype,
        "load_and_verify_integrity",
        lambda *args: SimpleNamespace(passed=next(checks)),
    )
    with pytest.raises(ValueError, match="after the Mortality run"):
        prototype.run_mortality_prototype(controller.root)
    assert controller.mounts is not None
    assert controller.loaded == []
