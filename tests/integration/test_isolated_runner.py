"""Docker integration tests for isolated generated-code execution."""

import os
import shutil
from pathlib import Path

import pytest

from sasguard.execution.result import ExecutionStatus
from sasguard.execution.runner import DockerExecutionRunner, RunnerLimits

pytestmark = pytest.mark.docker_integration


def require_docker_tests() -> None:
    """Skip unless the explicit integration-test switch and Docker are available."""
    if os.environ.get("SASGUARD_RUN_DOCKER_TESTS") != "1":
        pytest.skip("set SASGUARD_RUN_DOCKER_TESTS=1 to run Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is unavailable")


@pytest.fixture(autouse=True)
def docker_required() -> None:
    require_docker_tests()


@pytest.fixture
def runner() -> DockerExecutionRunner:
    return DockerExecutionRunner(
        image="sasguard-runner:test",
        limits=RunnerLimits(timeout_seconds=2, memory="256m", cpus=0.5, pids=32),
    )


def directories(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    source = tmp_path / "source"
    input_directory = tmp_path / "input"
    output = tmp_path / "output"
    golden = tmp_path / "golden"
    for path in (source, input_directory, output, golden):
        path.mkdir()
    return source, input_directory, output, golden


def test_success_has_no_network_gold_or_host_write_access(
    tmp_path: Path, runner: DockerExecutionRunner
) -> None:
    source, input_directory, output, golden = directories(tmp_path)
    (input_directory / "value.txt").write_text("trusted input\n", encoding="utf-8")
    (golden / "STAR_2025JUL.csv").write_text("not mounted\n", encoding="utf-8")
    (source / "main.py").write_text(
        """\
import os
import socket
from pathlib import Path

source = Path(__file__).parent
input_dir = Path(os.environ["SASGUARD_INPUT_DIR"])
output_dir = Path(os.environ["SASGUARD_OUTPUT_DIR"])

assert not Path("/runner/gold").exists()
assert "SECRET_TEST_VALUE" not in os.environ

for protected in (source / "new.py", input_dir / "changed.txt", Path("/blocked.txt")):
    try:
        protected.write_text("blocked", encoding="utf-8")
    except OSError:
        pass
    else:
        raise AssertionError(f"write unexpectedly succeeded: {protected}")

sock = socket.socket()
sock.settimeout(0.5)
try:
    sock.connect(("1.1.1.1", 53))
except OSError:
    pass
else:
    raise AssertionError("network connection unexpectedly succeeded")
finally:
    sock.close()

value = (input_dir / "value.txt").read_text(encoding="utf-8")
(output_dir / "result.txt").write_text(value, encoding="utf-8")
print("complete")
""",
        encoding="utf-8",
    )

    os.environ["SECRET_TEST_VALUE"] = "must-not-enter-container"
    try:
        result = runner.run(
            source_directory=source,
            input_directory=input_directory,
            output_directory=output,
            forbidden_host_paths=(golden,),
        )
    finally:
        os.environ.pop("SECRET_TEST_VALUE", None)

    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.exit_code == 0
    assert result.stdout == "complete\n"
    assert result.output_files == ["result.txt"]
    assert (output / "result.txt").read_text(encoding="utf-8") == "trusted input\n"
    assert not list(output.glob("execution-*.json"))
    assert not (source / "new.py").exists()
    assert not (input_directory / "changed.txt").exists()


def test_failure_is_captured(tmp_path: Path, runner: DockerExecutionRunner) -> None:
    source, input_directory, output, golden = directories(tmp_path)
    (source / "main.py").write_text(
        "import sys\nprint('failed output')\nprint('details', file=sys.stderr)\nsys.exit(7)\n",
        encoding="utf-8",
    )

    result = runner.run(
        source_directory=source,
        input_directory=input_directory,
        output_directory=output,
        forbidden_host_paths=(golden,),
    )

    assert result.status is ExecutionStatus.FAILED
    assert result.exit_code == 7
    assert result.stdout == "failed output\n"
    assert result.stderr == "details\n"


def test_timeout_terminates_and_is_reported(tmp_path: Path) -> None:
    source, input_directory, output, golden = directories(tmp_path)
    (source / "main.py").write_text(
        "import time\ntime.sleep(30)\n",
        encoding="utf-8",
    )
    runner = DockerExecutionRunner(
        image="sasguard-runner:test",
        limits=RunnerLimits(timeout_seconds=0.25, memory="256m", cpus=0.5, pids=32),
    )

    result = runner.run(
        source_directory=source,
        input_directory=input_directory,
        output_directory=output,
        forbidden_host_paths=(golden,),
    )

    assert result.status is ExecutionStatus.TIMED_OUT
    assert result.exit_code is None
    assert result.runtime_seconds < 5


def test_escaping_output_symlink_is_a_policy_violation(
    tmp_path: Path, runner: DockerExecutionRunner
) -> None:
    source, input_directory, output, golden = directories(tmp_path)
    (input_directory / "value.txt").write_text("input\n", encoding="utf-8")
    (source / "main.py").write_text(
        """\
import os
from pathlib import Path

output = Path(os.environ["SASGUARD_OUTPUT_DIR"])
(output / "escape").symlink_to("/runner/input/value.txt")
""",
        encoding="utf-8",
    )

    result = runner.run(
        source_directory=source,
        input_directory=input_directory,
        output_directory=output,
        forbidden_host_paths=(golden,),
    )

    assert result.status is ExecutionStatus.POLICY_VIOLATION
    assert result.policy_violations == ["output symlink escapes allowed directory: escape"]
