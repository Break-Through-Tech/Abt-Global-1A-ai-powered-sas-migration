"""Recorded evidence is summarized without executing code or leaking logs and row keys."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from sasguard import cli
from sasguard.config import load_project_configuration
from sasguard.execution.environment import DockerRuntimeEnvironment, PythonEnvironment
from sasguard.execution.manifest import RunManifest
from sasguard.execution.result import ExecutionResult, ExecutionStatus
from sasguard.prototypes.mortality import mortality_policy
from sasguard.provenance.hashing import hash_files, sha256_file
from sasguard.reporting import write_run_report
from sasguard.reporting.models import ScopeStatus
from sasguard.reporting.reader import MORTALITY_SCOPE, read_run_report
from sasguard.reporting.render import render_handoff, render_technical
from sasguard.verification import ArtifactComparison, ArtifactComparisonPolicy, ReferenceSource
from sasguard.verification.golden_trace import trace_artifacts
from sasguard.verification.integrity import ProtectedArtifactManifest, ProtectedFile
from sasguard.verification.lineage import ArtifactLineage

SECRET = "PRIVATE_ROW_OR_LOG_SENTINEL_92834"
REPO = Path(__file__).resolve().parents[1]


def execution(status: ExecutionStatus = ExecutionStatus.SUCCEEDED) -> ExecutionResult:
    return ExecutionResult(
        execution_id=uuid4(),
        status=status,
        exit_code=0 if status is ExecutionStatus.SUCCEEDED else 7,
        runtime_seconds=1.25,
        stdout=SECRET,
        stderr=SECRET,
        output_files=["OUTCOME_MORTALITY.csv"],
        runtime_environment=DockerRuntimeEnvironment(
            requested_image="sasguard-runner:test",
            image_id="sha256:" + "d" * 64,
            repo_digests=[],
            operating_system="linux",
            architecture="amd64",
            python=PythonEnvironment(
                python_version="3.11.9",
                operating_system="Linux",
                architecture="x86_64",
                packages={"pandas": "2.3.3"},
            ),
        ),
    )


def comparison(
    *, artifact: str, passed: bool, source: ReferenceSource, columns: list[str]
) -> ArtifactComparison:
    return ArtifactComparison(
        artifact=artifact,
        passed=passed,
        reference_source=source,
        expected_rows=2,
        actual_rows=2,
        expected_columns=columns,
        actual_columns=columns,
        missing_keys=[] if passed else [SECRET],
        extra_keys=[] if passed else [SECRET + "_EXTRA"],
        mismatched_columns=[] if passed else [columns[-1]],
        mismatched_cells=0 if passed else 1,
        missingness_mismatches=0 if passed else 1,
        exact_cells=2 if passed else 0,
    )


def mortality_bundle(root: Path, *, passed: bool = True, state: str = "complete") -> Path:
    """Tiny recorded bundle. Tests do not purport to execute SAS or read SAS table bytes."""
    run = root / "reports/runs/mortality-test"
    for folder in (run / "source", run / "input", run / "output", root / "configs"):
        folder.mkdir(parents=True)
    for name in (
        "cms_2025jul.yaml",
        "mortality-comparison-policy.json",
        "cms-artifact-lineage.json",
    ):
        shutil.copyfile(REPO / "configs" / name, root / "configs" / name)
    policy = mortality_policy(root)
    config = load_project_configuration(
        root / "configs/cms_2025jul.yaml", project_root=root, require_existing=False
    )
    paths = config.resolve_paths(root)
    relatives = [path.relative_to(root).as_posix() for path in (*paths.programs, *paths.macros)]
    relatives += [
        "reference_python/mortality.py",
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
    for relative in relatives:
        path = root / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("raise AssertionError('must not execute')\n")
    source = root / "reference_python/mortality.py"
    shutil.copyfile(source, run / "source/mortality.py")
    reference = paths.reference_sas7bdat["OUTCOME_MORTALITY"]
    intermediate = paths.reference_sas7bdat["STD_DATA_2025JUL_ANALYSIS"]
    for path in (reference, intermediate):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"simulated protected reference file")
    shutil.copyfile(intermediate, run / "input" / intermediate.name)
    protected = ProtectedArtifactManifest(
        protected_roots=[reference.parent.relative_to(root).as_posix()],
        files=[
            ProtectedFile(path=path.relative_to(root).as_posix(), sha256=sha256_file(path))
            for path in (reference, intermediate)
        ],
    )
    (root / "configs/protected-artifacts.json").write_text(protected.model_dump_json())
    manifest = RunManifest.create(
        source_hashes=hash_files(root, relatives),
        input_hashes=hash_files(root, [intermediate.relative_to(root).as_posix()]),
    )
    result = execution(
        ExecutionStatus.FAILED if state == "execution_failed" else ExecutionStatus.SUCCEEDED
    )
    if state != "not_run":
        manifest = manifest.with_execution_result(result)
        (run / "execution.json").write_text(result.model_dump_json())
    lineage = ArtifactLineage.model_validate_json(
        (root / "configs/cms-artifact-lineage.json").read_text()
    )
    comparisons = []
    if state == "complete":
        cmp = comparison(
            artifact="OUTCOME_MORTALITY",
            passed=passed,
            source=ReferenceSource.SAS7BDAT,
            columns=["PROVIDER_ID", *(rule.name for rule in policy.columns)],
        )
        output = run / "output/OUTCOME_MORTALITY.csv"
        output.write_text(SECRET)
        manifest = manifest.model_copy(
            update={
                "artifact_results": {cmp.artifact: cmp},
                "reference_sources": {cmp.artifact: cmp.reference_source},
            }
        )
        (run / "comparison.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "implementation": "human_reference",
                    "scope": MORTALITY_SCOPE,
                    "input_artifact": "STD_DATA_2025JUL_ANALYSIS",
                    "reference_artifact": "OUTCOME_MORTALITY",
                    "runner_image": "sasguard-runner:test",
                    "runner_environment": result.runtime_environment.model_dump(mode="json"),
                    "reference_sha256": sha256_file(reference),
                    "output_sha256": sha256_file(output),
                    "trace_report": "trace.json",
                    "policy": policy.model_dump(mode="json"),
                    "comparison": cmp.model_dump(mode="json"),
                }
            )
        )
        comparisons = [cmp]
    trace = trace_artifacts(
        lineage,
        comparisons,
        scope=MORTALITY_SCOPE,
        supplied_reference_inputs=["STD_DATA_2025JUL_ANALYSIS"],
    )
    (run / "trace.json").write_text(trace.to_json())
    (run / "manifest.json").write_text(manifest.to_json())
    return run


def synthetic_bundle(root: Path, *, passed: bool = True, validation_error: bool = False) -> Path:
    run = root / "reports/runs/synthetic-test"
    files = {
        "source.sas": SECRET,
        "prompt.txt": SECRET,
        "request.json": SECRET,
        "response.json": SECRET,
        "source/main.py": f"raise AssertionError('{SECRET}')",
        "input/input.csv": SECRET,
        "expected/adjusted.csv": SECRET,
        "output/adjusted.csv": SECRET,
        "policy.json": ArtifactComparisonPolicy(keys=("PROVIDER_ID",)).to_json(),
    }
    for relative, content in files.items():
        path = run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    cmp = comparison(
        artifact="SYNTHETIC_ADJUSTED",
        passed=passed,
        source=ReferenceSource.CSV,
        columns=["PROVIDER_ID", "SCORE", "ADJUSTED"],
    )
    result = execution().model_copy(update={"output_files": ["adjusted.csv"]})
    (run / "report.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "timestamp": datetime(2026, 10, 20, tzinfo=UTC).isoformat(),
                "case": "double-score",
                "scope": SECRET,
                "model": "qwen3:4b",
                "generation_status": "succeeded",
                "execution_result": result.model_dump(mode="json"),
                "validation_status": "failed" if validation_error or not passed else "passed",
                "comparison": None if validation_error else cmp.model_dump(mode="json"),
                "hashes": {relative: sha256_file(run / relative) for relative in files},
                "error": SECRET,
                "human_review": SECRET,
                "pipeline_complete": True,
            }
        )
    )
    return run


@pytest.mark.parametrize(
    "passed,status", [(True, ScopeStatus.VERIFIED), (False, ScopeStatus.FAILED)]
)
def test_mortality_scoped_status_and_privacy(
    tmp_path: Path, passed: bool, status: ScopeStatus
) -> None:
    run = mortality_bundle(tmp_path, passed=passed)
    snapshot = {path: path.read_bytes() for path in run.rglob("*") if path.is_file()}
    report = read_run_report(tmp_path, run)
    assert report.scope_status is status
    assert report.pipeline_complete is report.client_release_approved is False
    assert report.human_review == "not_recorded"
    assert report.hospitals_processed is report.hospitals_eligible is report.final_ratings is None
    destination = write_run_report(tmp_path, run)
    assert {path.name for path in destination.iterdir()} == {
        "handoff.md",
        "technical.md",
        "report.json",
    }
    content = "\n".join(path.read_text() for path in destination.iterdir())
    assert SECRET not in content
    assert str(tmp_path) not in content
    assert "Full-pipeline status: NOT VERIFIED" in render_handoff(report)
    if not passed:
        assert report.artifacts[0].missing_key_count == 1
        assert report.first_observed_failures == ("OUTCOME_MORTALITY",)
    assert all(path.read_bytes() == data for path, data in snapshot.items())


@pytest.mark.parametrize(
    "state,status",
    [
        ("execution_failed", ScopeStatus.FAILED),
        ("not_run", ScopeStatus.NOT_VERIFIED),
        ("missing_comparison", ScopeStatus.NOT_VERIFIED),
    ],
)
def test_no_inferred_comparison_success(tmp_path: Path, state: str, status: ScopeStatus) -> None:
    run = mortality_bundle(tmp_path, state=state)
    report = read_run_report(tmp_path, run)
    assert report.scope_status is status
    assert report.validation_status == "not_run"


@pytest.mark.parametrize(
    "relative",
    [
        "output/OUTCOME_MORTALITY.csv",
        "source/mortality.py",
        "input/std_data_2025jul_analysis.sas7bdat",
    ],
)
def test_changed_run_evidence_cannot_remain_verified(tmp_path: Path, relative: str) -> None:
    run = mortality_bundle(tmp_path)
    (run / relative).write_text("changed")
    report = read_run_report(tmp_path, run)
    assert report.scope_status is ScopeStatus.NOT_VERIFIED
    assert report.evidence_issues


@pytest.mark.parametrize(
    "passed,error,status",
    [
        (True, False, ScopeStatus.NOT_VERIFIED),
        (False, False, ScopeStatus.FAILED),
        (True, True, ScopeStatus.FAILED),
    ],
)
def test_synthetic_never_claims_sas_parity_or_copies_raw_fields(
    tmp_path: Path,
    passed: bool,
    error: bool,
    status: ScopeStatus,
) -> None:
    run = synthetic_bundle(tmp_path, passed=passed, validation_error=error)
    report = read_run_report(tmp_path, run)
    assert report.scope_status is status
    assert report.artifacts[0].reference_authority == "handwritten_synthetic"
    assert report.human_review == "not_recorded"
    destination = write_run_report(tmp_path, run)
    assert SECRET not in "\n".join(path.read_text() for path in destination.iterdir())


def test_changed_synthetic_output_is_flagged(tmp_path: Path) -> None:
    run = synthetic_bundle(tmp_path)
    (run / "output/adjusted.csv").write_text("changed")
    report = read_run_report(tmp_path, run)
    assert report.evidence_integrity == "not_confirmed"
    assert report.scope_status is ScopeStatus.NOT_VERIFIED


@pytest.mark.parametrize("change", ["reference", "artifact_results", "trace", "code_origin"])
def test_mortality_evidence_disagreements_do_not_produce_verified(
    tmp_path: Path, change: str
) -> None:
    run = mortality_bundle(tmp_path)
    if change == "reference":
        path = run / "comparison.json"
        data = json.loads(path.read_text())
        data["reference_sha256"] = "a" * 64
    elif change in ("artifact_results", "code_origin"):
        path = run / "manifest.json"
        data = json.loads(path.read_text())
        if change == "artifact_results":
            data["artifact_results"] = {}
        else:
            data["model"] = "test-model"
            data["temperature"] = 0
            data["prompt_version"] = "test-v1"
    else:
        path = run / "trace.json"
        lineage = ArtifactLineage.model_validate_json(
            (tmp_path / "configs/cms-artifact-lineage.json").read_text()
        )
        data = json.loads(
            trace_artifacts(
                lineage,
                [],
                scope=MORTALITY_SCOPE,
                supplied_reference_inputs=["STD_DATA_2025JUL_ANALYSIS"],
            ).to_json()
        )
    path.write_text(json.dumps(data))
    report = read_run_report(tmp_path, run)
    assert report.scope_status is ScopeStatus.NOT_VERIFIED
    assert report.evidence_issues


@pytest.mark.parametrize("stage", ["generation", "execution", "output_contract"])
def test_synthetic_failure_stages_remain_explicit(tmp_path: Path, stage: str) -> None:
    run = synthetic_bundle(tmp_path)
    source = run / "report.json"
    data = json.loads(source.read_text())
    data["comparison"] = None
    data["validation_status"] = "not_run"
    if stage == "generation":
        data["generation_status"] = "failed"
        data["execution_result"] = None
    elif stage == "execution":
        data["execution_result"] = execution(ExecutionStatus.FAILED).model_dump(mode="json")
    else:
        data["execution_result"]["output_files"] = ["wrong-name.csv"]
        data["validation_status"] = "failed"
    source.write_text(json.dumps(data))
    report = read_run_report(tmp_path, run)
    assert report.scope_status is ScopeStatus.FAILED
    assert report.validation_status == data["validation_status"]


def test_synthetic_claimed_pass_without_comparison_is_not_confirmed(tmp_path: Path) -> None:
    run = synthetic_bundle(tmp_path)
    source = run / "report.json"
    data = json.loads(source.read_text())
    data["comparison"] = None
    source.write_text(json.dumps(data))
    report = read_run_report(tmp_path, run)
    assert report.scope_status is ScopeStatus.NOT_VERIFIED
    assert report.evidence_integrity == "not_confirmed"


@pytest.mark.parametrize("kind", ["synthetic", "mortality"])
def test_deterministic_output_and_no_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    run = synthetic_bundle(tmp_path) if kind == "synthetic" else mortality_bundle(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("report generation must not execute code or call Docker")

    monkeypatch.setattr("sasguard.execution.runner.DockerExecutionRunner.run", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    first, second = write_run_report(tmp_path, run), write_run_report(tmp_path, run)
    for name in ("handoff.md", "technical.md", "report.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_no_overwrite_or_nested_output(tmp_path: Path) -> None:
    run = synthetic_bundle(tmp_path)
    with pytest.raises(ValueError, match="separate new directory"):
        write_run_report(tmp_path, run, output_directory=run / "nested")
    output = write_run_report(tmp_path, run)
    before = (output / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        write_run_report(tmp_path, run, output_directory=output)
    assert (output / "report.json").read_bytes() == before
    with pytest.raises(ValueError):
        write_run_report(tmp_path, run, output_directory=tmp_path.parent / "outside")
    with pytest.raises(ValueError, match="top-level saved run"):
        read_run_report(tmp_path, run / "output")


def test_escape_and_unknown_layout_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside reports/runs"):
        read_run_report(tmp_path, tmp_path.parent)
    empty = tmp_path / "reports/runs/empty"
    empty.mkdir(parents=True)
    with pytest.raises(ValueError, match="unsupported run layout"):
        read_run_report(tmp_path, empty)


def test_markdown_escapes_schema_metadata(tmp_path: Path) -> None:
    report = read_run_report(tmp_path, synthetic_bundle(tmp_path))
    artifact = report.artifacts[0].model_copy(update={"actual_columns": ("<script>|x\ny",)})
    text = render_technical(report.model_copy(update={"artifacts": (artifact,)}))
    assert "<script>" not in text
    assert "&lt;script&gt;\\|x y" in text


def test_cli_emits_draft_and_parse_errors(tmp_path: Path) -> None:
    run = synthetic_bundle(tmp_path)
    result = CliRunner().invoke(cli.app, ["report-run", str(run), "--project-root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Internal draft generated" in result.stdout
    result = CliRunner().invoke(cli.app, ["report-run", "missing", "--project-root", str(tmp_path)])
    assert result.exit_code == 2
