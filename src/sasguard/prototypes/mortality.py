"""Trusted controller for the bounded human-reference Mortality demonstration."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from sasguard.config import load_project_configuration
from sasguard.data import load_artifact
from sasguard.execution.manifest import RunManifest
from sasguard.execution.result import ExecutionStatus
from sasguard.execution.runner import DockerExecutionRunner
from sasguard.provenance.hashing import hash_files, sha256_file
from sasguard.verification import ArtifactComparison, ArtifactComparisonPolicy, compare_artifacts
from sasguard.verification.golden_trace import trace_artifacts
from sasguard.verification.integrity import load_and_verify_integrity
from sasguard.verification.lineage import ArtifactLineage

# This bounded baseline accepts only these reviewed configurations. Updating a
# policy requires a corresponding trusted-controller change, never an automatic repair.
_TRUSTED_CONFIGURATION_HASHES = {
    "configs/cms_2025jul.yaml": "d6e16a00a5cc86a2e36079d2dc59dd2ced072f50d4595e4a823575fe80c3a64a",
    "configs/mortality-comparison-policy.json": (
        "632173ce570b38b26ff4f3953474335154f33d3d97dd22492abcca7873a60a26"
    ),
    "configs/cms-artifact-lineage.json": (
        "a9c9a5ceeece017be09332c7612c7dd074f2bfa17098398920ce337520776baf"
    ),
}


def _require_frozen_configuration(project_root: Path) -> None:
    observed = hash_files(project_root, _TRUSTED_CONFIGURATION_HASHES)
    if observed != _TRUSTED_CONFIGURATION_HASHES:
        raise ValueError("Mortality configuration differs from the frozen controller baseline")


def mortality_policy(project_root: Path) -> ArtifactComparisonPolicy:
    """Load the committed artifact-specific policy before executing the reference."""
    _require_frozen_configuration(project_root)
    return ArtifactComparisonPolicy.model_validate_json(
        (project_root / "configs" / "mortality-comparison-policy.json").read_text(encoding="utf-8")
    )


def run_mortality_prototype(
    project_root: Path,
    *,
    image: str = "sasguard-runner:test",
) -> tuple[ArtifactComparison, Path]:
    """Stage Program 0 input, run Docker, and validate outside the isolated container.

    Returns the structured comparison and report path. Runner failures and integrity
    failures stop the workflow before validation. Analytical mismatches remain in the report.
    """
    root = project_root.resolve()
    policy = mortality_policy(root)
    lineage = ArtifactLineage.model_validate_json(
        (root / "configs" / "cms-artifact-lineage.json").read_text(encoding="utf-8")
    )
    integrity = load_and_verify_integrity(root, root / "configs" / "protected-artifacts.json")
    if not integrity.passed:
        raise ValueError("protected-artifact integrity failed before the Mortality run")
    config = load_project_configuration(root / "configs" / "cms_2025jul.yaml", project_root=root)
    paths = config.resolve_paths(root)
    reference = paths.reference_sas7bdat["OUTCOME_MORTALITY"]
    intermediate = paths.reference_sas7bdat["STD_DATA_2025JUL_ANALYSIS"]
    run_directory = (root / "reports" / "runs" / f"mortality-{uuid4()}").resolve()
    if not run_directory.is_relative_to(root):
        raise ValueError("Mortality report directory must stay within the repository")
    staged_input = run_directory / "input"
    staged_source = run_directory / "source"
    output = run_directory / "output"
    staged_input.mkdir(parents=True)
    staged_source.mkdir()
    shutil.copyfile(intermediate, staged_input / intermediate.name)
    source = root / "reference_python" / "mortality.py"
    shutil.copyfile(source, staged_source / source.name)
    source_hashes = hash_files(
        root,
        [
            path.relative_to(root).as_posix()
            for path in (
                *paths.programs,
                *paths.macros,
                source,
                root / "configs" / "cms_2025jul.yaml",
                root / "configs" / "mortality-comparison-policy.json",
                root / "configs" / "cms-artifact-lineage.json",
            )
        ],
    )
    input_hashes = hash_files(root, [intermediate.relative_to(root).as_posix()])
    if sha256_file(staged_input / intermediate.name) != next(iter(input_hashes.values())):
        raise ValueError("staged Mortality input does not match its supplied source")
    if (
        sha256_file(staged_source / source.name)
        != source_hashes[source.relative_to(root).as_posix()]
    ):
        raise ValueError("staged Mortality code does not match its reference implementation")
    manifest = RunManifest.create(source_hashes=source_hashes, input_hashes=input_hashes)
    manifest_path = run_directory / "manifest.json"
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    trace_path = run_directory / "trace.json"
    initial_trace = trace_artifacts(
        lineage,
        [],
        scope="Program 1 Mortality only, supplied Program 0 intermediate",
        supplied_reference_inputs=["STD_DATA_2025JUL_ANALYSIS"],
    )
    trace_path.write_text(initial_trace.to_json(), encoding="utf-8")

    execution = DockerExecutionRunner(image=image).run(
        source_directory=staged_source,
        input_directory=staged_input,
        output_directory=output,
        script="mortality.py",
        forbidden_host_paths=(paths.reference_sas7bdat_directory, paths.reference_csv_directory),
    )
    (run_directory / "execution.json").write_text(
        execution.model_dump_json(indent=2), encoding="utf-8"
    )
    manifest = manifest.with_execution_result(execution)
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    after = load_and_verify_integrity(root, root / "configs" / "protected-artifacts.json")
    if not after.passed:
        raise ValueError("protected-artifact integrity failed after the Mortality run")
    _require_frozen_configuration(root)
    if execution.status is not ExecutionStatus.SUCCEEDED:
        raise RuntimeError(f"Mortality execution failed: {execution.status}; see {run_directory}")

    actual = load_artifact(output / "OUTCOME_MORTALITY.csv", key=config.project.key)
    expected = load_artifact(reference, key=config.project.key)
    comparison = compare_artifacts(actual, expected, artifact="OUTCOME_MORTALITY", policy=policy)
    trace = trace_artifacts(
        lineage,
        [comparison],
        scope="Program 1 Mortality only, supplied Program 0 intermediate",
        supplied_reference_inputs=["STD_DATA_2025JUL_ANALYSIS"],
    )
    trace_path.write_text(trace.to_json(), encoding="utf-8")
    report_path = run_directory / "comparison.json"
    report = {
        "schema_version": 1,
        "implementation": "human_reference",
        "scope": "Program 1 Mortality only, supplied Program 0 intermediate",
        "input_artifact": "STD_DATA_2025JUL_ANALYSIS",
        "reference_artifact": "OUTCOME_MORTALITY",
        "runner_image": image,
        "reference_sha256": sha256_file(reference),
        "output_sha256": sha256_file(output / "OUTCOME_MORTALITY.csv"),
        "trace_report": "trace.json",
        "policy": policy.model_dump(mode="json"),
        "comparison": comparison.model_dump(mode="json"),
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    after = load_and_verify_integrity(root, root / "configs" / "protected-artifacts.json")
    if not after.passed:
        raise ValueError("protected-artifact integrity failed after the Mortality run")
    _require_frozen_configuration(root)
    manifest = manifest.model_copy(
        update={
            "reference_sources": {comparison.artifact: comparison.reference_source},
            "artifact_results": {comparison.artifact: comparison},
        }
    )
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    return comparison, report_path
