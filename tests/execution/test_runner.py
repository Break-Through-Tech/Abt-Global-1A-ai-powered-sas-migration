"""Unit tests for the host-side Docker runner controller."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from sasguard.execution.result import ExecutionStatus
from sasguard.execution.runner import DockerExecutionRunner, RunnerLimits

IMAGE_ID = "sha256:" + "a" * 64
PYTHON_METADATA = {
    "python_version": "3.11.9",
    "operating_system": "Linux",
    "architecture": "x86_64",
    "packages": {"numpy": "2.1.0"},
}


def image_inspection() -> str:
    return json.dumps([{"Id": IMAGE_ID, "RepoDigests": [], "Os": "linux", "Architecture": "amd64"}])


def test_runner_limits_are_bounded() -> None:
    limits = RunnerLimits()

    assert limits.timeout_seconds == 60
    assert limits.memory == "512m"
    assert limits.cpus == 1
    assert limits.pids == 64

    with pytest.raises(ValidationError):
        RunnerLimits(timeout_seconds=0)
    with pytest.raises(ValidationError):
        RunnerLimits(memory="unlimited")
    with pytest.raises(ValidationError):
        RunnerLimits(pids=1000)


def test_docker_command_contains_required_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "source"
    input_directory = tmp_path / "input"
    output = tmp_path / "output"
    for path in (source, input_directory, output):
        path.mkdir()

    runner = DockerExecutionRunner(image="runner:test")
    command = runner._docker_command(
        container_name="sasguard-runner-test",
        execution_id="12345678-1234-5678-1234-567812345678",
        source=source,
        input_directory=input_directory,
        output=output,
        script="main.py",
        image_id=IMAGE_ID,
    )
    rendered = " ".join(command)

    assert "--network none" in rendered
    assert "--pull never" in rendered
    assert IMAGE_ID in command
    assert "runner:test" not in command
    assert "--read-only" in command
    assert "--cap-drop ALL" in rendered
    assert "no-new-privileges:true" in command
    assert "--ipc none" in rendered
    assert "--pids-limit 64" in rendered
    assert "--memory 512m" in rendered
    assert "--cpus 1.0" in rendered
    assert "nofile=256:256" in command
    assert "dst=/runner/source,readonly" in rendered
    assert "dst=/runner/input,readonly" in rendered
    assert "dst=/runner/output" in rendered
    assert "--env" not in command
    assert "--env-file" not in command
    assert "--result" not in command
    assert "data/Project_1/SAS Output" not in rendered


def test_runner_uses_inspected_image_and_overrides_worker_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, input_directory, output = tmp_path / "source", tmp_path / "input", tmp_path / "output"
    source.mkdir()
    input_directory.mkdir()
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs) -> SimpleNamespace:
        calls.append(command)
        if command[1:3] == ["image", "inspect"]:
            return SimpleNamespace(stdout=image_inspection(), stderr="", returncode=0)
        if "--entrypoint" in command:
            assert IMAGE_ID in command
            assert command[command.index("--network") + 1] == "none"
            assert "--mount" not in command
            assert command[command.index("--entrypoint") + 1] == "python"
            return SimpleNamespace(stdout=json.dumps(PYTHON_METADATA), stderr="", returncode=0)
        execution_id = UUID(command[command.index("--execution-id") + 1])
        fabricated = {
            "requested_image": "attacker/image:latest",
            "image_id": "sha256:" + "f" * 64,
            "repo_digests": [],
            "operating_system": "FakeOS",
            "architecture": "fake-arch",
            "python": PYTHON_METADATA,
        }
        result = {
            "execution_id": str(execution_id),
            "status": "succeeded",
            "exit_code": 0,
            "runtime_seconds": 0.1,
            "runtime_environment": fabricated,
        }
        return SimpleNamespace(stdout=json.dumps(result), stderr="", returncode=0)

    monkeypatch.setattr("sasguard.execution.runner.subprocess.run", fake_run)
    result = DockerExecutionRunner(image="runner:test").run(
        source_directory=source,
        input_directory=input_directory,
        output_directory=output,
    )

    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.runtime_environment.image_id == IMAGE_ID
    assert result.runtime_environment.requested_image == "runner:test"
    assert result.runtime_environment.operating_system == "linux"
    assert len(calls) == 3
    assert calls[0][1:4] == ["image", "inspect", "--"]
    assert calls[1][1] == "run" and calls[2][1] == "run"
    assert calls[1][calls[1].index("--entrypoint") + 1] == "python"
    assert calls[2][calls[2].index("--script") - 1] == IMAGE_ID
    assert calls[2][calls[2].index("--pull") + 1] == "never"
    assert "attacker/image:latest" not in calls[2]


@pytest.mark.parametrize("failed_at", ["inspect", "probe", "invalid_probe"])
def test_preflight_failures_do_not_launch_generated_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_at: str,
) -> None:
    source, input_directory, output = tmp_path / "source", tmp_path / "input", tmp_path / "output"
    source.mkdir()
    input_directory.mkdir()
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs) -> SimpleNamespace:
        calls.append(command)
        if command[1:3] == ["image", "inspect"]:
            if failed_at == "inspect":
                raise subprocess.CalledProcessError(1, command, stderr="missing image")
            return SimpleNamespace(stdout=image_inspection(), stderr="", returncode=0)
        if "--entrypoint" in command:
            if failed_at == "probe":
                raise subprocess.CalledProcessError(2, command, stderr="probe failed")
            return SimpleNamespace(stdout="not-json", stderr="", returncode=0)
        pytest.fail("generated code launched after environment preflight failed")

    monkeypatch.setattr("sasguard.execution.runner.subprocess.run", fake_run)
    result = DockerExecutionRunner(image="runner:test").run(
        source_directory=source,
        input_directory=input_directory,
        output_directory=output,
    )

    assert result.status is ExecutionStatus.RUNNER_ERROR
    assert result.runtime_environment is None
    assert all("--mount" not in command for command in calls)
    assert len(calls) == (1 if failed_at == "inspect" else 2)


@pytest.mark.parametrize(
    "inspection",
    [
        "not-json",
        "{}",
        "[]",
        json.dumps(
            [{"Id": "sha256:short", "RepoDigests": [], "Os": "linux", "Architecture": "amd64"}]
        ),
        json.dumps([{"Id": IMAGE_ID, "RepoDigests": [], "Architecture": "amd64"}]),
    ],
)
def test_invalid_image_inspection_stops_before_generated_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    inspection: str,
) -> None:
    source, input_directory, output = tmp_path / "source", tmp_path / "input", tmp_path / "output"
    source.mkdir()
    input_directory.mkdir()
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(stdout=inspection, stderr="", returncode=0)

    monkeypatch.setattr("sasguard.execution.runner.subprocess.run", fake_run)
    result = DockerExecutionRunner(image="runner:test").run(
        source_directory=source,
        input_directory=input_directory,
        output_directory=output,
    )

    assert result.status is ExecutionStatus.RUNNER_ERROR
    assert result.runtime_environment is None
    assert len(calls) == 1
    assert all("--mount" not in command for command in calls)
    assert calls[0][1:3] == ["image", "inspect"]


def test_inspection_oserror_returns_runner_error_without_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, input_directory, output = tmp_path / "source", tmp_path / "input", tmp_path / "output"
    source.mkdir()
    input_directory.mkdir()

    def fake_run(command: list[str], **kwargs) -> SimpleNamespace:
        raise OSError("docker executable unavailable")

    monkeypatch.setattr("sasguard.execution.runner.subprocess.run", fake_run)
    result = DockerExecutionRunner(image="runner:test").run(
        source_directory=source,
        input_directory=input_directory,
        output_directory=output,
    )

    assert result.status is ExecutionStatus.RUNNER_ERROR
    assert result.runtime_environment is None
    assert "preflight failed" in result.stderr


def test_probe_timeout_removes_probe_container_before_returning_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, input_directory, output = tmp_path / "source", tmp_path / "input", tmp_path / "output"
    source.mkdir()
    input_directory.mkdir()
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs) -> SimpleNamespace:
        calls.append(command)
        if command[1:3] == ["image", "inspect"]:
            return SimpleNamespace(stdout=image_inspection(), stderr="", returncode=0)
        if command[1] == "run":
            raise subprocess.TimeoutExpired(command, timeout=30)
        assert command[1:3] == ["rm", "--force"]
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr("sasguard.execution.runner.subprocess.run", fake_run)
    result = DockerExecutionRunner(image="runner:test").run(
        source_directory=source,
        input_directory=input_directory,
        output_directory=output,
    )

    assert result.status is ExecutionStatus.RUNNER_ERROR
    assert result.runtime_environment is None
    assert len(calls) == 3
    assert calls[2][3] == calls[1][calls[1].index("--name") + 1]


@pytest.mark.parametrize("outcome", ["timeout", "docker_failure", "invalid_result", "oserror"])
def test_docker_execution_failures_keep_inspected_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    source, input_directory, output = tmp_path / "source", tmp_path / "input", tmp_path / "output"
    source.mkdir()
    input_directory.mkdir()
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs) -> SimpleNamespace:
        calls.append(command)
        if command[1:3] == ["image", "inspect"]:
            return SimpleNamespace(stdout=image_inspection(), stderr="", returncode=0)
        if "--entrypoint" in command:
            return SimpleNamespace(stdout=json.dumps(PYTHON_METADATA), stderr="", returncode=0)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(
                command, timeout=17, output=b"partial out", stderr=b"partial err"
            )
        if outcome == "oserror":
            raise OSError("Docker daemon unavailable")
        if outcome == "docker_failure":
            return SimpleNamespace(stdout="", stderr="container could not start", returncode=125)
        return SimpleNamespace(stdout="not-json", stderr="", returncode=0)

    monkeypatch.setattr("sasguard.execution.runner.subprocess.run", fake_run)
    result = DockerExecutionRunner(image="runner:test").run(
        source_directory=source,
        input_directory=input_directory,
        output_directory=output,
    )

    assert result.runtime_environment is not None
    assert result.runtime_environment.image_id == IMAGE_ID
    assert result.status is (
        ExecutionStatus.TIMED_OUT if outcome == "timeout" else ExecutionStatus.RUNNER_ERROR
    )
    if outcome == "timeout":
        assert result.stdout == "partial out"
        assert result.stderr == "partial err"
        assert calls[-1][1:3] == ["rm", "--force"]
    elif outcome == "docker_failure":
        assert result.stderr == "container could not start"
    elif outcome == "oserror":
        assert "Docker execution could not start" in result.stderr
    else:
        assert "invalid execution result" in result.stderr


def test_runner_rejects_overlapping_directories(tmp_path: Path) -> None:
    source = tmp_path / "source"
    input_directory = tmp_path / "input"
    source.mkdir()
    input_directory.mkdir()

    runner = DockerExecutionRunner()
    with pytest.raises(ValueError, match="must not overlap"):
        runner.run(
            source_directory=source,
            input_directory=input_directory,
            output_directory=source / "output",
        )


@pytest.mark.parametrize("mount", ["source", "input", "output"])
def test_runner_rejects_forbidden_mounts(tmp_path: Path, mount: str) -> None:
    source = tmp_path / "source"
    input_directory = tmp_path / "input"
    output = tmp_path / "output"
    golden = tmp_path / "golden"
    for path in (source, input_directory, golden):
        path.mkdir()

    selected = {"source": source, "input": input_directory, "output": output}
    selected[mount] = golden

    runner = DockerExecutionRunner()
    with pytest.raises(ValueError, match="forbidden host path"):
        runner.run(
            source_directory=selected["source"],
            input_directory=selected["input"],
            output_directory=selected["output"],
            forbidden_host_paths=(golden,),
        )


@pytest.mark.parametrize("script", ["../main.py", "/main.py", "main.txt", ""])
def test_runner_rejects_unsafe_script_paths(tmp_path: Path, script: str) -> None:
    source = tmp_path / "source"
    input_directory = tmp_path / "input"
    source.mkdir()
    input_directory.mkdir()

    with pytest.raises(ValueError, match="relative Python path"):
        DockerExecutionRunner().run(
            source_directory=source,
            input_directory=input_directory,
            output_directory=tmp_path / "output",
            script=script,
        )
