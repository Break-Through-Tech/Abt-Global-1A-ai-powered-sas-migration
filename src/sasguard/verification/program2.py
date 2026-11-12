"""Fixed host-only comparisons for Program 2 stars and national averages."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast

import pyreadstat
from pydantic import BaseModel, Field, JsonValue

from sasguard.config import load_project_configuration
from sasguard.data import ArtifactFormat, LoadedArtifact, load_artifact
from sasguard.provenance.hashing import hash_files, sha256_file
from sasguard.verification import ArtifactComparisonPolicy, compare_artifacts
from sasguard.verification.artifact import ArtifactComparison
from sasguard.verification.policy import ColumnComparisonPolicy, ComparisonKind

POLICY_PATH = "configs/program2-comparison-policies.json"
ARTIFACTS = {
    "star_2025jul.csv": "STAR_2025JUL",
    "national_average_2025jul.csv": "NATIONAL_AVERAGE_2025JUL",
}


class Program2Validation(BaseModel):
    """Retain every computable comparison, even when another file is malformed."""

    status: Literal["passed", "failed", "malformed_outputs"]
    comparisons: dict[str, ArtifactComparison] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)
    output_hashes: dict[str, str] = Field(default_factory=dict)
    feedback: dict[str, JsonValue] = Field(default_factory=dict)
    input_passthrough: ArtifactComparison | None = None


def load_program2_policies(root: Path) -> dict[str, ArtifactComparisonPolicy]:
    """Load a policy fixed before generation, with exact categorical/count decisions."""
    value = json.loads((root / POLICY_PATH).read_bytes())
    if value.get("schema_version") != 1 or set(value["artifacts"]) != set(ARTIFACTS.values()):
        raise ValueError("Program 2 policies must cover both target artifacts")
    return {
        name: ArtifactComparisonPolicy.model_validate(rule)
        for name, rule in value["artifacts"].items()
    }


def check_domain_passthrough(inputs: Path, output: Path) -> ArtifactComparison:
    """Require copied domain scores to equal the actual input, independently of SAS tolerance."""
    mapping = {
        "OUTCOME_MORTALITY": "STD_OUTCOMES_MORTALITY_SCORE",
        "OUTCOME_READMISSION": "STD_OUTCOMES_READMISSION_SCORE",
        "OUTCOME_SAFETY": "STD_OUTCOMES_SAFETY_SCORE",
        "PTEXP": "STD_PATIENTEXP_SCORE",
        "PROCESS": "STD_PROCESS_SCORE",
    }
    combined = None
    for name, column in mapping.items():
        frame = load_artifact(inputs / f"{name.lower()}.csv", key="PROVIDER_ID").frame
        selected = frame.loc[:, ["PROVIDER_ID", "GRP_SCORE"]].rename(columns={"GRP_SCORE": column})
        combined = (
            selected
            if combined is None
            else combined.merge(selected, on="PROVIDER_ID", how="outer", validate="one_to_one")
        )
    assert combined is not None
    actual = load_artifact(output / "star_2025jul.csv", key="PROVIDER_ID")
    columns = ["PROVIDER_ID", *mapping.values()]
    return compare_artifacts(
        replace(actual, frame=actual.frame.loc[:, columns]),
        LoadedArtifact(
            frame=combined, source_path=inputs, format=ArtifactFormat.CSV, key_column="PROVIDER_ID"
        ),
        artifact="PROGRAM2_INPUT_PASSTHROUGH",
        policy=ArtifactComparisonPolicy(
            keys=("PROVIDER_ID",),
            columns=tuple(
                ColumnComparisonPolicy(name=column, kind=ComparisonKind.EXACT)
                for column in mapping.values()
            ),
        ),
    )


def validate_program2(root: Path, output: Path) -> Program2Validation:
    """Compare data on the host; return only aggregate feedback to the model.

    National averages have one row and no natural key. A host-only row index aligns
    those rows without asking generated code to add a column. Extra rows still fail.
    Raw provider identifiers, values, logs, and exceptions never enter feedback.
    """
    paths = load_project_configuration(
        root / "configs/cms_2025jul.yaml", project_root=root
    ).resolve_paths(root)
    policies = load_program2_policies(root)
    frozen = hash_files(
        root,
        [
            POLICY_PATH,
            *[
                paths.reference_sas7bdat[name].relative_to(root).as_posix()
                for name in ARTIFACTS.values()
            ],
        ],
    )
    comparisons = {}
    errors = {}
    hashes = {}
    feedback: dict[str, JsonValue] = {}
    for filename, name in ARTIFACTS.items():
        reference = paths.reference_sas7bdat[name]
        _, metadata = pyreadstat.read_sas7bdat(reference, metadataonly=True)
        columns = [column.upper() for column in metadata.column_names]
        details: dict[str, JsonValue] = {
            "expected_columns": cast(JsonValue, columns),
            "expected_rows": metadata.number_rows,
            "comparison_policy": cast(JsonValue, policies[name].model_dump(mode="json")),
        }
        if name == "NATIONAL_AVERAGE_2025JUL":
            details["comparison_policy"] = {
                "row_alignment": "single row; no generated key column",
                "numeric_tolerance": {"absolute": 1e-12, "relative": 1e-12},
            }
        path = output / filename
        try:
            if path.is_symlink() or not path.is_file() or path.resolve().parent != output.resolve():
                raise ValueError("missing or unsafe output")
            before = sha256_file(path, normalize_text=False)
            actual = load_artifact(path)
            expected = load_artifact(
                reference, key="PROVIDER_ID" if name == "STAR_2025JUL" else None
            )
            details.update(
                {
                    "actual_rows": actual.row_count,
                    "missing_columns": cast(
                        JsonValue, [column for column in columns if column not in actual.columns]
                    ),
                    "unexpected_column_count": len(set(actual.columns) - set(columns)),
                }
            )
            if name == "NATIONAL_AVERAGE_2025JUL":
                if "__SASGUARD_ROW" in actual.columns:
                    raise ValueError("reserved host row key supplied by candidate")
                actual = replace(
                    actual,
                    frame=actual.frame.assign(
                        __SASGUARD_ROW=[str(row) for row in range(actual.row_count)]
                    ),
                )
                expected = replace(
                    expected,
                    frame=expected.frame.assign(
                        __SASGUARD_ROW=[str(row) for row in range(expected.row_count)]
                    ),
                )
            compared = compare_artifacts(actual, expected, artifact=name, policy=policies[name])
            comparisons[name] = compared
            details.update(
                {
                    "passed": compared.passed,
                    "mismatched_cells": compared.mismatched_cells,
                    "mismatched_columns": cast(JsonValue, compared.mismatched_columns),
                    "missingness_mismatches": compared.missingness_mismatches,
                    "missing_key_count": len(compared.missing_keys),
                    "extra_key_count": len(compared.extra_keys),
                    "max_abs_error": compared.max_abs_error,
                }
            )
            if sha256_file(path, normalize_text=False) != before:
                raise ValueError("output changed during comparison")
            hashes[filename] = before
        except (OSError, ValueError, KeyError):
            errors[name] = "missing_or_malformed_output"
            details["status"] = "missing_or_malformed_output"
        feedback[name] = details
    if hash_files(root, frozen) != frozen:
        raise ValueError("Program 2 policy or references changed during validation")
    return Program2Validation(
        status="malformed_outputs"
        if errors
        else "passed"
        if len(comparisons) == 2 and all(item.passed for item in comparisons.values())
        else "failed",
        comparisons=comparisons,
        errors=errors,
        output_hashes=hashes,
        feedback=feedback,
    )
