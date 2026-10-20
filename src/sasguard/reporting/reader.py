"""Adapters for existing Mortality bundles and individual synthetic model records."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sasguard.config import load_project_configuration
from sasguard.execution.environment import DockerRuntimeEnvironment
from sasguard.execution.manifest import RunManifest
from sasguard.execution.result import ExecutionResult
from sasguard.prototypes.mortality import mortality_policy
from sasguard.provenance.hashing import normalize_relative_path, sha256_file, validate_sha256
from sasguard.reporting.models import RunReport, summarize_artifact
from sasguard.verification.artifact import ArtifactComparison, ReferenceSource
from sasguard.verification.golden_trace import GoldenTraceResult
from sasguard.verification.integrity import ProtectedArtifactManifest, load_and_verify_integrity
from sasguard.verification.policy import ArtifactComparisonPolicy

MORTALITY_SCOPE = "Program 1 Mortality only, supplied Program 0 intermediate"


def safe_file(root: Path, relative: str) -> Path:
    path = root / normalize_relative_path(relative)
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("report input must be an ordinary file inside its declared directory")
    if not path.is_file():
        raise FileNotFoundError(f"required report input is missing: {relative}")
    return path


def _matches(root: Path, relative: str, expected: str) -> bool:
    try:
        return sha256_file(safe_file(root, relative)) == validate_sha256(expected)
    except (OSError, ValueError):
        return False


class MortalityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    implementation: Literal["human_reference"]
    scope: Literal["Program 1 Mortality only, supplied Program 0 intermediate"]
    input_artifact: Literal["STD_DATA_2025JUL_ANALYSIS"]
    reference_artifact: Literal["OUTCOME_MORTALITY"]
    runner_image: str
    runner_environment: DockerRuntimeEnvironment | None
    reference_sha256: str
    output_sha256: str
    trace_report: Literal["trace.json"]
    policy: ArtifactComparisonPolicy
    comparison: ArtifactComparison

    @field_validator("reference_sha256", "output_sha256")
    @classmethod
    def valid_digest(cls, value: str) -> str:
        return validate_sha256(value)


class SyntheticRecord(BaseModel):
    """Accept known metadata fields; never export the unselected payload."""

    model_config = ConfigDict(strict=True)
    schema_version: Literal[1]
    timestamp: datetime
    case: str
    model: str
    generation_status: Literal["succeeded", "failed"]
    execution_result: ExecutionResult | None
    validation_status: Literal["passed", "failed", "not_run"]
    comparison: ArtifactComparison | None
    hashes: dict[str, str] = Field(min_length=1)
    validation_policy_version: str = "legacy_inferred"

    @field_validator("hashes")
    @classmethod
    def valid_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        return {
            normalize_relative_path(path): validate_sha256(digest) for path, digest in value.items()
        }

    @field_validator("case", "model", "validation_policy_version")
    @classmethod
    def metadata_identifier(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", value) is None:
            raise ValueError("unsupported report metadata identifier")
        return value

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("run timestamp must include a timezone")
        return value


def _mortality(root: Path, run: Path) -> RunReport:
    manifest = RunManifest.model_validate_json(
        safe_file(run, "manifest.json").read_text(encoding="utf-8")
    )
    policy = mortality_policy(root)
    config = load_project_configuration(
        root / "configs/cms_2025jul.yaml", project_root=root, require_existing=False
    )
    paths = config.resolve_paths(root)
    trace = GoldenTraceResult.model_validate_json(
        safe_file(run, "trace.json").read_text(encoding="utf-8")
    )
    if trace.scope != MORTALITY_SCOPE:
        raise ValueError("unsupported Mortality trace scope")
    issues = []
    evidence = {
        "manifest.json": sha256_file(run / "manifest.json"),
        "trace.json": sha256_file(run / "trace.json"),
    }
    expected_sources = {
        path.relative_to(root).as_posix() for path in (*paths.programs, *paths.macros)
    } | {
        "reference_python/mortality.py",
        "configs/cms_2025jul.yaml",
        "configs/mortality-comparison-policy.json",
        "configs/cms-artifact-lineage.json",
        "pyproject.toml",
        "uv.lock",
        "requirements.lock",
        "requirements-runtime.lock",
        "Dockerfile",
        "Dockerfile.runner",
    }
    input_path = paths.reference_sas7bdat["STD_DATA_2025JUL_ANALYSIS"]
    expected_inputs = {input_path.relative_to(root).as_posix()}
    if (
        set(manifest.source_hashes) != expected_sources
        or set(manifest.input_hashes) != expected_inputs
    ):
        issues.append("source_or_input_manifest_layout_not_confirmed")
    declared_hashes = {
        **{key: value for key, value in manifest.source_hashes.items() if key in expected_sources},
        **{key: value for key, value in manifest.input_hashes.items() if key in expected_inputs},
    }
    for relative, digest in declared_hashes.items():
        if not _matches(root, relative, digest):
            issues.append("source_or_input_snapshot_not_confirmed")
    source_digest = manifest.source_hashes.get("reference_python/mortality.py")
    input_digest = manifest.input_hashes.get(input_path.relative_to(root).as_posix())
    if not source_digest or not _matches(run, "source/mortality.py", source_digest):
        issues.append("staged_source_not_confirmed")
    if not input_digest or not _matches(run, f"input/{input_path.name}", input_digest):
        issues.append("staged_input_not_confirmed")
    execution = manifest.execution_result
    if manifest.model_name is not None or manifest.generated_code_hashes:
        issues.append("implementation_records_disagree")
    if execution and execution.passed and execution.runtime_environment is None:
        issues.append("container_identity_not_recorded")
    if (run / "execution.json").exists():
        recorded_execution = ExecutionResult.model_validate_json(
            safe_file(run, "execution.json").read_text(encoding="utf-8")
        )
        evidence["execution.json"] = sha256_file(run / "execution.json")
        if execution != recorded_execution:
            issues.append("execution_records_disagree")
    elif execution is not None:
        issues.append("execution_record_missing")
    comparison = None
    if (run / "comparison.json").exists():
        record = MortalityRecord.model_validate_json(
            safe_file(run, "comparison.json").read_text(encoding="utf-8")
        )
        evidence["comparison.json"] = sha256_file(run / "comparison.json")
        comparison = record.comparison
        reference = paths.reference_sas7bdat["OUTCOME_MORTALITY"]
        protected_path = safe_file(root, "configs/protected-artifacts.json")
        protected = ProtectedArtifactManifest.load(protected_path)
        recorded_reference = {entry.path: entry.sha256 for entry in protected.files}.get(
            reference.relative_to(root).as_posix()
        )
        intact = load_and_verify_integrity(root, protected_path).passed
        if (
            not intact
            or recorded_reference != record.reference_sha256
            or not _matches(root, reference.relative_to(root).as_posix(), record.reference_sha256)
        ):
            issues.append("protected_sas_reference_not_confirmed")
        if not _matches(run, "output/OUTCOME_MORTALITY.csv", record.output_sha256):
            issues.append("output_hash_not_confirmed")
        if (
            record.policy != policy
            or comparison.artifact != "OUTCOME_MORTALITY"
            or comparison.reference_source is not ReferenceSource.SAS7BDAT
            or manifest.artifact_results != {comparison.artifact: comparison}
            or execution is None
            or record.runner_environment != execution.runtime_environment
        ):
            issues.append("comparison_records_disagree")
        expected_status = "passed" if comparison.passed else "failed"
        checked = {
            item.artifact: item.status.value
            for item in trace.checkpoints
            if item.status.value != "not_checked"
        }
        if checked != {"OUTCOME_MORTALITY": expected_status}:
            issues.append("trace_records_disagree")
    elif manifest.artifact_results or trace.first_divergences or trace.all_checked_passed:
        issues.append("comparison_record_missing")
    evidence.update({f"project:{key}": value for key, value in declared_hashes.items()})
    if comparison is not None:
        evidence["reference:OUTCOME_MORTALITY"] = record.reference_sha256
        evidence["output/OUTCOME_MORTALITY.csv"] = record.output_sha256
    artifact = summarize_artifact(
        comparison, name="OUTCOME_MORTALITY", authority="supplied_sas", policy=policy
    )
    return RunReport(
        report_kind="mortality",
        run_id=str(manifest.run_id),
        run_timestamp=manifest.timestamp,
        input_release="CMS July 2025",
        scope=MORTALITY_SCOPE,
        code_origin="human_reference",
        generation_status="not_applicable",
        execution_status=execution.status.value if execution else "not_recorded",
        validation_status=("passed" if comparison.passed else "failed")
        if comparison
        else "not_run",
        evidence_integrity="not_confirmed" if issues else "matched",
        evidence_issues=tuple(sorted(set(issues))),
        docker_image_id=(
            execution.runtime_environment.image_id
            if execution and execution.runtime_environment
            else None
        ),
        runtime_seconds=execution.runtime_seconds if execution else None,
        exit_code=execution.exit_code if execution else None,
        artifacts=(artifact,),
        repair_attempts=manifest.repair_attempts,
        evidence_hashes=evidence,
        first_observed_failures=tuple(item.artifact for item in trace.first_divergences),
        not_checked=trace.not_checked_artifacts,
        limitations=(
            "Supplied Program 0 intermediate was used, not regenerated.",
            "Other domains, eligibility, clustering, and final ratings are not verified.",
            "This summarizes recorded checks; it is not a rerun or signed attestation.",
        ),
    )


def _synthetic(run: Path) -> RunReport:
    source = safe_file(run, "report.json")
    saved = SyntheticRecord.model_validate_json(source.read_text(encoding="utf-8"))
    allowed = {
        "source.sas",
        "prompt.txt",
        "request.json",
        "policy.json",
        "input/input.csv",
        "expected/adjusted.csv",
        "response.json",
        "source/main.py",
        "source/sas_helpers.py",
        "output/adjusted.csv",
    }
    required = {
        "source.sas",
        "prompt.txt",
        "request.json",
        "policy.json",
        "input/input.csv",
        "expected/adjusted.csv",
    }
    if not required.issubset(saved.hashes) or not set(saved.hashes).issubset(allowed):
        raise ValueError("unsupported synthetic artifact hash set")
    issues = []
    for relative, digest in saved.hashes.items():
        if not _matches(run, relative, digest):
            issues.append("recorded_artifact_hash_not_confirmed")
    policy = ArtifactComparisonPolicy.model_validate_json(
        safe_file(run, "policy.json").read_text(encoding="utf-8")
    )
    execution = saved.execution_result
    comparison = saved.comparison
    if saved.validation_status == "passed" and (
        comparison is None or not comparison.passed or execution is None or not execution.passed
    ):
        issues.append("validation_records_disagree")
    if comparison is not None and (
        saved.generation_status != "succeeded"
        or execution is None
        or not execution.passed
        or comparison.artifact != "SYNTHETIC_ADJUSTED"
    ):
        issues.append("comparison_without_successful_execution")
    if comparison is not None and (
        comparison.reference_source is not ReferenceSource.CSV
        or saved.validation_status != ("passed" if comparison.passed else "failed")
    ):
        issues.append("comparison_status_or_reference_disagrees")
    if execution and saved.generation_status != "succeeded":
        issues.append("execution_without_successful_generation")
    if execution and execution.passed:
        if execution.output_files == ["adjusted.csv"]:
            if not {"source/main.py", "response.json"}.issubset(saved.hashes):
                issues.append("candidate_or_response_hash_missing")
            if saved.validation_status == "passed" and "output/adjusted.csv" not in saved.hashes:
                issues.append("output_hash_missing")
        elif saved.validation_status != "failed":
            issues.append("output_contract_and_validation_disagree")
    artifact = summarize_artifact(
        comparison,
        name="SYNTHETIC_ADJUSTED",
        authority="handwritten_synthetic",
        policy=policy,
        validation_failed=saved.validation_status == "failed",
    )
    return RunReport(
        report_kind="synthetic",
        run_id=f"record-{sha256_file(source)[:16]}",
        run_timestamp=saved.timestamp,
        input_release="Synthetic fixtures, not CMS data",
        scope=f"Synthetic case {saved.case}; handwritten expectations; no SAS-runtime comparison",
        code_origin="model_generated",
        generation_status=saved.generation_status,
        execution_status=execution.status.value if execution else "not_recorded",
        validation_status=saved.validation_status,
        evidence_integrity="not_confirmed" if issues else "matched",
        evidence_issues=tuple(sorted(set(issues))),
        model_name=saved.model,
        validation_policy_version=saved.validation_policy_version,
        docker_image_id=(
            execution.runtime_environment.image_id
            if execution and execution.runtime_environment
            else None
        ),
        runtime_seconds=execution.runtime_seconds if execution else None,
        exit_code=execution.exit_code if execution else None,
        artifacts=(artifact,),
        evidence_hashes={"report.json": sha256_file(source), **saved.hashes},
        first_observed_failures=("SYNTHETIC_ADJUSTED",)
        if saved.validation_status == "failed"
        else (),
        limitations=(
            "Synthetic expectations have not been generated by a SAS runtime.",
            "No clinical pipeline output, hospital eligibility, or ratings are verified.",
            "This summarizes recorded checks; it is not a rerun or signed attestation.",
        ),
    )


def read_run_report(project_root: Path, run_directory: Path) -> RunReport:
    root = project_root.resolve()
    run = run_directory if run_directory.is_absolute() else root / run_directory
    run = run.resolve()
    if run.parent != (root / "reports" / "runs").resolve():
        raise ValueError("report input must be a top-level saved run inside reports/runs")
    if (run / "manifest.json").is_file():
        return _mortality(root, run)
    if (run / "report.json").is_file():
        return _synthetic(run)
    raise ValueError("unsupported run layout; expected a Mortality bundle or synthetic attempt")
