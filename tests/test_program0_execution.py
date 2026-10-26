"""Program 0 staging, output transport, and failure classification tests."""

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest
from typer.testing import CliRunner

from sasguard import cli
from sasguard.execution import program0
from sasguard.execution.manifest import RunManifest
from sasguard.execution.result import ExecutionResult, ExecutionStatus

TABLES = {
    "less100_measure.csv": "freq,measure_name\n",
    "measure_average_stddev_2025jul.csv": "_STAT_,SCORE\nN,2\nMEAN,5\n",
    "std_data_2025jul_analysis.csv": "PROVIDER_ID,std_SCORE\n000001,0\nNA,\n",
}


def write_tables(output: Path) -> None:
    """Create transport-valid fixtures that do not claim numerical SAS agreement."""
    output.mkdir(exist_ok=True)
    for name, content in TABLES.items():
        (output / name).write_text(content, encoding="utf-8")


@pytest.fixture
def staged_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    root = tmp_path / "repo"
    source = root / program0.PROGRAM_PATH
    source.parent.mkdir(parents=True)
    source.write_text("* source fixture;", encoding="utf-8")
    hospital_input = root / program0.INPUT_PATH
    hospital_input.parent.mkdir(parents=True)
    hospital_input.write_text("PROVIDER_ID,SCORE\n000001,2\n", encoding="utf-8")
    for directory in ("reference_python", "data/Project_1/SAS Output", "configs"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "reference_python/secret.py").write_text("reference-only", encoding="utf-8")
    (root / "data/Project_1/SAS Output/secret.txt").write_text("gold-only", encoding="utf-8")
    candidate = tmp_path / "candidate.py"
    candidate.write_bytes(b"# Keep original bytes.\r\nprint('candidate')\r\n")
    state = SimpleNamespace(root=root, candidate=candidate, calls=[], integrity_checks=0)

    def integrity(*args: object) -> SimpleNamespace:
        state.integrity_checks += 1
        return SimpleNamespace(passed=True)

    def run(self: object, **kwargs: object) -> ExecutionResult:
        state.calls.append(kwargs)
        write_tables(kwargs["output_directory"])
        return ExecutionResult(
            execution_id=uuid4(),
            status=ExecutionStatus.SUCCEEDED,
            exit_code=0,
            runtime_seconds=0.1,
            output_files=list(TABLES),
        )

    monkeypatch.setattr(program0, "load_and_verify_integrity", integrity)
    monkeypatch.setattr(program0.DockerExecutionRunner, "run", run)
    return state


def test_stages_only_candidate_and_input_derived_contract(staged_repo: SimpleNamespace) -> None:
    state = staged_repo
    report, path = program0.run_program0_candidate(state.root, state.candidate)
    assert report.ready_for_validation
    assert report.validation_status == "not_run"
    assert state.integrity_checks == 2
    call = state.calls[0]
    assert sorted(p.name for p in call["source_directory"].iterdir()) == ["main.py"]
    assert sorted(p.name for p in call["input_directory"].iterdir()) == [
        "alldata_2025jul.csv",
        "contract.json",
    ]
    assert (call["source_directory"] / "main.py").read_bytes() == state.candidate.read_bytes()
    contract = json.loads((call["input_directory"] / "contract.json").read_text())
    assert contract["input_columns"] == ["PROVIDER_ID", "SCORE"]
    assert contract["output_filenames"] == list(program0.OUTPUT_FILENAMES)
    assert call["forbidden_host_paths"] == (state.root / "data", state.root / "reference_python")
    manifest = RunManifest.model_validate_json((path.parent / "manifest.json").read_text())
    assert manifest.execution_result.status is ExecutionStatus.SUCCEEDED
    assert manifest.artifact_results == {}
    assert report.artifacts["less100_measure.csv"].rows == 0
    assert report.artifacts["std_data_2025jul_analysis.csv"].rows == 2
    assert report.artifacts["std_data_2025jul_analysis.csv"].columns == ["PROVIDER_ID", "STD_SCORE"]


def test_runs_get_fresh_directories(staged_repo: SimpleNamespace) -> None:
    _, first = program0.run_program0_candidate(staged_repo.root, staged_repo.candidate)
    _, second = program0.run_program0_candidate(staged_repo.root, staged_repo.candidate)
    assert first != second
    assert first.exists() and second.exists()


@pytest.mark.parametrize("code", [b"return 1", b"def broken(:", b"print(1)\x00"])
def test_bad_syntax_does_not_execute(staged_repo: SimpleNamespace, code: bytes) -> None:
    staged_repo.candidate.write_bytes(code)
    report, path = program0.run_program0_candidate(staged_repo.root, staged_repo.candidate)
    assert report.status is program0.CandidateStatus.SYNTAX_ERROR
    assert report.execution_result is None
    assert not staged_repo.calls
    assert path.exists()


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (ExecutionStatus.FAILED, 7, program0.CandidateStatus.EXECUTION_FAILED),
        (ExecutionStatus.TIMED_OUT, None, program0.CandidateStatus.TIMED_OUT),
        (ExecutionStatus.POLICY_VIOLATION, 0, program0.CandidateStatus.POLICY_VIOLATION),
        (ExecutionStatus.RUNNER_ERROR, None, program0.CandidateStatus.RUNNER_ERROR),
    ],
)
def test_execution_failures_are_not_analytical_failures(
    staged_repo: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    status: ExecutionStatus,
    code: int | None,
    expected: program0.CandidateStatus,
) -> None:
    def run(self: object, **kwargs: object) -> ExecutionResult:
        return ExecutionResult(
            execution_id=uuid4(),
            status=status,
            exit_code=code,
            runtime_seconds=0.1,
            policy_violations=["escaped output"]
            if status is ExecutionStatus.POLICY_VIOLATION
            else [],
        )

    monkeypatch.setattr(program0.DockerExecutionRunner, "run", run)
    report, _ = program0.run_program0_candidate(staged_repo.root, staged_repo.candidate)
    assert report.status is expected
    assert report.validation_status == "not_run"
    assert report.artifacts == {}


def test_integrity_failure_stops_execution(staged_repo: SimpleNamespace, monkeypatch) -> None:
    monkeypatch.setattr(
        program0, "load_and_verify_integrity", lambda *args: SimpleNamespace(passed=False)
    )
    with pytest.raises(ValueError, match="integrity failed before"):
        program0.run_program0_candidate(staged_repo.root, staged_repo.candidate)
    assert not staged_repo.calls


def test_postrun_integrity_failure_prevents_handoff(
    staged_repo: SimpleNamespace, monkeypatch
) -> None:
    outcomes = iter((True, False))
    monkeypatch.setattr(
        program0, "load_and_verify_integrity", lambda *args: SimpleNamespace(passed=next(outcomes))
    )
    report, path = program0.run_program0_candidate(staged_repo.root, staged_repo.candidate)
    assert report.status is program0.CandidateStatus.INTEGRITY_FAILED
    assert not report.ready_for_validation
    assert path.exists()


def test_missing_csv_is_reported(tmp_path: Path) -> None:
    write_tables(tmp_path)
    (tmp_path / "less100_measure.csv").unlink()
    result = program0.collect_program0_outputs(tmp_path)
    assert result.status is program0.CandidateStatus.MISSING_OUTPUTS
    assert result.missing_outputs == ["less100_measure.csv"]


@pytest.mark.parametrize(
    "content", ["", "x,X\n1,2\n", 'x,y\n"unclosed,2\n', "x,y\n1,2,3\n", "x,,z\n1,2,3\n"]
)
def test_malformed_csv_is_reported(tmp_path: Path, content: str) -> None:
    write_tables(tmp_path)
    (tmp_path / "less100_measure.csv").write_text(content, encoding="utf-8")
    result = program0.collect_program0_outputs(tmp_path)
    assert result.status is program0.CandidateStatus.MALFORMED_OUTPUTS
    assert "less100_measure.csv" in result.malformed_outputs


def test_extra_output_cannot_be_handed_off(tmp_path: Path) -> None:
    write_tables(tmp_path)
    (tmp_path / "report.json").write_text("{}", encoding="utf-8")
    result = program0.collect_program0_outputs(tmp_path)
    assert result.status is program0.CandidateStatus.POLICY_VIOLATION


def test_windows_reparse_output_is_rejected_before_following(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_tables(tmp_path)
    linked = tmp_path / "less100_measure.csv"
    original_lstat = Path.lstat

    def lstat(path: Path) -> object:
        metadata = original_lstat(path)
        if path == linked:
            return SimpleNamespace(st_mode=metadata.st_mode, st_file_attributes=0x400)
        return metadata

    monkeypatch.setattr(Path, "lstat", lstat)
    result = program0.collect_program0_outputs(tmp_path)
    assert result.status is program0.CandidateStatus.POLICY_VIOLATION
    assert result.artifacts == {}


def test_csv_with_wrong_values_is_left_for_shared_validation(tmp_path: Path) -> None:
    write_tables(tmp_path)
    (tmp_path / "std_data_2025jul_analysis.csv").write_text(
        "PROVIDER_ID,std_SCORE\nwrong-id,999999\n", encoding="utf-8"
    )
    result = program0.collect_program0_outputs(tmp_path)
    assert result.ready_for_validation
    assert result.validation_status == "not_run"


def test_reference_python_cannot_be_selected(staged_repo: SimpleNamespace) -> None:
    with pytest.raises(ValueError, match="separate from"):
        program0.run_program0_candidate(
            staged_repo.root, staged_repo.root / "reference_python/secret.py"
        )


def test_cli_keeps_collection_separate_from_parity(staged_repo: SimpleNamespace) -> None:
    result = CliRunner().invoke(
        cli.app,
        [
            "run-program0-candidate",
            str(staged_repo.candidate),
            "--project-root",
            str(staged_repo.root),
        ],
    )
    assert result.exit_code == 0
    assert "ready_for_validation" in result.stdout
    assert "SAS comparison: not run" in result.stdout


def test_optional_validator_runs_after_collection_and_is_saved(
    staged_repo: SimpleNamespace,
) -> None:
    calls = []

    def validator(project_root, output_directory, expected_sha256):
        assert len(staged_repo.calls) == 1
        assert staged_repo.integrity_checks == 2
        assert all((output_directory / name).is_file() for name in expected_sha256)
        calls.append(dict(expected_sha256))
        return program0.CandidateValidationResult(status="hash_mismatch")

    report, path = program0.run_program0_candidate(
        staged_repo.root, staged_repo.candidate, validator=validator
    )
    assert len(calls) == 1
    assert report.validation_status == "hash_mismatch"
    assert report.execution_result.passed
    assert report.status is program0.CandidateStatus.READY
    saved = program0.CandidateReport.model_validate_json(path.read_text())
    assert saved == report


def test_syntax_error_does_not_call_optional_validator(staged_repo: SimpleNamespace) -> None:
    staged_repo.candidate.write_bytes(b"def broken(:")

    def forbidden(*args):
        raise AssertionError("syntax failure must not reach the validator")

    report, _ = program0.run_program0_candidate(
        staged_repo.root, staged_repo.candidate, validator=forbidden
    )
    assert report.validation_status == "not_run"


def test_postrun_integrity_failure_never_calls_optional_validator(
    staged_repo: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcomes = iter((True, False))
    monkeypatch.setattr(
        program0, "load_and_verify_integrity", lambda *args: SimpleNamespace(passed=next(outcomes))
    )
    calls = []

    def forbidden(*args):
        calls.append(args)
        raise AssertionError("integrity failure must not reach validation")

    report, path = program0.run_program0_candidate(
        staged_repo.root, staged_repo.candidate, validator=forbidden
    )
    assert report.status is program0.CandidateStatus.INTEGRITY_FAILED
    assert report.validation_status == "not_run"
    assert calls == []
    assert program0.CandidateReport.model_validate_json(path.read_text()) == report


def test_cli_validate_exits_unsuccessfully_and_preserves_file_reasons(
    staged_repo: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def validator(*args):
        return program0.CandidateValidationResult(
            status="hash_mismatch", errors={"less100_measure.csv": "output changed"}
        )

    monkeypatch.setattr(cli, "validate_collected_program0", validator)
    result = CliRunner().invoke(
        cli.app,
        [
            "run-program0-candidate",
            str(staged_repo.candidate),
            "--project-root",
            str(staged_repo.root),
            "--validate",
        ],
    )
    assert result.exit_code == 1
    assert "SAS comparison: hash_mismatch" in result.stdout
    assert "Full pipeline and CMS ratings are not verified" in result.stdout
    path = next((staged_repo.root / "reports/runs").glob("*/report.json"))
    saved = program0.CandidateReport.model_validate_json(path.read_text())
    assert saved.validation_errors == {"less100_measure.csv": "output changed"}
    assert saved.execution_result.passed


def test_sas_source_is_staged_as_csv_with_separate_hashes(
    staged_repo: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = (staged_repo.root / program0.INPUT_PATH).with_suffix(".sas7bdat")
    binary.write_bytes(b"test source input")
    original_load = program0.load_artifact
    frame = pd.DataFrame(
        {"PROVIDER_ID": ["000001", "NA", "NULL"], "SCORE": [0.12345678901234566, 2.0, None]}
    )

    def load(path, **kwargs):
        if path == binary:
            assert kwargs == {"key": "PROVIDER_ID"}
            return SimpleNamespace(frame=frame)
        return original_load(path, **kwargs)

    monkeypatch.setattr(program0, "load_artifact", load)
    report, path = program0.run_program0_candidate(
        staged_repo.root, staged_repo.candidate, input_format=program0.CandidateInputFormat.SAS7BDAT
    )
    staged = path.parent / "input/alldata_2025jul.csv"
    loaded = pd.read_csv(staged, converters={"PROVIDER_ID": str}, float_precision="round_trip")
    assert loaded["PROVIDER_ID"].tolist() == frame["PROVIDER_ID"].tolist()
    assert loaded["SCORE"].iloc[:2].tolist() == frame["SCORE"].iloc[:2].tolist()
    metadata = json.loads((path.parent / "staging.json").read_text())
    assert metadata["input_format"] == "sas7bdat"
    assert metadata["input_source_sha256"] == program0.sha256_file(binary)
    assert metadata["staged_input_sha256"] == program0.sha256_file(staged)
    assert report.input_format is program0.CandidateInputFormat.SAS7BDAT
    assert report.validation_status == "not_run"
