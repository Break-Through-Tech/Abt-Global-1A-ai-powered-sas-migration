"""Stage a single Program 0 candidate and collect its outputs outside Docker."""

from __future__ import annotations

import csv
import json
import shutil
import stat
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sasguard.config import load_project_configuration
from sasguard.data import load_artifact
from sasguard.execution.environment import collect_python_environment
from sasguard.execution.manifest import RunManifest
from sasguard.execution.result import ExecutionResult, ExecutionStatus
from sasguard.execution.runner import DockerExecutionRunner, RunnerLimits
from sasguard.provenance.hashing import hash_files, sha256_file, validate_sha256
from sasguard.verification.artifact import ArtifactComparison, ReferenceSource
from sasguard.verification.integrity import load_and_verify_integrity
from sasguard.verification.policy import ArtifactComparisonPolicy
from sasguard.verification.program0 import (
    EXACT_STATISTIC_ROWS,
    PROGRAM0_ARTIFACTS,
    load_program0_policies,
    validate_program0_outputs,
)

INPUT_PATH = "data/Project_1/Starrating/alldata_2025jul.csv"
PROGRAM_PATH = "data/Project_1/SAS Programs/0 - Data and Measure Standardization_2025Jul.sas"
OUTPUT_FILENAMES = (
    "less100_measure.csv",
    "measure_average_stddev_2025jul.csv",
    "std_data_2025jul_analysis.csv",
)
ValidationStatus = Literal[
    "passed", "failed", "hash_mismatch", "missing_outputs", "malformed_outputs"
]
VALIDATION_SOURCE_PATHS = (
    "configs/program0-comparison-policies.json",
    "configs/cms_2025jul.yaml",
    "configs/protected-artifacts.json",
    "src/sasguard/verification/program0.py",
    "src/sasguard/verification/comparator.py",
    "src/sasguard/verification/policy.py",
    "src/sasguard/data/loading.py",
    "src/sasguard/columns.py",
)


class Program0ValidationEvidence(BaseModel):
    """Host-recorded inputs to a comparison, without reference rows or source code."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    project_hashes: dict[str, str]
    policies: dict[str, ArtifactComparisonPolicy]
    exact_statistic_rows: tuple[Literal["N"], Literal["MIN"], Literal["MAX"]]
    output_hashes: dict[str, str]
    candidate_sha256: str


class CandidateInputFormat(StrEnum):
    """Select the supplied input source; Docker always receives an input CSV."""

    CSV = "csv"
    SAS7BDAT = "sas7bdat"


class CandidateValidationResult(BaseModel):
    """Adapter return format, not an implementation of the three-artifact validator."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    status: ValidationStatus
    artifact_results: dict[str, ArtifactComparison] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)
    evidence: Program0ValidationEvidence | None = None

    @model_validator(mode="after")
    def check_comparison_claims(self) -> Self:
        if any(
            name not in OUTPUT_FILENAMES or not reason.strip()
            for name, reason in self.errors.items()
        ):
            raise ValueError("validation errors must name declared outputs and a nonblank reason")
        if self.status in ("passed", "failed") and self.errors:
            raise ValueError("comparison outcomes cannot contain file-read or hash errors")
        for filename, comparison in self.artifact_results.items():
            if filename not in OUTPUT_FILENAMES:
                raise ValueError("validation returned an undeclared output")
            if (
                comparison.artifact != Path(filename).stem.upper()
                or comparison.reference_source is not ReferenceSource.SAS7BDAT
            ):
                raise ValueError("validation comparison must name the matching SAS artifact")
        if self.status == "passed" and (
            set(self.artifact_results) != set(OUTPUT_FILENAMES)
            or not all(item.passed for item in self.artifact_results.values())
        ):
            raise ValueError("a validation pass requires all three passing SAS comparisons")
        if self.status == "failed" and not any(
            not item.passed for item in self.artifact_results.values()
        ):
            raise ValueError("an analytical failure requires a failed artifact comparison")
        return self


class Program0Validator(Protocol):
    """Host callback matching #44's proposed arguments, with a normalized return value."""

    def __call__(
        self,
        project_root: Path,
        output_directory: Path,
        expected_sha256: Mapping[str, str],
    ) -> CandidateValidationResult: ...


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
    input_format: CandidateInputFormat = CandidateInputFormat.CSV
    execution_result: ExecutionResult | None = None
    artifacts: dict[str, CollectedArtifact] = Field(default_factory=dict)
    missing_outputs: list[str] = Field(default_factory=list)
    malformed_outputs: dict[str, str] = Field(default_factory=dict)
    violations: list[str] = Field(default_factory=list)
    error: str | None = None
    validation_status: Literal[
        "not_run",
        "passed",
        "failed",
        "hash_mismatch",
        "missing_outputs",
        "malformed_outputs",
        "validator_error",
    ] = "not_run"
    validation_results: dict[str, ArtifactComparison] = Field(default_factory=dict)
    validation_errors: dict[str, str] = Field(default_factory=dict)
    validation_error: str | None = None
    validation_evidence: Program0ValidationEvidence | None = None
    human_review: Literal["not_recorded"] = "not_recorded"

    @model_validator(mode="after")
    def check_validation_record(self) -> Self:
        if self.validation_status == "not_run":
            if self.validation_evidence is not None or (
                self.validation_results
                or self.validation_errors
                or self.validation_error is not None
            ):
                raise ValueError("an unvalidated candidate cannot contain validation results")
            return self
        if (
            self.status is not CandidateStatus.READY
            or self.execution_result is None
            or not self.execution_result.passed
        ):
            raise ValueError("validation requires successful execution and complete collection")
        if self.validation_status == "validator_error":
            if (
                self.validation_results
                or self.validation_errors
                or self.validation_error is None
                or self.validation_evidence is not None
            ):
                raise ValueError("a validator error requires an error record, not comparisons")
        else:
            CandidateValidationResult(
                status=self.validation_status,
                artifact_results=self.validation_results,
                errors=self.validation_errors,
            )
            if self.validation_error is not None:
                raise ValueError("a validation outcome cannot contain a validator error")
        return self

    @property
    def ready_for_validation(self) -> bool:
        """Return whether all declared outputs can be handed to the host validator."""
        return self.status is CandidateStatus.READY


def apply_program0_validation(
    project_root: Path,
    output_directory: Path,
    report: CandidateReport,
    validator: Program0Validator,
) -> CandidateReport:
    """Call the host validator only after successful execution and complete collection.

    Return a new report without rewriting saved execution evidence. The callback must
    check the supplied hashes before comparing SAS values. Its implementation and final
    result conversion remain in #44; no comparison rules are implemented here.
    """
    if (
        not report.ready_for_validation
        or report.execution_result is None
        or not report.execution_result.passed
        or report.validation_status != "not_run"
    ):
        return report
    try:
        root = project_root.resolve()
        runs = (root / "reports/runs").resolve()
        output = output_directory.resolve()
        if (
            runs == root
            or not runs.is_relative_to(root)
            or output.name != "output"
            or output.parent.parent != runs
        ):
            raise ValueError("validation output must stay inside a project run directory")
        if set(report.artifacts) != set(OUTPUT_FILENAMES):
            raise ValueError("validation requires metadata for all three collected outputs")
        hashes = {}
        for filename, artifact in report.artifacts.items():
            if artifact.relative_path != f"output/{filename}":
                raise ValueError("collected artifact path does not match its declared filename")
            hashes[filename] = validate_sha256(artifact.sha256)
        # Revalidate the callback's return value, including objects built with model_copy.
        result = CandidateValidationResult.model_validate(
            validator(root, output, hashes).model_dump()
        )
    except Exception as error:
        return report.model_copy(
            update={"validation_status": "validator_error", "validation_error": str(error)}
        )
    return report.model_copy(
        update={
            "validation_status": result.status,
            "validation_results": result.artifact_results,
            "validation_errors": result.errors,
            "validation_error": None,
            "validation_evidence": result.evidence,
        }
    )


def validate_collected_program0(
    project_root: Path, output_directory: Path, expected_sha256: Mapping[str, str]
) -> CandidateValidationResult:
    """Convert the shared validator result without dropping per-file failure reasons."""
    root = project_root.resolve()
    protected = root / "configs/protected-artifacts.json"
    if not load_and_verify_integrity(root, protected).passed:
        raise ValueError("protected artifacts changed before validation")
    paths = load_project_configuration(
        root / "configs/cms_2025jul.yaml", project_root=root
    ).resolve_paths(root)
    relatives = [
        *VALIDATION_SOURCE_PATHS,
        *(
            paths.reference_sas7bdat[name].relative_to(root).as_posix()
            for name in PROGRAM0_ARTIFACTS.values()
        ),
    ]
    before = hash_files(root, relatives)
    candidate = output_directory.parent / "source/main.py"
    candidate_hash = sha256_file(candidate)
    policies = load_program0_policies(root)
    result = validate_program0_outputs(root, output_directory, expected_sha256)
    if hash_files(root, relatives) != before or sha256_file(candidate) != candidate_hash:
        raise ValueError(
            "validation source, policy, reference, or candidate changed during comparison"
        )
    evidence = Program0ValidationEvidence(
        project_hashes=before,
        policies=policies,
        exact_statistic_rows=EXACT_STATISTIC_ROWS,
        output_hashes=dict(expected_sha256),
        candidate_sha256=candidate_hash,
    )
    return CandidateValidationResult.model_validate({**result.model_dump(), "evidence": evidence})


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
    validator: Program0Validator | None = None,
    input_format: CandidateInputFormat = CandidateInputFormat.CSV,
) -> tuple[CandidateReport, Path]:
    """Snapshot one standalone Python file, run it in Docker, and collect three CSVs.

    Only the candidate, hospital CSV, and an input-derived contract enter Docker.
    Every run gets a fresh directory; failures retain their manifest and report.
    No generated code is executed on the host. An optional host callback can validate
    collected outputs after execution; no validator is enabled by default.
    """
    root = project_root.resolve()
    input_format = CandidateInputFormat(input_format)
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
    input_relative = (
        INPUT_PATH
        if input_format is CandidateInputFormat.CSV
        else str(Path(INPUT_PATH).with_suffix(".sas7bdat").as_posix())
    )
    input_path = root / input_relative
    staged_input = inputs / Path(INPUT_PATH).name
    original_input_hash = sha256_file(input_path)
    if input_format is CandidateInputFormat.CSV:
        shutil.copyfile(input_path, staged_input)
        if sha256_file(staged_input) != original_input_hash:
            raise ValueError("staged hospital input differs from protected source")
    else:
        # Use only the supplied source input, never a reference output. The supplied
        # export loses bits in some decimals, so exact extrema need a lossless export.
        load_artifact(input_path, key="PROVIDER_ID").frame.to_csv(
            staged_input, index=False, float_format="%.17g"
        )
        if sha256_file(input_path) != original_input_hash:
            raise ValueError("source input changed during SAS-to-CSV staging")
    contract = {
        "schema_version": 1,
        "input_filename": staged_input.name,
        "input_columns": _csv_columns(staged_input),
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
        input_hashes={input_relative: original_input_hash},
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
            "input_format": input_format.value,
            "input_source_path": input_relative,
            "input_source_sha256": original_input_hash,
            "staged_input_sha256": sha256_file(staged_input),
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
    report = report.model_copy(update={"execution_result": execution, "input_format": input_format})
    if not load_and_verify_integrity(root, manifest_path).passed:
        report = report.model_copy(
            update={
                "status": CandidateStatus.INTEGRITY_FAILED,
                "error": "protected-artifact integrity failed after execution",
            }
        )
    if validator is not None:
        report = apply_program0_validation(root, output, report, validator)
    path = run / "report.json"
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report, path
