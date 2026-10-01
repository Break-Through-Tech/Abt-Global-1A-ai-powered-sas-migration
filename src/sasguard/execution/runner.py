"""Host-side Docker controller for isolated generated-code execution."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from sasguard.execution.result import ExecutionResult, ExecutionStatus


class RunnerLimits(BaseModel):
    """Resource boundaries applied to one generated-code container."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_seconds: float = Field(default=60, gt=0, le=600)
    memory: str = Field(default="512m", pattern=r"^[1-9][0-9]*[mMgG]$")
    cpus: float = Field(default=1.0, gt=0, le=4)
    pids: int = Field(default=64, ge=16, le=256)


def _relative_python_script(value: str) -> str:
    candidate = value.replace("\\", "/").strip()
    path = PurePosixPath(candidate)
    if (
        not candidate
        or path.is_absolute()
        or path == PurePosixPath(".")
        or ".." in path.parts
        or not candidate.lower().endswith(".py")
    ):
        raise ValueError("script must be a relative Python path")
    return path.as_posix()


def _require_directory(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"{label} directory does not exist: {resolved}")
    return resolved


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _timeout_output(value: bytes | str | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


class DockerExecutionRunner:
    """Launch generated Python with explicit Docker mounts and restrictions."""

    def __init__(
        self,
        *,
        image: str = "sasguard-runner:local",
        docker_executable: str = "docker",
        limits: RunnerLimits | None = None,
    ) -> None:
        self.image = image
        self.docker_executable = docker_executable
        self.limits = limits or RunnerLimits()

    def run(
        self,
        *,
        source_directory: Path,
        input_directory: Path,
        output_directory: Path,
        script: str = "main.py",
        forbidden_host_paths: tuple[Path, ...] = (),
    ) -> ExecutionResult:
        """Run one generated entry point and return its structured result."""
        execution_id = uuid4()
        script = _relative_python_script(script)
        source = _require_directory(source_directory, "source")
        input_path = _require_directory(input_directory, "input")
        output_directory.mkdir(parents=True, exist_ok=True)
        output = _require_directory(output_directory, "output")

        if any(
            _paths_overlap(left, right)
            for left, right in ((source, input_path), (source, output), (input_path, output))
        ):
            raise ValueError("source, input, and output directories must not overlap")

        for forbidden_path in forbidden_host_paths:
            forbidden = forbidden_path.resolve()
            if any(
                _paths_overlap(candidate, forbidden) for candidate in (source, input_path, output)
            ):
                raise ValueError(
                    f"runner mount overlaps forbidden host path: {forbidden.as_posix()}"
                )

        container_name = f"sasguard-runner-{execution_id}"
        command = self._docker_command(
            container_name=container_name,
            execution_id=str(execution_id),
            source=source,
            input_directory=input_path,
            output=output,
            script=script,
        )

        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self.limits.timeout_seconds + 15,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            self._force_remove(container_name)
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.TIMED_OUT,
                exit_code=None,
                runtime_seconds=time.monotonic() - started,
                stdout=_timeout_output(error.stdout),
                stderr=_timeout_output(error.stderr),
            )

        if completed.returncode != 0:
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.RUNNER_ERROR,
                exit_code=completed.returncode,
                runtime_seconds=time.monotonic() - started,
                stdout=completed.stdout,
                stderr=completed.stderr or "runner did not produce an execution result",
            )

        try:
            result = ExecutionResult.model_validate_json(completed.stdout)
        except ValueError as error:
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.RUNNER_ERROR,
                exit_code=completed.returncode,
                runtime_seconds=time.monotonic() - started,
                stderr=f"runner produced an invalid execution result: {error}",
            )
        if result.execution_id != execution_id:
            raise ValueError("runner result execution ID does not match its request")
        return result

    def _docker_command(
        self,
        *,
        container_name: str,
        execution_id: str,
        source: Path,
        input_directory: Path,
        output: Path,
        script: str,
    ) -> list[str]:
        command = [
            self.docker_executable,
            "run",
            "--name",
            container_name,
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--ipc",
            "none",
            "--pids-limit",
            str(self.limits.pids),
            "--memory",
            self.limits.memory,
            "--cpus",
            str(self.limits.cpus),
            "--ulimit",
            "nofile=256:256",
        ]
        if sys.platform != "win32" and os.getuid() != 0:
            command.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
        command.extend(
            [
                "--mount",
                f"type=bind,src={source},dst=/runner/source,readonly",
                "--mount",
                f"type=bind,src={input_directory},dst=/runner/input,readonly",
                "--mount",
                f"type=bind,src={output},dst=/runner/output",
                self.image,
                "--script",
                script,
                "--timeout",
                str(self.limits.timeout_seconds),
                "--execution-id",
                execution_id,
            ]
        )
        return command

    def _force_remove(self, container_name: str) -> None:
        subprocess.run(
            [self.docker_executable, "rm", "--force", container_name],
            capture_output=True,
            check=False,
        )
