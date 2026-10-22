"""Real Docker checks for the Program 0 candidate contract and reference isolation."""

import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

from sasguard.execution import program0
from sasguard.execution.manifest import RunManifest
from sasguard.execution.runner import RunnerLimits
from sasguard.provenance.hashing import sha256_file
from sasguard.verification.artifact import ArtifactComparison, ReferenceSource

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
    validator_calls = []

    def forbidden(*args):
        validator_calls.append(args)
        raise AssertionError("failed execution or collection must not reach validation")

    result, _ = program0.run_program0_candidate(
        root,
        candidate,
        image="sasguard-runner:test",
        limits=RunnerLimits(timeout_seconds=1),
        validator=forbidden,
    )
    assert result.status is status
    assert result.validation_status == "not_run"
    assert not result.ready_for_validation
    assert validator_calls == []


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


@pytest.mark.parametrize(
    "validation_status",
    [
        "passed",
        "failed",
        "hash_mismatch",
        "missing_outputs",
        "malformed_outputs",
        "validator_error",
    ],
)
def test_real_docker_handoff_records_stub_validator_results(
    candidate_repository, validation_status: str
) -> None:
    """Test host plumbing only. The stub's comparisons are not real SAS validation."""
    root, candidate = candidate_repository
    candidate.write_text(
        """\
import json
import os
from pathlib import Path
inputs = Path(os.environ['SASGUARD_INPUT_DIR'])
output = Path(os.environ['SASGUARD_OUTPUT_DIR'])
for name in json.loads((inputs / 'contract.json').read_text())['output_filenames']:
    (output / name).write_text('VALUE\\n1\\n')
""",
        encoding="utf-8",
    )
    calls = []
    snapshots = {}

    def validator(
        project_root: Path, output_directory: Path, expected_sha256: Mapping[str, str]
    ) -> program0.CandidateValidationResult:
        assert project_root == root.resolve()
        assert set(expected_sha256) == set(program0.OUTPUT_FILENAMES)
        for name, digest in expected_sha256.items():
            assert sha256_file(output_directory / name) == digest
            snapshots[name] = (output_directory / name).read_bytes()
        manifest_path = output_directory.parent / "manifest.json"
        snapshots["manifest.json"] = manifest_path.read_bytes()
        manifest = RunManifest.model_validate_json(snapshots["manifest.json"])
        assert manifest.execution_result.passed
        assert manifest.execution_result.runtime_environment.image_id.startswith("sha256:")
        assert manifest.artifact_results == {}
        calls.append((project_root, output_directory, dict(expected_sha256)))
        if validation_status == "validator_error":
            raise RuntimeError("test validator unavailable")
        comparisons = {}
        if validation_status in ("passed", "failed"):
            comparisons = {
                name: ArtifactComparison(
                    artifact=Path(name).stem.upper(),
                    passed=validation_status == "passed",
                    reference_source=ReferenceSource.SAS7BDAT,
                    expected_rows=1,
                    actual_rows=1,
                    expected_columns=["VALUE"],
                    actual_columns=["VALUE"],
                    mismatched_cells=0 if validation_status == "passed" else 1,
                )
                for name in expected_sha256
            }
        return program0.CandidateValidationResult.model_validate(
            {"status": validation_status, "artifact_results": comparisons}
        )

    result, report_path = program0.run_program0_candidate(
        root, candidate, image="sasguard-runner:test", validator=validator
    )
    assert len(calls) == 1
    assert result.execution_result.passed
    assert result.status is program0.CandidateStatus.READY
    assert result.validation_status == validation_status
    assert result.human_review == "not_recorded"
    assert program0.CandidateReport.model_validate_json(report_path.read_bytes()) == result
    for name, content in snapshots.items():
        path = (
            report_path.parent / name
            if name == "manifest.json"
            else report_path.parent / "output" / name
        )
        assert path.read_bytes() == content
