"""Read saved Program 0 runs without executing candidates or repeating comparisons."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from sasguard.config import load_project_configuration
from sasguard.execution.manifest import RunManifest
from sasguard.execution.program0 import (
    INPUT_PATH,
    PROGRAM_PATH,
    VALIDATION_SOURCE_PATHS,
    CandidateInputFormat,
    CandidateReport,
)
from sasguard.provenance.hashing import sha256_file
from sasguard.reporting.models import RunReport, summarize_artifact
from sasguard.reporting.reader import _matches, safe_file
from sasguard.verification.integrity import load_and_verify_integrity
from sasguard.verification.program0 import (
    EXACT_STATISTIC_ROWS,
    PROGRAM0_ARTIFACTS,
    load_program0_policies,
)


class StagingRecord(BaseModel):
    """Accept the original CSV staging shape and the explicit input-source extension."""

    model_config = ConfigDict(extra="forbid")
    candidate_sha256_bytes: str
    contract_sha256: str
    controller_sha256: str
    validation_status: Literal["not_run"]
    input_format: CandidateInputFormat = CandidateInputFormat.CSV
    input_source_path: str | None = None
    input_source_sha256: str | None = None
    staged_input_sha256: str | None = None


def read_program0_report(root: Path, run: Path) -> RunReport:
    """Project known host records into aggregate reporting facts, never raw errors or rows."""
    saved = CandidateReport.model_validate_json(safe_file(run, "report.json").read_bytes())
    manifest = RunManifest.model_validate_json(safe_file(run, "manifest.json").read_bytes())
    staging = StagingRecord.model_validate_json(safe_file(run, "staging.json").read_bytes())
    issues = []
    hashes = {
        name: sha256_file(safe_file(run, name))
        for name in ("report.json", "manifest.json", "staging.json")
    }
    expected_input = (
        INPUT_PATH
        if saved.input_format is CandidateInputFormat.CSV
        else Path(INPUT_PATH).with_suffix(".sas7bdat").as_posix()
    )
    if (
        set(manifest.source_hashes) != {PROGRAM_PATH}
        or set(manifest.input_hashes) != {expected_input}
        or set(manifest.generated_code_hashes) != {"source/main.py"}
    ):
        issues.append("manifest_layout_not_confirmed")
    for relative, digest in (
        (PROGRAM_PATH, manifest.source_hashes.get(PROGRAM_PATH)),
        (expected_input, manifest.input_hashes.get(expected_input)),
    ):
        if digest is None or not _matches(root, relative, digest):
            issues.append("source_or_input_snapshot_not_confirmed")
        elif digest is not None:
            hashes[f"project:{relative}"] = digest
    candidate = safe_file(run, "source/main.py")
    candidate_hash = manifest.generated_code_hashes.get("source/main.py")
    if (
        candidate_hash is None
        or not _matches(run, "source/main.py", candidate_hash)
        or sha256_file(candidate, normalize_text=False) != staging.candidate_sha256_bytes
    ):
        issues.append("staged_candidate_not_confirmed")
    else:
        hashes["source/main.py"] = candidate_hash
    if not _matches(run, "input/contract.json", staging.contract_sha256):
        issues.append("staged_contract_not_confirmed")
    if not _matches(root, "src/sasguard/execution/program0.py", staging.controller_sha256):
        issues.append("controller_snapshot_not_confirmed")
    if (
        staging.input_format is not saved.input_format
        or (staging.input_source_path is not None and staging.input_source_path != expected_input)
        or (
            staging.input_source_sha256 is not None
            and staging.input_source_sha256 != manifest.input_hashes.get(expected_input)
        )
    ):
        issues.append("input_source_records_disagree")
    input_digest = staging.staged_input_sha256
    if input_digest is None and saved.input_format is CandidateInputFormat.CSV:
        input_digest = manifest.input_hashes.get(expected_input)
    if input_digest is None or not _matches(run, "input/alldata_2025jul.csv", input_digest):
        issues.append("staged_input_not_confirmed")
    execution = saved.execution_result
    if execution != manifest.execution_result:
        issues.append("execution_records_disagree")
    if execution and execution.passed and execution.runtime_environment is None:
        issues.append("container_identity_not_recorded")
    if saved.ready_for_validation and (
        execution is None
        or not execution.passed
        or set(execution.output_files) != set(PROGRAM0_ARTIFACTS)
        or set(saved.artifacts) != set(PROGRAM0_ARTIFACTS)
    ):
        issues.append("execution_and_collection_records_disagree")
    if not load_and_verify_integrity(
        root, safe_file(root, "configs/protected-artifacts.json")
    ).passed:
        issues.append("protected_artifacts_not_confirmed")
    if set(saved.artifacts) - set(PROGRAM0_ARTIFACTS):
        issues.append("collection_layout_not_confirmed")
    for filename, artifact in saved.artifacts.items():
        if filename not in PROGRAM0_ARTIFACTS:
            continue
        relative = f"output/{filename}"
        if artifact.relative_path != relative or not _matches(run, relative, artifact.sha256):
            issues.append("collected_output_not_confirmed")
        else:
            hashes[relative] = artifact.sha256
        compared = saved.validation_results.get(filename)
        if compared is not None and (
            compared.actual_rows != artifact.rows
            or tuple(name.casefold() for name in compared.actual_columns)
            != tuple(name.casefold() for name in artifact.columns)
        ):
            issues.append("collection_and_comparison_records_disagree")
    policies = {}
    evidence = saved.validation_evidence
    if saved.validation_status in (
        "passed",
        "failed",
        "hash_mismatch",
        "missing_outputs",
        "malformed_outputs",
    ):
        if evidence is None:
            issues.append("validation_snapshot_not_recorded")
        else:
            config = load_project_configuration(
                root / "configs/cms_2025jul.yaml", project_root=root, require_existing=False
            ).resolve_paths(root)
            expected_paths = set(VALIDATION_SOURCE_PATHS) | {
                config.reference_sas7bdat[name].relative_to(root).as_posix()
                for name in PROGRAM0_ARTIFACTS.values()
            }
            if set(evidence.project_hashes) != expected_paths:
                issues.append("validation_snapshot_layout_not_confirmed")
            for relative in expected_paths:
                digest = evidence.project_hashes.get(relative)
                if digest is None or not _matches(root, relative, digest):
                    issues.append("validation_snapshot_not_confirmed")
                else:
                    hashes[f"project:{relative}"] = digest
            if (
                evidence.output_hashes
                != {name: item.sha256 for name, item in saved.artifacts.items()}
                or evidence.candidate_sha256 != candidate_hash
            ):
                issues.append("validation_candidate_or_outputs_disagree")
            if (
                evidence.policies != load_program0_policies(root)
                or evidence.exact_statistic_rows != EXACT_STATISTIC_ROWS
            ):
                issues.append("validation_policy_records_disagree")
            policies = evidence.policies
    validation_status: Literal["passed", "failed", "not_run"] = (
        "passed"
        if saved.validation_status == "passed"
        else "not_run"
        if saved.validation_status == "not_run"
        else "failed"
    )
    return RunReport(
        report_kind="program0",
        run_id=str(manifest.run_id),
        run_timestamp=manifest.timestamp,
        input_release="CMS July 2025",
        scope="Program 0 only; three declared output artifacts",
        input_format=saved.input_format.value,
        code_origin="not_recorded",
        generation_status="not_recorded",
        execution_status=execution.status.value if execution else saved.status.value,
        collection_status=saved.status.value,
        validation_status=validation_status,
        validation_outcome=saved.validation_status,
        validation_failure_files=tuple(
            PROGRAM0_ARTIFACTS[name]
            for name in saved.validation_errors
            if name in PROGRAM0_ARTIFACTS
        ),
        exact_statistic_rows=evidence.exact_statistic_rows if evidence else (),
        evidence_integrity="not_confirmed" if issues else "matched",
        evidence_issues=tuple(sorted(set(issues))),
        docker_image_id=execution.runtime_environment.image_id
        if execution and execution.runtime_environment
        else None,
        runtime_seconds=execution.runtime_seconds if execution else None,
        exit_code=execution.exit_code if execution else None,
        artifacts=tuple(
            summarize_artifact(
                saved.validation_results.get(filename),
                name=name,
                authority="supplied_sas",
                policy=policies.get(name),
            )
            for filename, name in PROGRAM0_ARTIFACTS.items()
        ),
        evidence_hashes=hashes,
        first_observed_failures=tuple(
            name
            for filename, name in PROGRAM0_ARTIFACTS.items()
            if filename in saved.validation_results
            and not saved.validation_results[filename].passed
        ),
        not_checked=tuple(
            name
            for filename, name in PROGRAM0_ARTIFACTS.items()
            if filename not in saved.validation_results
        ),
        limitations=(
            "Program 1, Program 2, eligibility, clustering, and final ratings are not verified.",
            "Code origin and model generation are not established by these execution records.",
            "This summarizes saved comparisons without rerunning code or numerical validation.",
            "Older runs without validation snapshots cannot establish current verification.",
        ),
    )
