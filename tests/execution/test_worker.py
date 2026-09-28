"""Unit tests for the isolated runner's in-container worker."""

import json
import os
import sys
from pathlib import Path
from uuid import UUID

import pytest

from sasguard.execution import worker
from sasguard.execution.result import ExecutionStatus

EXECUTION_ID = UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def worker_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    source = tmp_path / "source"
    input_directory = tmp_path / "input"
    output = tmp_path / "output"
    for path in (source, input_directory, output):
        path.mkdir()
    monkeypatch.setattr(worker, "SOURCE_ROOT", source)
    monkeypatch.setattr(worker, "INPUT_ROOT", input_directory)
    monkeypatch.setattr(worker, "OUTPUT_ROOT", output)
    return source, input_directory, output


def test_execute_captures_success_with_a_sanitized_environment(
    worker_roots: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, input_directory, output = worker_roots
    (input_directory / "value.txt").write_text("input\n", encoding="utf-8")
    (source / "main.py").write_text(
        """\
import os
from pathlib import Path

assert "SASGUARD_TEST_SECRET" not in os.environ
input_dir = Path(os.environ["SASGUARD_INPUT_DIR"])
output_dir = Path(os.environ["SASGUARD_OUTPUT_DIR"])
(output_dir / "result.txt").write_text(
    (input_dir / "value.txt").read_text(encoding="utf-8"),
    encoding="utf-8",
)
print("complete")
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("SASGUARD_TEST_SECRET", "not-for-the-child")

    result = worker.execute(
        script="main.py",
        timeout_seconds=2,
        execution_id=EXECUTION_ID,
    )

    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.exit_code == 0
    assert result.stdout == "complete\n"
    assert result.output_files == ["result.txt"]
    assert (output / "result.txt").read_text(encoding="utf-8") == "input\n"


def test_execute_captures_generated_failure(worker_roots: tuple[Path, Path, Path]) -> None:
    source, _, _ = worker_roots
    (source / "main.py").write_text(
        "import sys\nprint('details', file=sys.stderr)\nsys.exit(9)\n",
        encoding="utf-8",
    )

    result = worker.execute(
        script="main.py",
        timeout_seconds=2,
        execution_id=EXECUTION_ID,
    )

    assert result.status is ExecutionStatus.FAILED
    assert result.exit_code == 9
    assert result.stderr == "details\n"


@pytest.mark.skipif(sys.platform == "win32", reason="worker process groups run inside Linux")
def test_execute_terminates_a_timeout(worker_roots: tuple[Path, Path, Path]) -> None:
    source, _, _ = worker_roots
    (source / "main.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")

    result = worker.execute(
        script="main.py",
        timeout_seconds=0.05,
        execution_id=EXECUTION_ID,
    )

    assert result.status is ExecutionStatus.TIMED_OUT
    assert result.exit_code is None


def test_execute_rejects_unsafe_or_missing_scripts(
    worker_roots: tuple[Path, Path, Path],
) -> None:
    with pytest.raises(ValueError, match="relative Python path"):
        worker.execute(
            script="../main.py",
            timeout_seconds=2,
            execution_id=EXECUTION_ID,
        )
    with pytest.raises(FileNotFoundError, match="entry point"):
        worker.execute(
            script="missing.py",
            timeout_seconds=2,
            execution_id=EXECUTION_ID,
        )


def test_main_emits_only_the_machine_result(
    worker_roots: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, _, _ = worker_roots
    (source / "main.py").write_text("print('generated output')\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "worker",
            "--script",
            "main.py",
            "--timeout",
            "2",
            "--execution-id",
            str(EXECUTION_ID),
        ],
    )

    assert worker.main() == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution_id"] == str(EXECUTION_ID)
    assert payload["stdout"] == "generated output\n"
    assert captured.err == ""


def test_main_reports_worker_configuration_errors(
    worker_roots: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["worker", "--script", "missing.py"])

    assert worker.main() == 2
    assert "Runner worker error" in capsys.readouterr().err


def test_output_symlink_escape_is_a_policy_violation(
    worker_roots: tuple[Path, Path, Path],
) -> None:
    source, input_directory, _ = worker_roots
    (input_directory / "value.txt").write_text("input\n", encoding="utf-8")
    (source / "main.py").write_text(
        """\
import os
from pathlib import Path

output = Path(os.environ["SASGUARD_OUTPUT_DIR"])
(output / "escape").symlink_to(Path(os.environ["SASGUARD_INPUT_DIR"]) / "value.txt")
""",
        encoding="utf-8",
    )
    if os.name == "nt":
        pytest.skip("creating symlinks may require Windows Developer Mode")

    result = worker.execute(
        script="main.py",
        timeout_seconds=2,
        execution_id=EXECUTION_ID,
    )

    assert result.status is ExecutionStatus.POLICY_VIOLATION
    assert result.policy_violations == ["output symlink escapes allowed directory: escape"]
