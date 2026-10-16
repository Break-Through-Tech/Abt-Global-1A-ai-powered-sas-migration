"""Host-side Docker controller for isolated generated-code execution."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from sasguard.execution.environment import (
    PYTHON_ENVIRONMENT_PROBE,
    DockerImageIdentity,
    DockerRuntimeEnvironment,
    PythonEnvironment,
)
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
        started = time.monotonic()
        try:
            environment = self._inspect_environment()
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.RUNNER_ERROR,
                exit_code=None,
                runtime_seconds=time.monotonic() - started,
                stderr=f"runner environment preflight failed: {error}",
            )
        command = self._docker_command(
            container_name=container_name,
            execution_id=str(execution_id),
            source=source,
            input_directory=input_path,
            output=output,
            script=script,
            image_id=environment.image_id,
        )

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
                runtime_environment=environment,
            )
        except OSError as error:
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.RUNNER_ERROR,
                exit_code=None,
                runtime_seconds=time.monotonic() - started,
                stderr=f"Docker execution could not start: {error}",
                runtime_environment=environment,
            )

        if completed.returncode != 0:
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.RUNNER_ERROR,
                exit_code=completed.returncode,
                runtime_seconds=time.monotonic() - started,
                stdout=completed.stdout,
                stderr=completed.stderr or "runner did not produce an execution result",
                runtime_environment=environment,
            )

        try:
            payload = json.loads(completed.stdout)
            # Never accept environment claims from the generated-code container.
            payload["runtime_environment"] = environment.model_dump(mode="json")
            result = ExecutionResult.model_validate(payload)
        except (ValueError, TypeError) as error:
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.RUNNER_ERROR,
                exit_code=completed.returncode,
                runtime_seconds=time.monotonic() - started,
                stderr=f"runner produced an invalid execution result: {error}",
                runtime_environment=environment,
            )
        if result.execution_id != execution_id:
            raise ValueError("runner result execution ID does not match its request")
        return result

    def _inspect_environment(self) -> DockerRuntimeEnvironment:
        """Resolve a local image once and probe that exact ID without data mounts."""
        inspected = subprocess.run(
            [self.docker_executable, "image", "inspect", "--", self.image],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
            check=True,
        )
        images = json.loads(inspected.stdout)
        if not isinstance(images, list) or len(images) != 1:
            raise ValueError("Docker inspection must return exactly one image")
        image = images[0]
        # Validate all daemon metadata before using the identity in a Docker command.
        identity = DockerImageIdentity(
            requested_image=self.image,
            image_id=image["Id"],
            repo_digests=image.get("RepoDigests") or [],
            operating_system=image["Os"],
            architecture=image["Architecture"],
        )
        probe_name = f"sasguard-environment-{uuid4()}"
        try:
            probed = subprocess.run(
                [
                    self.docker_executable,
                    "run",
                    "--name",
                    probe_name,
                    "--rm",
                    "--pull",
                    "never",
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
                    "32",
                    "--memory",
                    "128m",
                    "--cpus",
                    "0.5",
                    "--entrypoint",
                    "python",
                    identity.image_id,
                    "-I",
                    "-c",
                    PYTHON_ENVIRONMENT_PROBE,
                ],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=30,
                check=True,
            )
        except subprocess.TimeoutExpired:
            self._force_remove(probe_name)
            raise
        return DockerRuntimeEnvironment(
            **identity.model_dump(),
            python=PythonEnvironment.model_validate_json(probed.stdout),
        )

    def _docker_command(
        self,
        *,
        container_name: str,
        execution_id: str,
        source: Path,
        input_directory: Path,
        output: Path,
        script: str,
        image_id: str,
    ) -> list[str]:
        command = [
            self.docker_executable,
            "run",
            "--name",
            container_name,
            "--rm",
            "--pull",
            "never",
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
                image_id,
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
        try:
            subprocess.run(
                [self.docker_executable, "rm", "--force", container_name],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            # Cleanup must not hide the original timeout. A failed Docker daemon
            # can leave a named container that needs manual removal later.
            pass
