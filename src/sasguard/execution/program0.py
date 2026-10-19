"""Stage a single Program 0 candidate and collect its outputs outside Docker."""

from __future__ import annotations

import csv
import json
import shutil
import stat
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from sasguard.data import load_artifact
from sasguard.execution.environment import collect_python_environment
from sasguard.execution.manifest import RunManifest
from sasguard.execution.result import ExecutionResult, ExecutionStatus
from sasguard.execution.runner import DockerExecutionRunner, RunnerLimits
from sasguard.provenance.hashing import hash_files, sha256_file
from sasguard.verification.integrity import load_and_verify_integrity

INPUT_PATH = "data/Project_1/Starrating/alldata_2025jul.csv"
PROGRAM_PATH = "data/Project_1/SAS Programs/0 - Data and Measure Standardization_2025Jul.sas"
OUTPUT_FILENAMES = (
    "less100_measure.csv",
    "measure_average_stddev_2025jul.csv",
    "std_data_2025jul_analysis.csv",
)


class CandidateStatus(StrEnum):
    """Execution and output-collection outcomes, independent of numerical parity."""

    READY = "ready_for_validation"
    SYNTAX_ERROR = "syntax_error"
    EXECUTION_FAILED = "execution_failed"
    TIMED_OUT = "timed_out"
    POLICY_VIOLATION = "policy_violation"
    RUNNER_ERROR = "runner_error"
    MISSING_OUTPUTS = "missing_outputs"
    MALFORMED_OUTPUTS = "malformed_outputs"
    INTEGRITY_FAILED = "integrity_failed"


class CollectedArtifact(BaseModel):
    """A readable candidate CSV that is available for the shared host validator."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    relative_path: str
    sha256: str
    rows: int = Field(ge=0)
    columns: list[str]


class CandidateReport(BaseModel):
    """Separate candidate execution, output structure, and future SAS comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    scope: Literal["Program 0 candidate execution and CSV collection"] = (
        "Program 0 candidate execution and CSV collection"
    )
    status: CandidateStatus
    execution_result: ExecutionResult | None = None
    artifacts: dict[str, CollectedArtifact] = Field(default_factory=dict)
    missing_outputs: list[str] = Field(default_factory=list)
    malformed_outputs: dict[str, str] = Field(default_factory=dict)
    violations: list[str] = Field(default_factory=list)
    error: str | None = None
    validation_status: Literal["not_run"] = "not_run"
    human_review: Literal["not_recorded"] = "not_recorded"

    @property
    def ready_for_validation(self) -> bool:
        """Return whether all declared outputs can be handed to the host validator."""
        return self.status is CandidateStatus.READY


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _csv_columns(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        columns = next(csv.reader(stream, strict=True), None)
    if not columns or any(not name.strip() for name in columns):
        raise ValueError("CSV requires a nonempty header with nonblank column names")
    if len({name.casefold() for name in columns}) != len(columns):
        raise ValueError("CSV header contains duplicate case-insensitive column names")
    return columns


def collect_program0_outputs(output_directory: Path) -> CandidateReport:
    """Collect only regular, well-formed CSVs; leave SAS schema and values to #44.

    An empty table with a header is valid. Row widths, quoting, paths, and duplicate
    headers are transport checks. Missingness, keys, and analytical schemas are not.
    """
    output = output_directory.resolve()
    violations = []
    for path in output.rglob("*"):
        relative = path.relative_to(output).as_posix()
        if relative == ".tmp" or relative.startswith(".tmp/"):
            continue
        metadata = path.lstat()
        # Docker's Linux links can appear as non-symlink reparse points on Windows.
        reparse_point = getattr(metadata, "st_file_attributes", 0) & 0x400
        if (
            stat.S_ISLNK(metadata.st_mode)
            or reparse_point
            or not path.resolve().is_relative_to(output)
        ):
            violations.append(f"output must not be a symlink or escape its directory: {relative}")
        elif not path.is_dir() and relative not in OUTPUT_FILENAMES:
            violations.append(f"undeclared output: {relative}")
    if violations:
        return CandidateReport(status=CandidateStatus.POLICY_VIOLATION, violations=violations)

    artifacts = {}
    missing = []
    malformed = {}
    for filename in OUTPUT_FILENAMES:
        path = output / filename
        if not path.exists():
            missing.append(filename)
            continue
        if not path.is_file():
            malformed[filename] = "declared output must be a regular CSV file"
            continue
        try:
            columns = _csv_columns(path)
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = csv.reader(stream, strict=True)
                next(rows)
                for number, row in enumerate(rows, start=2):
                    if len(row) != len(columns):
                        raise ValueError(
                            f"CSV record {number} has a different width from its header"
                        )
            loaded = load_artifact(path)
            artifacts[filename] = CollectedArtifact(
                relative_path=f"output/{filename}",
                sha256=sha256_file(path),
                rows=loaded.row_count,
                columns=list(loaded.columns),
            )
        except (OSError, ValueError, csv.Error) as error:
            malformed[filename] = str(error)
    status = CandidateStatus.READY
    if malformed:
        status = CandidateStatus.MALFORMED_OUTPUTS
    elif missing:
        status = CandidateStatus.MISSING_OUTPUTS
    return CandidateReport(
        status=status, artifacts=artifacts, missing_outputs=missing, malformed_outputs=malformed
    )


def run_program0_candidate(
    project_root: Path,
    candidate: Path,
    *,
    image: str = "sasguard-runner:local",
    limits: RunnerLimits | None = None,
) -> tuple[CandidateReport, Path]:
    """Snapshot one standalone Python file, run it in Docker, and collect three CSVs.

    Only the candidate, hospital CSV, and an input-derived contract enter Docker.
    Every run gets a fresh directory; failures retain their manifest and report.
    No generated code is executed on the host. Numerical validation is a separate step.
    """
    root = project_root.resolve()
    if candidate.is_symlink():
        raise ValueError("candidate must be a regular Python file, not a symlink")
    candidate = candidate.resolve()
    if not candidate.is_file() or candidate.suffix.lower() != ".py":
        raise ValueError("candidate must be an existing standalone .py file")
    if candidate.is_relative_to(root / "data") or candidate.is_relative_to(
        root / "reference_python"
    ):
        raise ValueError("candidate must be separate from protected data and reference Python")
    manifest_path = root / "configs" / "protected-artifacts.json"
    if not load_and_verify_integrity(root, manifest_path).passed:
        raise ValueError("protected-artifact integrity failed before candidate execution")
    run = root / "reports" / "runs" / f"program0-candidate-{uuid4()}"
    if not run.resolve().is_relative_to(root):
        raise ValueError("run directory must stay within the repository")
    source, inputs, output = (run / name for name in ("source", "input", "output"))
    for directory in (source, inputs, output):
        directory.mkdir(parents=True)
    original_code_hash = sha256_file(candidate, normalize_text=False)
    shutil.copyfile(candidate, source / "main.py")
    if sha256_file(source / "main.py", normalize_text=False) != original_code_hash:
        raise ValueError("staged candidate differs from selected source")
    input_path = root / INPUT_PATH
    original_input_hash = sha256_file(input_path)
    shutil.copyfile(input_path, inputs / input_path.name)
    if sha256_file(inputs / input_path.name) != original_input_hash:
        raise ValueError("staged hospital input differs from protected source")
    contract = {
        "schema_version": 1,
        "input_filename": input_path.name,
        "input_columns": _csv_columns(inputs / input_path.name),
        "identifier_column": "PROVIDER_ID",
        "identifier_type": "text; preserve leading zeros and literal NA and NULL",
        "numeric_missing_value": "empty CSV field",
        "output_filenames": list(OUTPUT_FILENAMES),
        "environment": {
            "SASGUARD_INPUT_DIR": "/runner/input",
            "SASGUARD_OUTPUT_DIR": "/runner/output",
        },
    }
    _write_json(inputs / "contract.json", contract)
    manifest = RunManifest.create(
        source_hashes=hash_files(root, [PROGRAM_PATH]),
        input_hashes={INPUT_PATH: original_input_hash},
        generated_code_hashes={"source/main.py": sha256_file(source / "main.py")},
        controller_environment=collect_python_environment(),
    )
    (run / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    _write_json(
        run / "staging.json",
        {
            "candidate_sha256_bytes": original_code_hash,
            "contract_sha256": sha256_file(inputs / "contract.json"),
            "controller_sha256": sha256_file(Path(__file__)),
            "validation_status": "not_run",
        },
    )
    execution = None
    try:
        # Compile bytes to respect the candidate's declared encoding without running it.
        compile((source / "main.py").read_bytes(), "main.py", "exec")
    except SyntaxError as error:
        report = CandidateReport(status=CandidateStatus.SYNTAX_ERROR, error=str(error))
    else:
        try:
            execution = DockerExecutionRunner(image=image, limits=limits).run(
                source_directory=source,
                input_directory=inputs,
                output_directory=output,
                forbidden_host_paths=(root / "data", root / "reference_python"),
            )
            manifest = manifest.with_execution_result(execution)
            (run / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
            if execution.passed:
                report = collect_program0_outputs(output)
            else:
                status = {
                    ExecutionStatus.FAILED: CandidateStatus.EXECUTION_FAILED,
                    ExecutionStatus.TIMED_OUT: CandidateStatus.TIMED_OUT,
                    ExecutionStatus.POLICY_VIOLATION: CandidateStatus.POLICY_VIOLATION,
                    ExecutionStatus.RUNNER_ERROR: CandidateStatus.RUNNER_ERROR,
                }[execution.status]
                report = CandidateReport(status=status, violations=execution.policy_violations)
        except (OSError, ValueError, RuntimeError) as error:
            report = CandidateReport(status=CandidateStatus.RUNNER_ERROR, error=str(error))
    report = report.model_copy(update={"execution_result": execution})
    if not load_and_verify_integrity(root, manifest_path).passed:
        report = report.model_copy(
            update={
                "status": CandidateStatus.INTEGRITY_FAILED,
                "error": "protected-artifact integrity failed after execution",
            }
        )
    path = run / "report.json"
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report, path
