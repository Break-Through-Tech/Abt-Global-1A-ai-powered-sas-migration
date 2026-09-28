"""Unit tests for the host-side Docker runner controller."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from sasguard.execution.runner import DockerExecutionRunner, RunnerLimits


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
    )
    rendered = " ".join(command)

    assert "--network none" in rendered
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
