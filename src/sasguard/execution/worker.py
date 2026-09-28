"""Minimal in-container worker for generated Python execution."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from sasguard.execution.result import ExecutionResult, ExecutionStatus

SOURCE_ROOT = Path("/runner/source")
INPUT_ROOT = Path("/runner/input")
OUTPUT_ROOT = Path("/runner/output")


def _relative_script(value: str) -> str:
    candidate = value.replace("\\", "/").strip()
    path = PurePosixPath(candidate)
    if (
        not candidate
        or path.is_absolute()
        or path == PurePosixPath(".")
        or ".." in path.parts
        or not candidate.lower().endswith(".py")
    ):
        raise ValueError("script must be a relative Python path beneath the source mount")
    return path.as_posix()


def _path_beneath(root: Path, relative_path: str) -> Path:
    path = (root.resolve() / Path(*PurePosixPath(relative_path).parts)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes its allowed root: {relative_path}")
    return path


def _child_environment(output_root: Path) -> dict[str, str]:
    temporary_directory = output_root / ".tmp"
    temporary_directory.mkdir(exist_ok=True)
    return {
        "HOME": "/nonexistent",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "SASGUARD_INPUT_DIR": str(INPUT_ROOT),
        "SASGUARD_OUTPUT_DIR": str(output_root),
        "TMPDIR": str(temporary_directory),
    }


def _collect_outputs(output_root: Path) -> tuple[list[str], list[str]]:
    output_files: list[str] = []
    violations: list[str] = []
    root = output_root.resolve()

    for path in sorted(output_root.rglob("*")):
        relative_path = path.relative_to(output_root).as_posix()
        if relative_path == ".tmp" or relative_path.startswith(".tmp/"):
            continue
        if path.is_symlink():
            if not path.resolve().is_relative_to(root):
                violations.append(f"output symlink escapes allowed directory: {relative_path}")
            continue
        if path.is_file():
            output_files.append(relative_path)

    return output_files, violations


def execute(
    *,
    script: str,
    timeout_seconds: float,
    execution_id: UUID,
) -> ExecutionResult:
    """Execute one generated Python entry point and collect bounded diagnostics."""
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")

    source_root = SOURCE_ROOT.resolve()
    input_root = INPUT_ROOT.resolve()
    output_root = OUTPUT_ROOT.resolve()
    script_path = _path_beneath(source_root, _relative_script(script))

    if not source_root.is_dir() or not input_root.is_dir() or not output_root.is_dir():
        raise FileNotFoundError("source, input, and output mounts must be directories")
    if not script_path.is_file():
        raise FileNotFoundError(f"generated entry point does not exist: {script}")

    started = time.monotonic()
    process = subprocess.Popen(
        [sys.executable, "-B", str(script_path)],
        cwd=source_root,
        env=_child_environment(output_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        start_new_session=True,
    )

    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.kill(-process.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        stdout, stderr = process.communicate()

    runtime_seconds = time.monotonic() - started
    output_files, violations = _collect_outputs(output_root)

    if violations:
        status = ExecutionStatus.POLICY_VIOLATION
        exit_code: int | None = process.returncode if not timed_out else None
    elif timed_out:
        status = ExecutionStatus.TIMED_OUT
        exit_code = None
    elif process.returncode == 0:
        status = ExecutionStatus.SUCCEEDED
        exit_code = 0
    else:
        status = ExecutionStatus.FAILED
        exit_code = process.returncode

    return ExecutionResult(
        execution_id=execution_id,
        status=status,
        exit_code=exit_code,
        runtime_seconds=runtime_seconds,
        stdout=stdout,
        stderr=stderr,
        output_files=output_files,
        policy_violations=violations,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", default="main.py")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--execution-id", type=UUID, default=uuid4())
    return parser


def main() -> int:
    """Run the worker and write its result atomically."""
    arguments = _parser().parse_args()
    try:
        result = execute(
            script=arguments.script,
            timeout_seconds=arguments.timeout,
            execution_id=arguments.execution_id,
        )
    except (OSError, ValueError) as error:
        print(f"Runner worker error: {error}", file=sys.stderr)
        return 2
    sys.stdout.write(result.to_json())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
