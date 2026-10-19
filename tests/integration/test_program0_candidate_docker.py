"""Real Docker checks for the Program 0 candidate contract and reference isolation."""

import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from sasguard.execution import program0
from sasguard.execution.runner import RunnerLimits

pytestmark = pytest.mark.docker_integration


@pytest.fixture
def candidate_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    if os.environ.get("SASGUARD_RUN_DOCKER_TESTS") != "1" or shutil.which("docker") is None:
        pytest.skip("set SASGUARD_RUN_DOCKER_TESTS=1 with Docker available")
    root = tmp_path / "repo"
    input_path = root / program0.INPUT_PATH
    input_path.parent.mkdir(parents=True)
    input_path.write_text("PROVIDER_ID,SCORE\n000001,2\n", encoding="utf-8")
    sas = root / program0.PROGRAM_PATH
    sas.parent.mkdir(parents=True)
    sas.write_text("* test source;", encoding="utf-8")
    for directory in ("reference_python", "configs", "data/Project_1/SAS Output"):
        (root / directory).mkdir(parents=True, exist_ok=True)
        (root / directory / "secret.txt").write_text("not mounted", encoding="utf-8")
    monkeypatch.setattr(
        program0, "load_and_verify_integrity", lambda *args: SimpleNamespace(passed=True)
    )
    candidate = tmp_path / "candidate.py"
    return root, candidate


def test_candidate_sees_only_the_declared_contract(candidate_repository, monkeypatch) -> None:
    root, candidate = candidate_repository
    monkeypatch.setenv("SASGUARD_TEST_SECRET", "must-not-enter-container")
    candidate.write_text(
        """\
import json
import os
from pathlib import Path

inputs = Path(os.environ["SASGUARD_INPUT_DIR"])
output = Path(os.environ["SASGUARD_OUTPUT_DIR"])
assert sorted(p.name for p in inputs.iterdir()) == ["alldata_2025jul.csv", "contract.json"]
assert sorted(p.name for p in Path("/runner/source").iterdir()) == ["main.py"]
assert not Path("/workspace").exists()
assert not Path("/runner/data").exists()
assert not Path("/runner/reference_python").exists()
assert "SASGUARD_TEST_SECRET" not in os.environ
assert "OPENAI_API_KEY" not in os.environ
assert "ANTHROPIC_API_KEY" not in os.environ
contract = json.loads((inputs / "contract.json").read_text())
assert contract["identifier_column"] == "PROVIDER_ID"
for name in contract["output_filenames"]:
    (output / name).write_text("PROVIDER_ID,SCORE\\n000001,2\\n")
""",
        encoding="utf-8",
    )
    result, path = program0.run_program0_candidate(root, candidate, image="sasguard-runner:test")
    assert result.ready_for_validation
    assert result.validation_status == "not_run"
    assert len(result.artifacts) == 3
    assert result.execution_result.runtime_environment.image_id.startswith("sha256:")
    assert (path.parent / "manifest.json").exists()


@pytest.mark.parametrize(
    "code,status",
    [
        ("print('no outputs')", program0.CandidateStatus.MISSING_OUTPUTS),
        ("raise RuntimeError('candidate failed')", program0.CandidateStatus.EXECUTION_FAILED),
        ("import time; time.sleep(30)", program0.CandidateStatus.TIMED_OUT),
        (
            "import os; from pathlib import Path; "
            "Path(os.environ['SASGUARD_OUTPUT_DIR'], 'less100_measure.csv')"
            ".symlink_to('/etc/passwd')",
            program0.CandidateStatus.POLICY_VIOLATION,
        ),
    ],
    ids=["missing-output", "nonzero-exit", "timeout", "escaped-output"],
)
def test_real_failures_remain_distinct(candidate_repository, code, status) -> None:
    root, candidate = candidate_repository
    candidate.write_text(code, encoding="utf-8")
    result, _ = program0.run_program0_candidate(
        root, candidate, image="sasguard-runner:test", limits=RunnerLimits(timeout_seconds=1)
    )
    assert result.status is status
    assert result.validation_status == "not_run"
    assert not result.ready_for_validation


def test_malformed_real_output_fails_collection(candidate_repository) -> None:
    root, candidate = candidate_repository
    candidate.write_text(
        """\
import json
import os
from pathlib import Path
inputs = Path(os.environ['SASGUARD_INPUT_DIR'])
output = Path(os.environ['SASGUARD_OUTPUT_DIR'])
for name in json.loads((inputs / 'contract.json').read_text())['output_filenames']:
    (output / name).write_text('x,y\\n1,2,3\\n')
""",
        encoding="utf-8",
    )
    result, _ = program0.run_program0_candidate(root, candidate, image="sasguard-runner:test")
    assert result.status is program0.CandidateStatus.MALFORMED_OUTPUTS
    assert len(result.malformed_outputs) == 3


def test_internal_output_alias_is_rejected(candidate_repository) -> None:
    root, candidate = candidate_repository
    candidate.write_text(
        """\
import os
from pathlib import Path
output = Path(os.environ['SASGUARD_OUTPUT_DIR'])
(output / 'measure_average_stddev_2025jul.csv').write_text('x,y\\n1,2\\n')
(output / 'less100_measure.csv').symlink_to('measure_average_stddev_2025jul.csv')
""",
        encoding="utf-8",
    )
    result, _ = program0.run_program0_candidate(root, candidate, image="sasguard-runner:test")
    assert result.status is program0.CandidateStatus.POLICY_VIOLATION
    assert result.artifacts == {}
