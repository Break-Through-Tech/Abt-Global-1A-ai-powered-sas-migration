"""Real Docker protocol check with a fake provider; not model-quality evidence."""

import json
import os
import shutil
from pathlib import Path

import pyreadstat
import pytest

from sasguard.config import load_project_configuration
from sasguard.prototypes import program2_model as controller
from sasguard.prototypes.program0_model import ModelSettings
from sasguard.verification.program2 import ARTIFACTS

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.docker_integration
def test_fake_program2_provider_runs_without_gold_mounts_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("SASGUARD_RUN_DOCKER_TESTS") != "1" or shutil.which("docker") is None:
        pytest.skip("set SASGUARD_RUN_DOCKER_TESTS=1 with Docker available")
    paths = load_project_configuration(
        ROOT / "configs/cms_2025jul.yaml", project_root=ROOT
    ).resolve_paths(ROOT)
    headers = {}
    for filename, name in ARTIFACTS.items():
        _, meta = pyreadstat.read_sas7bdat(paths.reference_sas7bdat[name], metadataonly=True)
        headers[filename] = meta.column_names
    # Human-authored empty/zero controls prove rejection. No gold row values enter the code.
    code = """
import csv
import os
from pathlib import Path
output = Path(os.environ["SASGUARD_OUTPUT_DIR"])
headers = HEADERS
for name, columns in headers.items():
    with (output / name).open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        if name.startswith("national"):
            writer.writerow([0] * len(columns))
""".replace("HEADERS", repr(headers))
    calls = []

    def submit(body: bytes, key: str, timeout: float) -> tuple[int, bytes]:
        assert key.encode() not in body
        calls.append(json.loads(body))
        return 200, json.dumps(
            {
                "status": "completed",
                "model": "test-program2-protocol",
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps({"code": code})}],
                    }
                ],
            }
        ).encode()

    monkeypatch.setenv("SASGUARD_API_KEY", "fake-credential-for-program2-protocol")
    monkeypatch.setattr(controller, "_submit_request", submit)
    record, path = controller.run_program2_model(
        ROOT,
        upstream_chain=None,
        image=os.environ.get("SASGUARD_TEST_RUNNER_IMAGE", "sasguard-runner:test"),
        settings=ModelSettings(model="test-program2-protocol", repair_attempts=0),
    )
    assert record.status == "failed", record.model_dump_json(indent=2)
    assert len(calls) == 1 and record.attempts[0].execution_status == "succeeded"
    assert record.attempts[0].validation_status != "passed"
    assert {path.name for path in (path.parent / "input").iterdir()} == {
        f"{name.lower()}.csv" for name in controller.INPUTS
    }
    assert not (path.parent / "input/star_2025jul.csv").exists()
    assert not (path.parent / "input/national_average_2025jul.csv").exists()
    request = json.loads((path.parent / "attempt-0/request.json").read_bytes())
    assert request["store"] is False and request["model"] == "test-program2-protocol"
