"""Host-side validation of Program 0 output CSVs against the trusted SAS artifacts.

The validator runs on the host after candidate execution has finished. It never runs
candidate code and never copies trusted artifacts into a candidate's run directory.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sasguard.config import load_project_configuration
from sasguard.data import ArtifactLoadError, LoadedArtifact, load_artifact
from sasguard.provenance.hashing import sha256_file, validate_sha256
from sasguard.verification.artifact import ArtifactComparison
from sasguard.verification.comparator import ComparisonInputError, compare_artifacts
from sasguard.verification.policy import (
    ArtifactComparisonPolicy,
    ColumnComparisonPolicy,
    ComparisonKind,
)

CONFIG_PATH = Path("configs/cms_2025jul.yaml")
POLICY_PATH = Path("configs/program0-comparison-policies.json")
EXACT_STATISTIC_ROWS = ("N", "MIN", "MAX")

# Output CSV filename -> trusted SAS artifact name in the project configuration.
PROGRAM0_ARTIFACTS: dict[str, str] = {
    "less100_measure.csv": "LESS100_MEASURE",
    "measure_average_stddev_2025jul.csv": "MEASURE_AVERAGE_STDDEV_2025JUL",
    "std_data_2025jul_analysis.csv": "STD_DATA_2025JUL_ANALYSIS",
}

Program0ValidationStatus = Literal[
    "passed", "failed", "hash_mismatch", "missing_outputs", "malformed_outputs"
]


class Program0Validation(BaseModel):
    """Outcome of validating the three Program 0 outputs.

    ``artifact_results`` maps each output filename to its SAS comparison. It is filled
    only when all three files could be compared. ``errors`` maps a filename to a short
    reason when a file is missing, changed after collection, or unreadable.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Program0ValidationStatus
    artifact_results: dict[str, ArtifactComparison] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "passed"


def load_program0_policies(project_root: Path) -> dict[str, ArtifactComparisonPolicy]:
    """Load the committed per-artifact comparison policies."""
    payload = json.loads((project_root / POLICY_PATH).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported Program 0 policy schema version")
    if payload.get("exact_statistic_rows") != list(EXACT_STATISTIC_ROWS):
        raise ValueError("Program 0 statistics require exact N, MIN, and MAX rows")
    artifacts = payload.get("artifacts", {})
    if set(artifacts) != set(PROGRAM0_ARTIFACTS.values()):
        raise ValueError("Program 0 policies must cover exactly the three Program 0 artifacts")
    return {
        name: ArtifactComparisonPolicy.model_validate(policy) for name, policy in artifacts.items()
    }


def _compare_statistics(
    actual: LoadedArtifact, expected: LoadedArtifact, policy: ArtifactComparisonPolicy
) -> ArtifactComparison:
    """Counts and selected raw extrema are exact; computed moments keep their tolerance."""
    artifact = "MEASURE_AVERAGE_STDDEV_2025JUL"
    key = "_STAT_"
    if policy.keys != (key,):
        raise ValueError("Program 0 statistics must align by _STAT_")
    exact_policy = ArtifactComparisonPolicy(
        keys=policy.keys,
        columns=tuple(
            ColumnComparisonPolicy(name=name, kind=ComparisonKind.EXACT)
            for name in dict.fromkeys((*expected.columns, *actual.columns))
            if name != key
        ),
    )
    checks = []
    for exact in (True, False):
        actual_rows = actual.frame[key].isin(EXACT_STATISTIC_ROWS)
        expected_rows = expected.frame[key].isin(EXACT_STATISTIC_ROWS)
        checks.append(
            compare_artifacts(
                replace(actual, frame=actual.frame.loc[actual_rows if exact else ~actual_rows]),
                replace(
                    expected, frame=expected.frame.loc[expected_rows if exact else ~expected_rows]
                ),
                artifact=artifact,
                policy=exact_policy if exact else policy,
            )
        )
    strict, numeric = checks
    mismatched = set(strict.mismatched_columns) | set(numeric.mismatched_columns)
    return ArtifactComparison(
        artifact=artifact,
        passed=all(check.passed for check in checks),
        reference_source=numeric.reference_source,
        expected_rows=expected.row_count,
        actual_rows=actual.row_count,
        expected_columns=list(expected.columns),
        actual_columns=list(actual.columns),
        missing_keys=sorted({key for check in checks for key in check.missing_keys}),
        extra_keys=sorted({key for check in checks for key in check.extra_keys}),
        missing_columns=numeric.missing_columns,
        extra_columns=numeric.extra_columns,
        mismatched_columns=[name for name in expected.columns if name in mismatched],
        exact_cells=sum(check.exact_cells for check in checks),
        mismatched_cells=sum(check.mismatched_cells for check in checks),
        missingness_mismatches=sum(check.missingness_mismatches for check in checks),
        max_abs_error=numeric.max_abs_error,
        mean_abs_error=numeric.mean_abs_error,
    )


def validate_program0_outputs(
    project_root: Path,
    output_directory: Path,
    expected_sha256: Mapping[str, str],
) -> Program0Validation:
    """Validate the three Program 0 CSVs in ``output_directory`` against SAS.

    ``expected_sha256`` maps each output filename to the hash recorded when the files
    were collected. Files are checked in this order, stopping at the first failing stage:
    presence, hash, readability, then keyed comparison with each artifact's policy.

    Raises ``ValueError`` if ``expected_sha256`` does not name exactly the three outputs,
    because that is a caller error rather than a candidate failure.
    """
    if set(expected_sha256) != set(PROGRAM0_ARTIFACTS):
        raise ValueError(
            f"expected_sha256 must name exactly these outputs: {sorted(PROGRAM0_ARTIFACTS)}"
        )
    expected_hashes = {name: validate_sha256(value) for name, value in expected_sha256.items()}
    root = project_root.resolve()
    output = output_directory.resolve()

    # Symlinks are rejected so a candidate cannot point the validator at another file.
    missing = {
        name: "file is missing"
        for name in PROGRAM0_ARTIFACTS
        if (output / name).is_symlink() or not (output / name).is_file()
    }
    if missing:
        return Program0Validation(status="missing_outputs", errors=missing)

    changed = {
        name: "SHA-256 differs from the hash recorded at collection"
        for name in PROGRAM0_ARTIFACTS
        if sha256_file(output / name) != expected_hashes[name]
    }
    if changed:
        return Program0Validation(status="hash_mismatch", errors=changed)

    policies = load_program0_policies(root)
    paths = load_project_configuration(root / CONFIG_PATH, project_root=root).resolve_paths(root)

    results: dict[str, ArtifactComparison] = {}
    malformed: dict[str, str] = {}
    for filename, artifact in PROGRAM0_ARTIFACTS.items():
        policy = policies[artifact]
        key = policy.keys[0]
        try:
            actual = load_artifact(output / filename, key=key)
            expected = load_artifact(paths.reference_sas7bdat[artifact], key=key)
            results[filename] = (
                _compare_statistics(actual, expected, policy)
                if artifact == "MEASURE_AVERAGE_STDDEV_2025JUL"
                else compare_artifacts(actual, expected, artifact=artifact, policy=policy)
            )
        except (ArtifactLoadError, ComparisonInputError, ValueError) as error:
            malformed[filename] = str(error)

    if malformed:
        return Program0Validation(status="malformed_outputs", errors=malformed)
    status: Program0ValidationStatus = (
        "passed" if all(result.passed for result in results.values()) else "failed"
    )
    return Program0Validation(status=status, artifact_results=results)
