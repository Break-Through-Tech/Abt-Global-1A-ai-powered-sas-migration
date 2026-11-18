"""Reassessment must reject changed artifacts and never rerun generated Python."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from sasguard import cli
from sasguard.execution.result import ExecutionResult, ExecutionStatus
from sasguard.prototypes import local_model
from sasguard.prototypes.local_model_cases import CASES
from sasguard.prototypes.local_model_reassessment import reassess_local_model_suite
from sasguard.provenance.hashing import sha256_file
from sasguard.verification import ArtifactComparisonPolicy


def saved_suite(root: Path, *, boolean: bool = False, execution_failed: bool = False) -> Path:
    run = root / "reports" / "runs" / "old"
    fixture = CASES["missing-comparison"]
    files = {
        "source.sas": fixture.sas_source,
        "prompt.txt": fixture.prompt,
        "request.json": "{}",
        "response.json": "{}",
        "policy.json": ArtifactComparisonPolicy(keys=(fixture.key,)).to_json(),
        "source/main.py": "raise AssertionError('this candidate must never run')\n",
        "input/input.csv": fixture.input_csv,
        "expected/adjusted.csv": fixture.expected_csv,
        "output/adjusted.csv": fixture.expected_csv,
    }
    if boolean:
        lines = fixture.expected_csv.strip().splitlines()
        files["output/adjusted.csv"] = (
            lines[0]
            + "\n"
            + "\n".join(
                line.rsplit(",", 1)[0] + (",True" if line.endswith(",1") else ",False")
                for line in lines[1:]
            )
            + "\n"
        )
    for relative, text in files.items():
        path = run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    attempt = {
        "schema_version": 1,
        "model": "test:4b",
        "case": fixture.name,
        "condition": "sas-helpers-v2",
        "passed": not execution_failed,
        "generation_status": "succeeded",
        "execution_result": ExecutionResult(
            execution_id=uuid4(),
            status=ExecutionStatus.FAILED if execution_failed else ExecutionStatus.SUCCEEDED,
            exit_code=7 if execution_failed else 0,
            runtime_seconds=1,
            output_files=["adjusted.csv"],
        ).model_dump(mode="json"),
        "hashes": {relative: sha256_file(run / relative) for relative in files},
    }
    (run / "report.json").write_text(json.dumps(attempt), encoding="utf-8")
    path = run / "suite.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "complete": True,
                "models": ["test:4b"],
                "cases": [fixture.name],
                "attempts": [
                    {
                        "model": "test:4b",
                        "case": fixture.name,
                        "passed": not execution_failed,
                        "report": "reports/runs/old/report.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("boolean,passed", [(False, True), (True, False)])
def test_rechecks_without_mutation_or_model_or_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boolean: bool,
    passed: bool,
) -> None:
    path = saved_suite(tmp_path, boolean=boolean)
    original = {file: file.read_bytes() for file in path.parent.rglob("*") if file.is_file()}

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("reassessment must not generate or execute code")

    monkeypatch.setattr(local_model, "_request_json", forbidden)
    monkeypatch.setattr(local_model.DockerExecutionRunner, "run", forbidden)
    outcome, report = reassess_local_model_suite(tmp_path, path)
    data = json.loads(report.read_text())
    assert outcome is passed
    assert data["generation_performed"] is data["execution_performed"] is False
    assert data["source_suite_sha256"] == sha256_file(path)
    assert data["human_review"] == "not_recorded"
    assert data["attempts"][0]["previous_passed"] is True
    assert data["attempts"][0]["passed"] is passed
    assert data["attempts"][0]["policy_sha256"]
    if boolean:
        assert "numeric comparison requires numeric values" in data["attempts"][0]["error"]
    assert all(file.read_bytes() == before for file, before in original.items())


def test_original_failed_execution_is_not_salvaged_from_partial_csv(tmp_path: Path) -> None:
    path = saved_suite(tmp_path, execution_failed=True)
    passed, report = reassess_local_model_suite(tmp_path, path)
    attempt = json.loads(report.read_text())["attempts"][0]
    assert not passed
    assert attempt["validation_status"] == "not_run"
    assert "not rerun" in attempt["reason"]


def test_modified_output_fails_hash_check(tmp_path: Path) -> None:
    path = saved_suite(tmp_path)
    (path.parent / "output" / "adjusted.csv").write_text("changed\n")
    passed, report = reassess_local_model_suite(tmp_path, path)
    assert not passed
    assert (
        "hash mismatch: output/adjusted.csv"
        in json.loads(report.read_text())["attempts"][0]["error"]
    )


@pytest.mark.parametrize("mutation", ["escape", "missing-hash", "identity"])
def test_unusable_saved_attempt_is_an_explicit_failure(tmp_path: Path, mutation: str) -> None:
    path = saved_suite(tmp_path)
    source = path.parent / "report.json"
    data = json.loads(source.read_text())
    if mutation == "escape":
        data["hashes"]["../outside.txt"] = "a" * 64
    elif mutation == "missing-hash":
        del data["hashes"]["output/adjusted.csv"]
    else:
        data["case"] = "double-score"
    source.write_text(json.dumps(data))
    passed, report = reassess_local_model_suite(tmp_path, path)
    assert not passed
    attempt = json.loads(report.read_text())["attempts"][0]
    assert attempt["validation_status"] == "failed"
    assert attempt["error"]


@pytest.mark.parametrize("mutation", ["incomplete", "duplicate", "missing"])
def test_invalid_suite_cannot_start(tmp_path: Path, mutation: str) -> None:
    path = saved_suite(tmp_path)
    data = json.loads(path.read_text())
    if mutation == "incomplete":
        data["complete"] = False
    elif mutation == "duplicate":
        data["attempts"].append(data["attempts"][0])
    else:
        data["cases"].append("double-score")
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        reassess_local_model_suite(tmp_path, path)


@pytest.mark.parametrize("passed,exit_code", [(True, 0), (False, 1)])
def test_cli_reassessment_outcome(
    monkeypatch: pytest.MonkeyPatch,
    passed: bool,
    exit_code: int,
) -> None:
    monkeypatch.setattr(cli, "reassess_local_model_suite", lambda *args: (passed, Path("new.json")))
    result = CliRunner().invoke(cli.app, ["reassess-local-model-suite", "old.json"])
    assert result.exit_code == exit_code
    assert "new.json" in result.stdout
