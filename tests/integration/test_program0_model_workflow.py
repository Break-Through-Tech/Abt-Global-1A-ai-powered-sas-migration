"""Exercise controller plumbing with a fake API and real isolated Docker execution.

The supplied responses below are human-written controls, not model-quality evidence.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from sasguard.execution.program0 import CandidateInputFormat
from sasguard.prototypes import program0_model as controller
from sasguard.prototypes.program0_prompt import PromptInputFormat, preview_program0_prompt
from sasguard.reporting import write_run_report
from sasguard.reporting.models import ScopeStatus
from sasguard.reporting.reader import read_run_report

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.docker_integration
def test_fake_provider_repair_validates_and_reports_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("SASGUARD_RUN_DOCKER_TESTS") != "1" or shutil.which("docker") is None:
        pytest.skip("set SASGUARD_RUN_DOCKER_TESTS=1 with Docker available")
    image = os.environ.get("SASGUARD_TEST_RUNNER_IMAGE", "sasguard-runner:test")
    source = (ROOT / "src/sasguard/program0.py").read_text(encoding="utf-8")
    entry = """
import os
from pathlib import Path
inputs = Path(os.environ["SASGUARD_INPUT_DIR"])
output = Path(os.environ["SASGUARD_OUTPUT_DIR"])
frame = pd.read_csv(inputs / "alldata_2025jul.csv", converters={"PROVIDER_ID": str},
                    float_precision="round_trip")
result = translate_program0(frame)
{mutation}
for name, table in (
    ("less100_measure.csv", result.excluded_measures),
    ("measure_average_stddev_2025jul.csv", result.raw_statistics),
    ("std_data_2025jul_analysis.csv", result.analysis),
):
    table.to_csv(output / name, index=False, float_format="%.17g")
"""
    attempts = []
    codes = [
        source + entry.replace("{mutation}", 'result.analysis["std_MORT_30_AMI"] *= -1'),
        source + entry.replace("{mutation}", ""),
    ]

    def submit(body: bytes, key: str, timeout: float) -> tuple[int, bytes]:
        attempts.append(json.loads(body))
        code = codes[len(attempts) - 1]
        return 200, json.dumps(
            {
                "status": "completed",
                "model": "test-provider-replay",
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps({"code": code})}],
                    }
                ],
            }
        ).encode()

    monkeypatch.setenv("SASGUARD_API_KEY", "fake-api-key-for-controller-test")
    monkeypatch.setattr(controller, "_submit_request", submit)
    preview = preview_program0_prompt(ROOT, input_format=PromptInputFormat.SAS7BDAT)
    workflow, path = controller.run_program0_model(
        ROOT,
        preview,
        image=image,
        settings=controller.ModelSettings(model="test-provider-replay", repair_attempts=1),
    )
    assert workflow.status == "passed", workflow.model_dump_json(indent=2)
    assert workflow.input_format is CandidateInputFormat.SAS7BDAT
    assert len(attempts) == 2
    assert workflow.attempts[0].validation_status == "failed"
    assert workflow.attempts[1].validation_status == "passed"
    saved = read_run_report(ROOT, path.parent)
    assert saved.scope_status is ScopeStatus.VERIFIED, saved.evidence_issues
    assert saved.code_origin == "model_generated" and saved.model_name == "test-provider-replay"
    assert saved.repair_attempts == 1
    handoff = write_run_report(ROOT, path.parent)
    assert "model-generated" in (handoff / "handoff.md").read_text(encoding="utf-8")
    response_path = path.parent / "attempt-1/response.json"
    original = response_path.read_bytes()
    response_path.write_bytes(original + b" ")
    try:
        changed = read_run_report(ROOT, path.parent)
        assert changed.scope_status is ScopeStatus.NOT_VERIFIED
        assert changed.code_origin == "not_recorded"
    finally:
        response_path.write_bytes(original)
    diagnostic_path = path.parent / "attempt-0/repair-diagnostics.json"
    original_diagnostics = diagnostic_path.read_bytes()
    diagnostic_path.write_bytes(original_diagnostics + b" ")
    try:
        assert read_run_report(ROOT, path.parent).scope_status is ScopeStatus.NOT_VERIFIED
    finally:
        diagnostic_path.write_bytes(original_diagnostics)
