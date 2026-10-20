"""Check model output handling and synthetic validation without a live model."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from sasguard import cli
from sasguard.execution.result import ExecutionResult, ExecutionStatus
from sasguard.prototypes import local_model
from sasguard.prototypes.local_model_cases import CASES

CODE = "# Candidate must be saved exactly.\nprint('synthetic attempt')\n"
DEFAULT_CASE = CASES["double-score"]


@pytest.fixture
def fake_ollama(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    response = {
        "model": "qwen3:4b",
        "done": True,
        "done_reason": "stop",
        "message": {"content": json.dumps({"code": CODE})},
    }

    def request(endpoint: str, payload: object = None) -> object:
        if endpoint == "/api/tags":
            return {"models": [{"name": "qwen3:4b", "digest": "a" * 64}]}
        if endpoint == "/api/version":
            return {"version": "test-runtime"}
        if endpoint == "/api/ps":
            return {"models": []}
        if endpoint == "/api/show":
            return {}
        assert endpoint == "/api/chat"
        assert isinstance(payload, dict)
        assert payload["stream"] is False
        assert payload["think"] is False
        # Neither the CSV rows nor the hand-written oracle enter the request.
        contents = "\n".join(message["content"] for message in payload["messages"])
        for fixture in CASES.values():
            assert fixture.input_csv not in contents
            assert fixture.expected_csv not in contents
        return response

    monkeypatch.setattr(local_model, "_request_json", request)
    return response


def stub_runner(monkeypatch: pytest.MonkeyPatch, csv_text: str) -> list[dict[str, object]]:
    calls = []

    def run(self: object, **kwargs: object) -> ExecutionResult:
        calls.append(kwargs)
        output = kwargs["output_directory"]
        assert isinstance(output, Path)
        (output / "adjusted.csv").write_text(csv_text, encoding="utf-8")
        return ExecutionResult(
            execution_id=uuid4(),
            status=ExecutionStatus.SUCCEEDED,
            exit_code=0,
            runtime_seconds=0.5,
            output_files=["adjusted.csv"],
        )

    monkeypatch.setattr(local_model.DockerExecutionRunner, "run", run)
    return calls


def read_report(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_records_candidate_and_checks_synthetic_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_ollama: dict[str, object]
) -> None:
    calls = stub_runner(monkeypatch, DEFAULT_CASE.expected_csv)
    passed, path = local_model.run_local_model_smoke(tmp_path)
    report = read_report(path)
    assert passed
    assert report["generation_status"] == "succeeded"
    assert report["validation_status"] == "passed"
    assert report["human_review"] == "not_recorded"
    assert report["model_metadata"] == {"name": "qwen3:4b", "digest": "a" * 64, "definition": {}}
    assert (path.parent / "source" / "main.py").read_bytes() == CODE.encode()
    assert json.loads((path.parent / "response.json").read_text()) == fake_ollama
    assert calls[0]["forbidden_host_paths"] == (tmp_path / "data", path.parent / "expected")
    assert (path.parent / "expected") not in (
        calls[0]["source_directory"],
        calls[0]["input_directory"],
        calls[0]["output_directory"],
    )


@pytest.mark.parametrize(
    "actual",
    [
        DEFAULT_CASE.expected_csv.replace("000001,2.5,5", "000001,2.5,50"),
        DEFAULT_CASE.expected_csv.replace("000002,,", "000002,,0"),
        DEFAULT_CASE.expected_csv.replace("000001", "1"),
        DEFAULT_CASE.expected_csv.replace("NULL,0.25,0.5\n", ""),
    ],
    ids=["wrong-arithmetic", "lost-missingness", "lost-leading-zeros", "missing-row"],
)
@pytest.mark.parametrize("with_helpers", [False, True])
def test_successful_execution_does_not_hide_wrong_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: dict[str, object],
    actual: str,
    with_helpers: bool,
) -> None:
    stub_runner(monkeypatch, actual)
    passed, path = local_model.run_local_model_smoke(tmp_path, with_sas_helpers=with_helpers)
    report = read_report(path)
    assert not passed
    assert report["generation_status"] == "succeeded"
    assert report["validation_status"] == "failed"


@pytest.mark.parametrize("problem", ["truncated", "invalid-json", "syntax"])
def test_bad_generation_is_recorded_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: dict[str, object],
    problem: str,
) -> None:
    calls = stub_runner(monkeypatch, DEFAULT_CASE.expected_csv)
    if problem == "truncated":
        fake_ollama["done_reason"] = "length"
    else:
        fake_ollama["message"] = {
            "content": "not JSON" if problem == "invalid-json" else json.dumps({"code": "return 1"})
        }
    passed, path = local_model.run_local_model_smoke(tmp_path)
    report = read_report(path)
    assert not passed
    assert report["error"]
    assert report["generation_status"] == "failed"
    assert report["validation_status"] == "not_run"
    assert (path.parent / "response.json").exists()
    assert not calls
    if problem == "syntax":
        assert (path.parent / "source" / "main.py").read_bytes() == b"return 1"


def test_unavailable_model_leaves_report_without_downloading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_ollama: dict[str, object]
) -> None:
    calls = stub_runner(monkeypatch, DEFAULT_CASE.expected_csv)
    passed, path = local_model.run_local_model_smoke(tmp_path, model="not-installed:7b")
    assert not passed
    assert "not installed" in str(read_report(path)["error"])
    assert not calls


def test_runner_failure_keeps_validation_unrun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_ollama: dict[str, object]
) -> None:
    def run(self: object, **kwargs: object) -> ExecutionResult:
        return ExecutionResult(
            execution_id=uuid4(),
            status=ExecutionStatus.FAILED,
            exit_code=1,
            runtime_seconds=0.5,
            stderr="candidate could not read the declared input",
        )

    monkeypatch.setattr(local_model.DockerExecutionRunner, "run", run)
    passed, path = local_model.run_local_model_smoke(tmp_path)
    report = read_report(path)
    assert not passed
    assert report["generation_status"] == "succeeded"
    assert report["validation_status"] == "not_run"
    assert report["execution_result"]["status"] == "failed"


def test_missing_literal_identifiers_rejects_the_observed_model_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_ollama: dict[str, object]
) -> None:
    actual = DEFAULT_CASE.expected_csv.replace("NA,0,0", ",0,0").replace(
        "NULL,0.25,0.5", ",0.25,0.5"
    )
    stub_runner(monkeypatch, actual)
    passed, path = local_model.run_local_model_smoke(tmp_path)
    report = read_report(path)
    assert not passed
    assert report["error"] == "actual artifact has 2 rows with missing comparison keys"
    assert report["validation_status"] == "failed"
    assert report["hashes"]["output/adjusted.csv"]


@pytest.mark.parametrize("passed,exit_code", [(True, 0), (False, 1)])
def test_cli_reports_the_attempt_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, passed: bool, exit_code: int
) -> None:
    report = tmp_path / "report.json"
    monkeypatch.setattr(cli, "run_local_model_smoke", lambda *args, **kwargs: (passed, report))
    result = CliRunner().invoke(cli.app, ["local-model-smoke"])
    assert result.exit_code == exit_code
    assert str(report) in result.stdout


@pytest.mark.parametrize("case", list(CASES))
def test_cases_use_their_own_source_contract_and_comparison_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: dict[str, object],
    case: str,
) -> None:
    fixture = CASES[case]
    stub_runner(monkeypatch, fixture.expected_csv)
    passed, path = local_model.run_local_model_smoke(tmp_path, case=case)
    assert passed
    report = read_report(path)
    assert report["case"] == case
    assert report["prompt_version"] == fixture.prompt_version
    request = json.loads((path.parent / "request.json").read_text())
    assert fixture.sas_source in request["messages"][1]["content"]
    policy = json.loads((path.parent / "policy.json").read_text())
    assert policy["keys"] == [fixture.key]


@pytest.mark.parametrize(
    "case,old,new",
    [
        ("missing-comparison", "000002,,1", "000002,,0"),
        ("sum-missing", "NA,,,,", "NA,,,,0"),
        ("sum-missing", "000002,,3,,3", "000002,,3,3,3"),
        ("grouped-mean", "A,2,2", "A,3,2"),
        ("grouped-mean", "C,0,", "C,0,0"),
    ],
    ids=["missing-order", "all-missing-sum", "arithmetic-missing", "count-missing", "empty-mean"],
)
def test_rejects_incorrect_sas_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: dict[str, object],
    case: str,
    old: str,
    new: str,
) -> None:
    stub_runner(monkeypatch, CASES[case].expected_csv.replace(old, new))
    passed, path = local_model.run_local_model_smoke(tmp_path, case=case)
    assert not passed
    assert read_report(path)["validation_status"] == "failed"


def test_suite_preserves_a_failed_attempt_without_retrying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    unloaded = []

    def smoke(
        root: Path, *, model: str, image: str, case: str, with_sas_helpers: bool
    ) -> tuple[bool, Path]:
        assert not with_sas_helpers
        calls.append((model, case))
        return case != "sum-missing", root / "reports" / f"{model}-{case}.json"

    def request(endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        assert endpoint == "/api/generate"
        assert payload["keep_alive"] == 0
        unloaded.append(payload["model"])
        return {}

    monkeypatch.setattr(local_model, "run_local_model_smoke", smoke)
    monkeypatch.setattr(local_model, "_request_json", request)
    passed, path = local_model.run_local_model_suite(tmp_path, models=("first:4b", "second:9b"))
    report = read_report(path)
    assert not passed
    assert report["complete"] is True
    assert len(calls) == len(set(calls)) == 2 * len(CASES)
    assert unloaded == ["first:4b", "second:9b"]
    assert len(report["attempts"]) == 2 * len(CASES)


def test_unknown_case_stops_before_contacting_model(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown synthetic case"):
        local_model.run_local_model_smoke(tmp_path, case="typo")


def test_cloud_alias_is_rejected_before_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoints = []

    def request(endpoint: str, payload: object = None) -> object:
        endpoints.append(endpoint)
        if endpoint == "/api/tags":
            return {"models": [{"name": "qwen3:4b", "digest": "a" * 64}]}
        assert endpoint == "/api/show"
        return {"remote_host": "https://example.invalid", "remote_model": "hosted-model"}

    monkeypatch.setattr(local_model, "_request_json", request)
    passed, path = local_model.run_local_model_smoke(tmp_path)
    assert not passed
    assert "downloaded local model" in str(read_report(path)["error"])
    assert endpoints == ["/api/tags", "/api/show"]


@pytest.mark.parametrize("with_helpers", [False, True])
def test_helper_condition_is_opt_in_and_records_exact_staged_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: dict[str, object],
    with_helpers: bool,
) -> None:
    from sasguard.provenance.hashing import sha256_file

    calls = stub_runner(monkeypatch, DEFAULT_CASE.expected_csv)
    passed, path = local_model.run_local_model_smoke(tmp_path, with_sas_helpers=with_helpers)
    assert passed
    report = read_report(path)
    request = read_report(path.parent / "request.json")
    content = request["messages"][1]["content"]
    helper = path.parent / "source" / "sas_helpers.py"
    assert report["condition"] == (local_model.HELPER_VERSION if with_helpers else "direct")
    assert helper.exists() is with_helpers
    if with_helpers:
        assert content == DEFAULT_CASE.prompt + local_model.HELPER_GUIDANCE
        assert helper.read_bytes() == Path(local_model.compatibility.__file__).read_bytes()
        assert report["hashes"]["source/sas_helpers.py"] == sha256_file(helper)
        assert report["prompt_version"].endswith("+sas-helpers-v1")
        assert calls[0]["source_directory"] == helper.parent
    else:
        assert content == DEFAULT_CASE.prompt
        assert "source/sas_helpers.py" not in report["hashes"]


def test_suite_forwards_helper_condition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def smoke(root: Path, **kwargs: object) -> tuple[bool, Path]:
        calls.append(kwargs)
        return True, root / "reports" / "test.json"

    monkeypatch.setattr(local_model, "run_local_model_smoke", smoke)
    monkeypatch.setattr(local_model, "_request_json", lambda *args: {})
    passed, path = local_model.run_local_model_suite(
        tmp_path, models=("test:4b",), with_sas_helpers=True
    )
    assert passed
    assert len(calls) == len(CASES)
    assert all(call["with_sas_helpers"] is True for call in calls)
    assert read_report(path)["condition"] == "sas-helpers-v1"


@pytest.mark.parametrize("command", ["local-model-smoke", "local-model-suite"])
def test_cli_forwards_helper_flag(command: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def run(*args: object, **kwargs: object) -> tuple[bool, Path]:
        calls.append(kwargs)
        return True, Path("report.json")

    monkeypatch.setattr(cli, "run_local_model_smoke", run)
    monkeypatch.setattr(cli, "run_local_model_suite", run)
    assert CliRunner().invoke(cli.app, [command, "--with-sas-helpers"]).exit_code == 0
    assert calls[0]["with_sas_helpers"] is True
