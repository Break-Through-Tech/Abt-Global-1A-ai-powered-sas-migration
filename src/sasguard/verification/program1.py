"""Host-side validation of the five Program 1 domain outputs against the trusted SAS artifacts.

The validator runs on the host after Program 1 has finished. It never runs candidate code.
Each domain is compared with its SAS binary under ``configs/program1-comparison-policies.json``
(PROVIDER_ID keys, exact flags and counts, 1e-12 absolute and relative tolerance for
calculated values). When the actual Program 0 analysis output is supplied, every domain's
copied standardized measures must also equal it exactly, independent of SAS tolerance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sasguard.config import load_project_configuration
from sasguard.data import ArtifactLoadError, load_artifact
from sasguard.prototypes.program01 import _copy_check
from sasguard.provenance.hashing import sha256_file
from sasguard.release import JULY_2025, Release
from sasguard.verification.artifact import ArtifactComparison
from sasguard.verification.comparator import ComparisonInputError, compare_artifacts
from sasguard.verification.policy import ArtifactComparisonPolicy

POLICY_PATH = Path("configs/program1-comparison-policies.json")
KEY = "PROVIDER_ID"

# Output CSV filename -> trusted SAS artifact name in the project configuration.
PROGRAM1_ARTIFACTS: dict[str, str] = {
    "outcome_mortality.csv": "OUTCOME_MORTALITY",
    "outcome_safety.csv": "OUTCOME_SAFETY",
    "outcome_readmission.csv": "OUTCOME_READMISSION",
    "ptexp.csv": "PTEXP",
    "process.csv": "PROCESS",
}

Program1ValidationStatus = Literal[
    "passed", "failed", "handoff_failed", "missing_outputs", "malformed_outputs"
]


class Program1Validation(BaseModel):
    """Outcome of validating the five Program 1 outputs.

    ``artifact_results`` maps each output filename to its SAS comparison and
    ``input_passthrough`` to its exact copied-input comparison against the actual Program 0
    output. ``handoff_failed`` means every SAS comparison passed but a copied measure
    differs from the Program 0 output that was supposed to be consumed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Program1ValidationStatus
    artifact_results: dict[str, ArtifactComparison] = Field(default_factory=dict)
    input_passthrough: dict[str, ArtifactComparison] = Field(default_factory=dict)
    output_hashes: dict[str, str] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "passed"


def load_program1_policies(
    project_root: Path, release: Release = JULY_2025
) -> dict[str, ArtifactComparisonPolicy]:
    """Load the committed per-domain comparison policies, keyed for ``release`` by role."""
    payload = json.loads((project_root / POLICY_PATH).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported Program 1 policy schema version")
    artifacts = payload.get("artifacts", {})
    if set(artifacts) != set(PROGRAM1_ARTIFACTS.values()):
        raise ValueError("Program 1 policies must cover exactly the five Program 1 artifacts")
    return release.policies_by_release_artifact(
        {
            name: ArtifactComparisonPolicy.model_validate(policy)
            for name, policy in artifacts.items()
        }
    )


def find_output_file(directory: Path, filename: str) -> Path | None:
    """Return the regular file for ``filename`` ignoring case, or None.

    Program 1 writers use either upper- or lowercase artifact names. Symlinks are
    rejected so a candidate cannot point the validator at another file.
    """
    if not directory.is_dir():
        return None
    for entry in sorted(directory.iterdir()):
        if entry.name.casefold() == filename.casefold():
            return None if entry.is_symlink() or not entry.is_file() else entry
    return None


def validate_program1_outputs(
    project_root: Path,
    output_directory: Path,
    program0_analysis: Path | None = None,
    release: Release = JULY_2025,
) -> Program1Validation:
    """Validate the five Program 1 CSVs in ``output_directory`` against SAS.

    Presence is checked first, then readability, then the keyed SAS comparison for each
    domain. Every computable comparison is retained even when another file is malformed.
    With ``program0_analysis`` (the actual Python Program 0 analysis CSV), copied
    standardized measures are also compared exactly with that file.
    """
    root = project_root.resolve()
    policies = load_program1_policies(root, release)
    paths = load_project_configuration(root / release.config_path, project_root=root).resolve_paths(
        root
    )

    located = {name: find_output_file(output_directory, name) for name in PROGRAM1_ARTIFACTS}
    missing = {name: "file is missing" for name, path in located.items() if path is None}
    if missing:
        return Program1Validation(status="missing_outputs", errors=missing)

    results: dict[str, ArtifactComparison] = {}
    copies: dict[str, ArtifactComparison] = {}
    hashes: dict[str, str] = {}
    errors: dict[str, str] = {}
    input_data = None
    if program0_analysis is not None:
        try:
            input_data = load_artifact(program0_analysis, key=KEY)
        except (OSError, ArtifactLoadError, ValueError) as error:
            errors["program0_analysis"] = str(error)
    for filename, artifact in PROGRAM1_ARTIFACTS.items():
        path = located[filename]
        assert path is not None
        try:
            before = sha256_file(path, normalize_text=False)
            actual = load_artifact(path, key=KEY)
            expected = load_artifact(paths.reference_sas7bdat[artifact], key=KEY)
            results[filename] = compare_artifacts(
                actual, expected, artifact=artifact, policy=policies[artifact]
            )
            if input_data is not None:
                copies[filename] = _copy_check(actual, input_data, artifact)
            if sha256_file(path, normalize_text=False) != before:
                raise ValueError("output changed during comparison")
            hashes[filename] = before
        except (OSError, ArtifactLoadError, ComparisonInputError, ValueError, KeyError) as error:
            errors[filename] = f"{type(error).__name__}: {error}"
    if any(name in PROGRAM1_ARTIFACTS for name in errors):
        return Program1Validation(
            status="malformed_outputs",
            artifact_results=results,
            input_passthrough=copies,
            output_hashes=hashes,
            errors=errors,
        )
    status: Program1ValidationStatus = "passed"
    if not all(result.passed for result in results.values()):
        status = "failed"
    elif "program0_analysis" in errors or not all(item.passed for item in copies.values()):
        status = "handoff_failed"
    return Program1Validation(
        status=status,
        artifact_results=results,
        input_passthrough=copies,
        output_hashes=hashes,
        errors=errors,
    )
