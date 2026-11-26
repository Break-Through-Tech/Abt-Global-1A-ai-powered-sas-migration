"""Read-only structural and aggregate feedback for Program 0 repair requests."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pyreadstat
from pydantic import JsonValue

from sasguard.config import load_project_configuration
from sasguard.data import load_artifact
from sasguard.execution.program0 import CandidateReport
from sasguard.prototypes.program0_prompt import _selected_file
from sasguard.provenance.hashing import hash_files, sha256_file
from sasguard.verification.artifact import ArtifactComparison
from sasguard.verification.comparator import compare_artifacts
from sasguard.verification.program0 import (
    PROGRAM0_ARTIFACTS,
    _compare_statistics,
    load_program0_policies,
)


def _aggregate(comparison: ArtifactComparison) -> dict[str, JsonValue]:
    return {
        "status": "compared",
        "passed": comparison.passed,
        "expected_rows": comparison.expected_rows,
        "actual_rows": comparison.actual_rows,
        "missing_key_count": len(comparison.missing_keys),
        "extra_key_count": len(comparison.extra_keys),
        "mismatched_columns": cast(JsonValue, comparison.mismatched_columns),
        "mismatched_cells": comparison.mismatched_cells,
        "missingness_mismatches": comparison.missingness_mismatches,
        "max_abs_error": comparison.max_abs_error,
    }


def structural_feedback(
    project_root: Path, output_directory: Path, report: CandidateReport
) -> dict[str, JsonValue]:
    """Describe schemas and each artifact independently without changing validation.

    The shared validator discards partial results when one artifact is malformed. Reuse
    its exact comparisons for diagnostic purposes only, so a missing key in one output
    does not hide failures in another. Never serialize row keys, raw values, candidate
    column names outside the trusted schema, or exception messages.
    """
    root, output = project_root.resolve(), output_directory.resolve()
    evidence = report.validation_evidence
    if evidence is None or set(report.artifacts) != set(PROGRAM0_ARTIFACTS):
        raise ValueError("structural feedback requires collected outputs and validation evidence")
    if output.parent.parent != (root / "reports/runs").resolve() or output.name != "output":
        raise ValueError("structural feedback requires a saved candidate output directory")
    hashes = {name: artifact.sha256 for name, artifact in report.artifacts.items()}
    if evidence.output_hashes != hashes:
        raise ValueError("diagnostic output records disagree")

    def unchanged() -> bool:
        return (
            hash_files(root, evidence.project_hashes) == evidence.project_hashes
            and all(
                sha256_file(_selected_file(output, name)) == digest
                for name, digest in hashes.items()
            )
            and sha256_file(_selected_file(output.parent, "source/main.py"))
            == evidence.candidate_sha256
        )

    if not unchanged():
        raise ValueError("diagnostic evidence changed")
    paths = load_project_configuration(
        root / "configs/cms_2025jul.yaml", project_root=root
    ).resolve_paths(root)
    policies = load_program0_policies(root)
    if policies != evidence.policies:
        raise ValueError("diagnostic policy differs from recorded validation")
    structures: dict[str, JsonValue] = {}
    comparisons: dict[str, JsonValue] = {}
    first_failure = None
    for filename, artifact in PROGRAM0_ARTIFACTS.items():
        policy = policies[artifact]
        reference = paths.reference_sas7bdat[artifact]
        _, metadata = pyreadstat.read_sas7bdat(reference, metadataonly=True)
        expected_columns = [name.upper() for name in metadata.column_names]
        actual_columns = {name.upper() for name in report.artifacts[filename].columns}
        expected_set = set(expected_columns)
        missing = [name for name in expected_columns if name not in actual_columns]
        missing_keys = [name for name in policy.keys if name not in actual_columns]
        structures[filename] = {
            "reference_metadata_source": "supplied_sas_metadata",
            "expected_rows": metadata.number_rows,
            "actual_rows": report.artifacts[filename].rows,
            "expected_columns": cast(JsonValue, expected_columns),
            "expected_key_columns": cast(JsonValue, list(policy.keys)),
            "missing_key_columns": cast(JsonValue, missing_keys),
            "missing_columns": cast(JsonValue, missing),
            "actual_column_count": len(actual_columns),
            "unexpected_column_count": len(actual_columns - expected_set),
            "comparison_policy": cast(JsonValue, policy.model_dump(mode="json")),
            "exact_statistic_rows": cast(JsonValue, list(evidence.exact_statistic_rows))
            if artifact == "MEASURE_AVERAGE_STDDEV_2025JUL"
            else [],
        }
        checked = report.validation_results.get(filename)
        if checked is None:
            try:
                actual = load_artifact(output / filename, key=policy.keys[0])
                expected = load_artifact(reference, key=policy.keys[0])
                checked = (
                    _compare_statistics(actual, expected, policy)
                    if artifact == "MEASURE_AVERAGE_STDDEV_2025JUL"
                    else compare_artifacts(actual, expected, artifact=artifact, policy=policy)
                )
            except (OSError, ValueError, KeyError):
                # The structural record already identifies missing columns/keys. Error
                # text can contain provider identifiers and is never sent to the model.
                checked = None
        comparisons[filename] = _aggregate(checked) if checked else {"status": "not_comparable"}
        if first_failure is None and (
            missing
            or len(actual_columns - expected_set)
            or report.artifacts[filename].rows != metadata.number_rows
            or checked is None
            or not checked.passed
        ):
            first_failure = filename
    if not unchanged():
        raise ValueError("diagnostic evidence changed while reading")
    return {
        "diagnostic_version": "program0-aggregate-v2",
        "artifact_structure": structures,
        "independent_artifact_comparisons": comparisons,
        "first_observed_failed_artifact": first_failure,
        "validation_authority": "original_candidate_report; diagnostics do not change its result",
    }
