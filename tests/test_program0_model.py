"""Model failures, repair boundaries, gold isolation, and saved generation provenance."""

import json
import shutil
from pathlib import Path

import pytest
from test_program0_prompt import GOLD_SECRET, PYTHON_SECRET, ROW_SECRET
from test_program0_prompt import project as project
from test_reporting import SECRET, comparison, execution
from typer.testing import CliRunner

from sasguard import cli
from sasguard.execution.program0 import (
    OUTPUT_FILENAMES,
    VALIDATION_SOURCE_PATHS,
    CandidateReport,
    CandidateStatus,
)
from sasguard.prototypes import program0_model as controller
from sasguard.prototypes.program0_prompt import preview_program0_prompt
from sasguard.provenance.hashing import sha256_file
from sasguard.verification.artifact import ReferenceSource

REPO = Path(__file__).resolve().parents[1]
KEY = "test-key-never-persist-this-384923"


@pytest.fixture
def model_project(project: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    for relative in (
        *VALIDATION_SOURCE_PATHS,
        "src/sasguard/execution/program0.py",
        "src/sasguard/prototypes/program0_prompt.py",
        "src/sasguard/prototypes/program0_model.py",
        "src/sasguard/prototypes/local_model.py",
    ):
        target = project / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / relative, target)
    monkeypatch.setenv("SASGUARD_API_KEY", KEY)
    preview = preview_program0_prompt(project)
    return project, preview


def response(code: str = "print('generated')\n", **changes: object) -> bytes:
    value = {
        "status": "completed",
        "model": "gpt-6-luna",
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps({"code": code})}],
            }
        ],
    }
    return json.dumps(value | changes).encode()


def result(passed: bool = True) -> CandidateReport:
    return CandidateReport(
        status=CandidateStatus.READY,
        execution_result=execution(),
        validation_status="passed" if passed else "failed",
        validation_results={
            name: comparison(
                artifact=Path(name).stem.upper(),
                passed=passed,
                source=ReferenceSource.SAS7BDAT,
                columns=["PROVIDER_ID", "SCORE"],
            )
            for name in OUTPUT_FILENAMES
        },
    )


def fake_runner(monkeypatch: pytest.MonkeyPatch, reports: list[CandidateReport]) -> list[bytes]:
    candidates = []

    def run(root: Path, candidate: Path, **kwargs: object) -> tuple[CandidateReport, Path]:
        assert kwargs["validator"] is controller.validate_collected_program0
        candidates.append(candidate.read_bytes())
        report = reports[min(len(candidates) - 1, len(reports) - 1)]
        path = root / "reports/runs" / f"fake-execution-{len(candidates)}" / "report.json"
        path.parent.mkdir()
        path.write_text(report.model_dump_json(), encoding="utf-8")
        return report, path

    monkeypatch.setattr(controller, "run_program0_candidate", run)
    return candidates


def test_direct_success_preserves_code_and_never_sends_gold(
    model_project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, preview = model_project
    requests = []

    def submit(body: bytes, key: str, timeout: float) -> tuple[int, bytes]:
        assert key == KEY and timeout == 180
        requests.append(json.loads(body))
        for secret in (ROW_SECRET, GOLD_SECRET, PYTHON_SECRET, SECRET, KEY):
            assert secret.encode() not in body
        return 200, response()

    monkeypatch.setattr(controller, "_submit_request", submit)
    candidates = fake_runner(monkeypatch, [result()])
    workflow, path = controller.run_program0_model(root, preview, image="test-image")
    assert workflow.status == "passed" and len(requests) == 1
    assert candidates == [b"print('generated')\n"]
    assert requests[0]["store"] is False
    assert requests[0]["text"]["format"]["strict"] is True
    assert workflow.attempts[0].usage == {"input_tokens": 100, "output_tokens": 20}
    assert workflow.estimated_cost_usd is None
    assert workflow.human_review == "not_recorded" and not workflow.full_pipeline_verified
    for saved in path.parent.rglob("*"):
        if saved.is_file():
            assert KEY.encode() not in saved.read_bytes()
    assert json.loads((preview / "preview.json").read_bytes())["generation_status"] == "not_run"


def test_automatic_repair_sends_only_aggregate_diagnostics_and_links_parent(
    model_project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, preview = model_project
    requests = []

    def submit(body: bytes, *_: object) -> tuple[int, bytes]:
        assert SECRET.encode() not in body
        requests.append(json.loads(body))
        return 200, response(f"print('attempt {len(requests)}')\n")

    monkeypatch.setattr(controller, "_submit_request", submit)
    fake_runner(monkeypatch, [result(False), result()])
    workflow, path = controller.run_program0_model(
        root, preview, image="test-image", settings=controller.ModelSettings(repair_attempts=2)
    )
    assert workflow.status == "passed" and len(requests) == 2
    assert len(requests[1]["input"]) == 4
    feedback = requests[1]["input"][-1]["content"]
    assert "automatic_aggregate_diagnostics" in feedback and '"missing_key_count": 1' in feedback
    assert "float_precision" not in feedback  # No manually added repair hints.
    first = path.parent / "attempt-0/attempt.json"
    assert workflow.attempts[1].parent_attempt_sha256 == sha256_file(first, normalize_text=False)
    assert workflow.attempts[0].validation_status == "failed"
    assert (path.parent / "attempt-0/candidate.py").read_bytes() == b"print('attempt 1')\n"


def test_failed_repairs_stop_at_limit(
    model_project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, preview = model_project
    calls = []
    monkeypatch.setattr(
        controller, "_submit_request", lambda *args: (calls.append(1) or 200, response())
    )
    fake_runner(monkeypatch, [result(False)])
    workflow, _ = controller.run_program0_model(
        root, preview, image="test", settings=controller.ModelSettings(repair_attempts=2)
    )
    assert workflow.status == "failed" and len(calls) == 3


@pytest.mark.parametrize("state", ["validator_error", "runner_error", "hash_mismatch"])
def test_infrastructure_failures_never_trigger_model_repair(
    model_project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    root, preview = model_project
    failed = (
        CandidateReport(status=CandidateStatus.RUNNER_ERROR, error=SECRET)
        if state == "runner_error"
        else CandidateReport(
            status=CandidateStatus.READY,
            execution_result=execution(),
            validation_status=state,
            validation_error=SECRET if state == "validator_error" else None,
            validation_errors={OUTPUT_FILENAMES[0]: SECRET} if state == "hash_mismatch" else {},
        )
    )
    calls = []
    monkeypatch.setattr(
        controller, "_submit_request", lambda *args: (calls.append(1) or 200, response())
    )
    fake_runner(monkeypatch, [failed])
    workflow, _ = controller.run_program0_model(
        root, preview, image="test", settings=controller.ModelSettings(repair_attempts=2)
    )
    assert workflow.status == "failed" and len(calls) == 1


@pytest.mark.parametrize("fault", ["http", "incomplete", "model", "schema", "secret", "network"])
def test_generation_failure_does_not_run_candidate_or_retry(
    model_project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    root, preview = model_project
    calls = []

    def submit(*args: object) -> tuple[int, bytes]:
        calls.append(1)
        if fault == "network":
            raise OSError("Authorization: Bearer " + KEY)
        return {
            "http": (429, b'{"error":{"code":"rate_limit"}}'),
            "incomplete": (200, response(status="incomplete")),
            "model": (200, response(model="unexpected")),
            "schema": (200, response(output=[])),
            "secret": (200, response(code=KEY)),
        }[fault]

    monkeypatch.setattr(controller, "_submit_request", submit)
    candidates = fake_runner(monkeypatch, [result()])
    workflow, path = controller.run_program0_model(root, preview, image="test")
    assert workflow.status == "error" and workflow.attempts[0].generation_status == "failed"
    assert len(calls) == 1 and not candidates
    for saved in path.parent.rglob("*"):
        if saved.is_file():
            assert KEY.encode() not in saved.read_bytes()


@pytest.mark.parametrize("changed", ["source", "policy", "preview", "controller"])
def test_changed_evidence_stops_before_execution(
    model_project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    root, preview = model_project
    candidates = fake_runner(monkeypatch, [result()])

    def submit(*args: object) -> tuple[int, bytes]:
        if changed == "source":
            target = root / next(
                iter(json.loads((preview / "preview.json").read_bytes())["source_hashes_lf"])
            )
        elif changed == "policy":
            target = root / VALIDATION_SOURCE_PATHS[0]
        elif changed == "preview":
            target = preview / "messages.json"
        else:
            target = root / "src/sasguard/prototypes/program0_model.py"
        target.write_text("changed", encoding="utf-8")
        return 200, response()

    monkeypatch.setattr(controller, "_submit_request", submit)
    workflow, _ = controller.run_program0_model(root, preview, image="test")
    assert workflow.status == "error" and not candidates


def test_missing_key_and_changed_preview_never_submit(
    model_project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, preview = model_project

    def forbidden(*args: object) -> None:
        raise AssertionError("API must not be called")

    monkeypatch.setattr(controller, "_submit_request", forbidden)
    monkeypatch.delenv("SASGUARD_API_KEY")
    with pytest.raises(ValueError, match="SASGUARD_API_KEY"):
        controller.run_program0_model(root, preview, image="test")
    monkeypatch.setenv("SASGUARD_API_KEY", KEY)
    (preview / "prompt.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Prompt preview changed"):
        controller.run_program0_model(root, preview, image="test")


def test_cli_returns_failure_with_separate_statuses(
    model_project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, preview = model_project
    monkeypatch.setattr(controller, "_submit_request", lambda *args: (200, response()))
    fake_runner(monkeypatch, [result(False)])
    response_cli = CliRunner().invoke(
        cli.app, ["model-program0", str(preview), "--project-root", str(root), "--image", "test"]
    )
    assert response_cli.exit_code == 1
    assert "generation completed, execution succeeded, SAS comparison failed" in response_cli.output
    assert "Full pipeline and CMS ratings are not verified" in response_cli.output
    assert KEY not in response_cli.output
