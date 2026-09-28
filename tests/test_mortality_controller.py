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
    (root / "configs/cms_2025jul.yaml").write_bytes(
        (policy_path.parent / "cms_2025jul.yaml").read_bytes()
    )
    (root / "configs/cms-artifact-lineage.json").write_bytes(
        (policy_path.parent / "cms-artifact-lineage.json").read_bytes()
    )
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
    assert report["trace_report"] == "trace.json"
    trace = json.loads((report_path.parent / "trace.json").read_text(encoding="utf-8"))
    assert trace["scope_complete"] is False
    assert trace["all_checked_passed"] is passed
    assert len(trace["checkpoints"]) == 11
    checkpoints = {item["artifact"]: item for item in trace["checkpoints"]}
    boundary = checkpoints["STD_DATA_2025JUL_ANALYSIS"]
    assert boundary["status"] == "not_checked"
    assert boundary["supplied_reference_input"] is True
    assert checkpoints["OUTCOME_MORTALITY"]["status"] == ("passed" if passed else "failed")
    if passed:
        assert trace["first_divergences"] == []
    else:
        assert [item["artifact"] for item in trace["first_divergences"]] == ["OUTCOME_MORTALITY"]
        assert trace["first_divergences"][0]["confirmed_within_scope"] is True
        assert trace["first_divergences"][0]["unchecked_upstream"] == []


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
    trace = json.loads((run_directory / "trace.json").read_text(encoding="utf-8"))
    assert trace["all_checked_passed"] is False
    assert trace["scope_complete"] is False
    assert trace["first_divergences"] == []
    assert all(item["status"] == "not_checked" for item in trace["checkpoints"])


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


@pytest.mark.parametrize(
    "filename",
    ["mortality-comparison-policy.json", "cms_2025jul.yaml", "cms-artifact-lineage.json"],
)
def test_controller_rejects_modified_trusted_configuration(controller, filename: str) -> None:
    path = controller.root / "configs" / filename
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen controller baseline"):
        prototype.run_mortality_prototype(controller.root)
    assert controller.mounts is None
    assert controller.loaded == []


def test_controller_rejects_policy_changed_during_execution(controller, monkeypatch) -> None:
    original_run = prototype.DockerExecutionRunner.run

    def change_policy(self, **mounts):
        result = original_run(self, **mounts)
        path = controller.root / "configs/mortality-comparison-policy.json"
        policy = json.loads(path.read_text(encoding="utf-8"))
        policy["columns"][-1]["tolerance"]["absolute"] = 100
        path.write_text(json.dumps(policy), encoding="utf-8")
        return result

    monkeypatch.setattr(prototype.DockerExecutionRunner, "run", change_policy)
    with pytest.raises(ValueError, match="frozen controller baseline"):
        prototype.run_mortality_prototype(controller.root)
    assert controller.loaded == []
