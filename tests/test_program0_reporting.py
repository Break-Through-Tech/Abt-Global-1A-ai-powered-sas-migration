"""Program 0 saved-record reports preserve scope, input identity, and privacy."""

import json
import shutil
from pathlib import Path

import pytest
from test_reporting import SECRET, comparison, execution

from sasguard.config import load_project_configuration
from sasguard.execution import program0 as controller
from sasguard.execution.manifest import RunManifest
from sasguard.execution.program0 import (
    INPUT_PATH,
    PROGRAM_PATH,
    VALIDATION_SOURCE_PATHS,
    CandidateReport,
    CandidateStatus,
    CollectedArtifact,
    Program0ValidationEvidence,
)
from sasguard.provenance.hashing import hash_files, sha256_file
from sasguard.reporting import write_run_report
from sasguard.reporting.models import ScopeStatus
from sasguard.reporting.reader import read_run_report
from sasguard.verification.artifact import ReferenceSource
from sasguard.verification.integrity import ProtectedArtifactManifest, ProtectedFile
from sasguard.verification.program0 import (
    EXACT_STATISTIC_ROWS,
    PROGRAM0_ARTIFACTS,
    Program0Validation,
    load_program0_policies,
)

REPO = Path(__file__).resolve().parents[1]


def bundle(root: Path, state: str = "passed", mode: str = "csv") -> Path:
    run = root / "reports/runs/program0-test"
    for directory in (run / "source", run / "input", run / "output", root / "configs"):
        directory.mkdir(parents=True, exist_ok=True)
    for name in ("cms_2025jul.yaml", "program0-comparison-policies.json"):
        shutil.copyfile(REPO / "configs" / name, root / "configs" / name)
    config = load_project_configuration(
        root / "configs/cms_2025jul.yaml", project_root=root, require_existing=False
    )
    paths = config.resolve_paths(root)
    source_input = (
        INPUT_PATH if mode == "csv" else Path(INPUT_PATH).with_suffix(".sas7bdat").as_posix()
    )
    protected_paths = [
        PROGRAM_PATH,
        source_input,
        *(
            paths.reference_sas7bdat[name].relative_to(root).as_posix()
            for name in PROGRAM0_ARTIFACTS.values()
        ),
    ]
    for relative in (
        *protected_paths,
        *VALIDATION_SOURCE_PATHS,
        "src/sasguard/execution/program0.py",
    ):
        path = root / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture bytes must not execute", encoding="utf-8")
    protected = ProtectedArtifactManifest(
        protected_roots=["data/Project_1"],
        files=[
            ProtectedFile(path=relative, sha256=sha256_file(root / relative))
            for relative in protected_paths
        ],
    )
    (root / "configs/protected-artifacts.json").write_text(protected.model_dump_json())
    (run / "source/main.py").write_text(f"raise AssertionError({SECRET!r})", encoding="utf-8")
    (run / "input/alldata_2025jul.csv").write_text(SECRET)
    (run / "input/contract.json").write_text("{}")
    output = {}
    comparisons = {}
    for filename, artifact in PROGRAM0_ARTIFACTS.items():
        path = run / "output" / filename
        path.write_text(SECRET)
        output[filename] = CollectedArtifact(
            relative_path=f"output/{filename}",
            sha256=sha256_file(path),
            rows=2,
            columns=["KEY", "VALUE"],
        )
        comparisons[filename] = comparison(
            artifact=artifact,
            passed=state != "failed",
            source=ReferenceSource.SAS7BDAT,
            columns=["KEY", "VALUE"],
        )
    execution_result = execution().model_copy(update={"output_files": list(PROGRAM0_ARTIFACTS)})
    report_status = CandidateStatus.READY
    if state == "execution_failed":
        from sasguard.execution.result import ExecutionStatus

        execution_result = execution(ExecutionStatus.FAILED)
        report_status = CandidateStatus.EXECUTION_FAILED
    if state == "syntax_error":
        execution_result = None
        report_status = CandidateStatus.SYNTAX_ERROR
    if state == "collection_missing":
        report_status = CandidateStatus.MISSING_OUTPUTS
    validation = (
        state
        if state in ("passed", "failed", "hash_mismatch", "malformed_outputs", "validator_error")
        else "not_run"
    )
    evidence = (
        Program0ValidationEvidence(
            project_hashes=hash_files(root, [*VALIDATION_SOURCE_PATHS, *protected_paths[2:]]),
            policies=load_program0_policies(root),
            exact_statistic_rows=EXACT_STATISTIC_ROWS,
            output_hashes={name: item.sha256 for name, item in output.items()},
            candidate_sha256=sha256_file(run / "source/main.py"),
        )
        if validation not in ("not_run", "validator_error")
        else None
    )
    report = CandidateReport.model_validate(
        {
            "status": report_status,
            "input_format": mode,
            "execution_result": execution_result,
            "artifacts": output,
            "validation_status": validation,
            "validation_results": comparisons if state in ("passed", "failed") else {},
            "validation_errors": {next(iter(PROGRAM0_ARTIFACTS)): SECRET}
            if state in ("hash_mismatch", "malformed_outputs")
            else {},
            "validation_error": SECRET if state == "validator_error" else None,
            "validation_evidence": evidence,
        }
    )
    manifest = RunManifest.create(
        source_hashes=hash_files(root, [PROGRAM_PATH]),
        input_hashes=hash_files(root, [source_input]),
        generated_code_hashes={"source/main.py": sha256_file(run / "source/main.py")},
    )
    if execution_result is not None:
        manifest = manifest.with_execution_result(execution_result)
    (run / "manifest.json").write_text(manifest.to_json())
    (run / "report.json").write_text(report.model_dump_json())
    (run / "staging.json").write_text(
        json.dumps(
            {
                "candidate_sha256_bytes": sha256_file(run / "source/main.py", normalize_text=False),
                "contract_sha256": sha256_file(run / "input/contract.json"),
                "controller_sha256": sha256_file(root / "src/sasguard/execution/program0.py"),
                "validation_status": "not_run",
                "input_format": mode,
                "input_source_path": source_input,
                "input_source_sha256": manifest.input_hashes[source_input],
                "staged_input_sha256": sha256_file(run / "input/alldata_2025jul.csv"),
            }
        )
    )
    return run


@pytest.mark.parametrize("mode", ["csv", "sas7bdat"])
@pytest.mark.parametrize(
    "state,expected",
    [
        ("passed", ScopeStatus.VERIFIED),
        ("failed", ScopeStatus.FAILED),
        ("not_run", ScopeStatus.NOT_VERIFIED),
        ("execution_failed", ScopeStatus.FAILED),
        ("syntax_error", ScopeStatus.FAILED),
        ("collection_missing", ScopeStatus.FAILED),
        ("hash_mismatch", ScopeStatus.FAILED),
        ("malformed_outputs", ScopeStatus.FAILED),
        ("validator_error", ScopeStatus.FAILED),
    ],
)
def test_program0_reports_scope_input_and_privacy(
    tmp_path: Path, state: str, expected: ScopeStatus, mode: str
) -> None:
    run = bundle(tmp_path, state, mode)
    before = {path: path.read_bytes() for path in run.rglob("*") if path.is_file()}
    report = read_run_report(tmp_path, run)
    assert report.scope_status is expected
    assert report.input_format == mode
    assert report.code_origin == report.generation_status == "not_recorded"
    assert len(report.artifacts) == 3
    assert report.pipeline_complete is report.client_release_approved is False
    output = write_run_report(tmp_path, run)
    content = "\n".join(path.read_text() for path in output.iterdir())
    assert SECRET not in content
    assert "Full-pipeline status: NOT VERIFIED" in content
    assert "Code origin: not recorded" in content
    assert all(path.read_bytes() == data for path, data in before.items())
    assert report.validation_outcome == (
        state
        if state in ("passed", "failed", "hash_mismatch", "malformed_outputs", "validator_error")
        else "not_run"
    )
    if state in ("passed", "failed"):
        assert report.exact_statistic_rows == ("N", "MIN", "MAX")
    if state == "failed":
        assert all(item.missing_key_count == 1 for item in report.artifacts)


@pytest.mark.parametrize(
    "relative",
    [
        "source/main.py",
        "input/alldata_2025jul.csv",
        "input/contract.json",
        "output/std_data_2025jul_analysis.csv",
    ],
)
def test_changed_run_files_remove_verified_claim(tmp_path: Path, relative: str) -> None:
    run = bundle(tmp_path)
    (run / relative).write_text("changed")
    report = read_run_report(tmp_path, run)
    assert report.scope_status is ScopeStatus.NOT_VERIFIED
    assert report.evidence_issues


def test_legacy_comparison_pass_without_snapshot_is_not_verified(tmp_path: Path) -> None:
    run = bundle(tmp_path)
    path = run / "report.json"
    data = json.loads(path.read_text())
    del data["validation_evidence"]
    path.write_text(json.dumps(data))
    report = read_run_report(tmp_path, run)
    assert report.validation_status == "passed"
    assert report.scope_status is ScopeStatus.NOT_VERIFIED
    assert "validation_snapshot_not_recorded" in report.evidence_issues


@pytest.mark.parametrize(
    "change",
    ["policy", "reference", "execution", "snapshot", "candidate", "rows", "missing_collection"],
)
def test_conflicting_records_never_produce_verification(tmp_path: Path, change: str) -> None:
    run = bundle(tmp_path)
    path = run / "report.json"
    data = json.loads(path.read_text())
    if change == "policy":
        data["validation_evidence"]["policies"]["STD_DATA_2025JUL_ANALYSIS"]["columns"] = []
    elif change == "reference":
        config = load_project_configuration(
            tmp_path / "configs/cms_2025jul.yaml", project_root=tmp_path, require_existing=False
        ).resolve_paths(tmp_path)
        config.reference_sas7bdat["LESS100_MEASURE"].write_bytes(b"changed")
    elif change == "execution":
        data["execution_result"]["runtime_seconds"] += 1
    elif change == "snapshot":
        data["validation_evidence"]["project_hashes"]["../../private"] = "a" * 64
    elif change == "rows":
        data["artifacts"]["less100_measure.csv"]["rows"] = 999
    elif change == "missing_collection":
        del data["artifacts"]["less100_measure.csv"]
    else:
        data["validation_evidence"]["candidate_sha256"] = "a" * 64
    path.write_text(json.dumps(data))
    assert read_run_report(tmp_path, run).scope_status is ScopeStatus.NOT_VERIFIED


def test_report_generation_is_offline_and_does_not_revalidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = bundle(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("reports must not rerun code or numerical comparisons")

    monkeypatch.setattr("sasguard.execution.runner.DockerExecutionRunner.run", forbidden)
    monkeypatch.setattr("sasguard.verification.program0.validate_program0_outputs", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    write_run_report(tmp_path, run)


@pytest.mark.parametrize("changed_file", ["policy", "reference", "candidate"])
def test_real_wrapper_rejects_changes_during_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_file: str
) -> None:
    run = bundle(tmp_path)
    config = load_project_configuration(
        tmp_path / "configs/cms_2025jul.yaml", project_root=tmp_path, require_existing=False
    )
    monkeypatch.setattr(controller, "load_project_configuration", lambda *args, **kwargs: config)

    def validator(*args):
        target = (
            tmp_path / "configs/program0-comparison-policies.json"
            if changed_file == "policy"
            else run / "source/main.py"
            if changed_file == "candidate"
            else config.resolve_paths(tmp_path).reference_sas7bdat["LESS100_MEASURE"]
        )
        target.write_text("changed during comparison")
        return Program0Validation(status="hash_mismatch")

    monkeypatch.setattr(controller, "validate_program0_outputs", validator)
    saved = CandidateReport.model_validate_json((run / "report.json").read_bytes())
    with pytest.raises(ValueError, match="changed during comparison"):
        controller.validate_collected_program0(
            tmp_path, run / "output", {name: item.sha256 for name, item in saved.artifacts.items()}
        )
