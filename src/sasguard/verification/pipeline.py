"""Full-pipeline validation: Program 0 -> Program 1 -> Program 2 on actual Python outputs.

The validator is host-only. It never executes candidate code and never copies trusted
artifacts into a candidate environment. Each stage is given as a directory of actual
output CSVs plus an explicit declaration of where that output came from. Every stage is
compared with the supplied SAS artifacts under its fixed policy, and every handoff is
checked exactly: Program 1's copied measures must equal the Program 0 output on disk, and
Program 2's copied domain scores must equal the Program 1 outputs on disk.

Summary status:

* ``PASS``: all ten artifact comparisons, both handoffs, the policy audit, and the
  before/after integrity checks passed.
* ``PARTIAL``: at least one but not all ten artifact comparisons passed (or a handoff
  failed). This is never full-pipeline parity.
* ``FAIL``: no artifact comparison passed, or integrity or the policy audit failed.

The earliest divergence is the first failure in stage order (Program 0, 1, 2), artifact
order, then the first differing column and key. Failures in later stages that follow an
earlier failure are reported as upstream failures rather than as that stage's own bug.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import replace
from enum import StrEnum
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from sasguard.columns import resolve_column_name
from sasguard.config import ResolvedProjectPaths, load_project_configuration
from sasguard.data import ArtifactLoadError, LoadedArtifact, load_artifact
from sasguard.provenance.hashing import sha256_file
from sasguard.verification.artifact import ArtifactComparison
from sasguard.verification.comparator import ComparisonInputError, compare_artifacts
from sasguard.verification.integrity import load_and_verify_integrity
from sasguard.verification.policy import ArtifactComparisonPolicy
from sasguard.verification.program0 import (
    PROGRAM0_ARTIFACTS,
    _compare_statistics,
    load_program0_policies,
    validate_program0_outputs,
)
from sasguard.verification.program1 import (
    PROGRAM1_ARTIFACTS,
    find_output_file,
    load_program1_policies,
    validate_program1_outputs,
)
from sasguard.verification.program2 import (
    ARTIFACTS as PROGRAM2_ARTIFACTS,
)
from sasguard.verification.program2 import (
    check_domain_passthrough,
    load_program2_policies,
    validate_program2,
)

CONFIG_PATH = "configs/cms_2025jul.yaml"
INTEGRITY_PATH = "configs/protected-artifacts.json"
POLICY_PATHS = {
    0: "configs/program0-comparison-policies.json",
    1: "configs/program1-comparison-policies.json",
    2: "configs/program2-comparison-policies.json",
}
ANALYSIS_FILENAME = "std_data_2025jul_analysis.csv"
TOTAL_ARTIFACTS = 10
FIXED_TOLERANCE = 1e-12
DOMAIN_SCORE_COLUMNS = {
    "OUTCOME_MORTALITY": "STD_OUTCOMES_MORTALITY_SCORE",
    "OUTCOME_READMISSION": "STD_OUTCOMES_READMISSION_SCORE",
    "OUTCOME_SAFETY": "STD_OUTCOMES_SAFETY_SCORE",
    "PTEXP": "STD_PATIENTEXP_SCORE",
    "PROCESS": "STD_PROCESS_SCORE",
}

PipelineStatus = Literal["PASS", "PARTIAL", "FAIL"]
StageStatus = Literal[
    "passed",
    "failed",
    "handoff_failed",
    "missing_outputs",
    "malformed_outputs",
    "upstream_failure",
]
DivergenceKind = Literal[
    "missing_output",
    "malformed_output",
    "schema",
    "keys",
    "value",
    "handoff",
    "integrity",
    "policy",
]
Compare = Callable[[LoadedArtifact, LoadedArtifact], ArtifactComparison]


class StageSource(StrEnum):
    """Where one stage's actual output came from."""

    HUMAN_REFERENCE = "human_reference"
    DIRECT_MODEL_OUTPUT = "direct_model_output"
    HELPER_ASSISTED_MODEL_OUTPUT = "helper_assisted_model_output"
    MANUALLY_CORRECTED_MODEL_OUTPUT = "manually_corrected_model_output"


class StageInput(BaseModel):
    """One stage's declared source and the directory holding its actual outputs."""

    model_config = ConfigDict(extra="forbid")

    source: StageSource
    output_directory: Path
    code_path: Path | None = None
    note: str = ""


class Divergence(BaseModel):
    """The earliest observed disagreement."""

    model_config = ConfigDict(extra="forbid")

    stage: int
    program: str
    artifact: str
    kind: DivergenceKind
    column: str | None = None
    key: str | None = None
    detail: str = ""


class ArtifactOutcome(BaseModel):
    """One of the ten declared artifacts."""

    model_config = ConfigDict(extra="forbid")

    artifact: str
    filename: str
    passed: bool
    comparison: ArtifactComparison | None = None
    error: str | None = None


class StageResult(BaseModel):
    """Per-stage evidence with explicit source flags."""

    model_config = ConfigDict(extra="forbid")

    stage: int
    program: str
    source: StageSource
    human_reference: bool
    direct_model_output: bool
    helper_assisted_model_output: bool
    manually_corrected_model_output: bool
    note: str = ""
    output_directory: str
    status: StageStatus
    own_status: StageStatus
    artifacts: list[ArtifactOutcome] = Field(default_factory=list)
    handoff: list[ArtifactComparison] = Field(default_factory=list)
    handoff_error: str | None = None
    errors: dict[str, str] = Field(default_factory=dict)
    source_hashes: dict[str, str] = Field(default_factory=dict)
    input_hashes: dict[str, str] = Field(default_factory=dict)
    output_hashes: dict[str, str] = Field(default_factory=dict)

    @property
    def artifacts_passed(self) -> int:
        return sum(item.passed for item in self.artifacts)

    @property
    def handoff_passed(self) -> bool:
        """True when the exact copied-input check ran and passed (Program 0 has none)."""
        return self.stage == 0 or (
            bool(self.handoff)
            and self.handoff_error is None
            and all(item.passed for item in self.handoff)
        )


class PipelineValidation(BaseModel):
    """Complete record of one full-pipeline validation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    status: PipelineStatus
    artifacts_passed: int
    artifacts_total: int = TOTAL_ARTIFACTS
    passed_by_program: dict[str, int]
    star_mismatches: int | None
    stages: list[StageResult]
    earliest_divergence: Divergence | None
    integrity_before: dict[str, int | bool]
    integrity_after: dict[str, int | bool]
    policy_audit: list[str]
    policy_hashes: dict[str, str]
    sas_reference_hashes: dict[str, str]
    environment: dict[str, str]
    environment_sha256: str
    scope: str = "CMS July 2025; supplied SAS artifacts only"
    full_pipeline_parity: bool
    human_review: Literal["not_recorded"] = "not_recorded"


def derive_status(
    *, artifacts_passed: int, handoffs_passed: bool, integrity_passed: bool, audit_passed: bool
) -> PipelineStatus:
    """PASS needs all ten artifacts and every other check; a partial match is never PASS."""
    if not integrity_passed or not audit_passed or artifacts_passed == 0:
        return "FAIL"
    if artifacts_passed == TOTAL_ARTIFACTS and handoffs_passed:
        return "PASS"
    return "PARTIAL"


def audit_policies(root: Path) -> list[str]:
    """Return problems with the fixed 1e-12 absolute and relative tolerance contract."""
    problems: list[str] = []
    groups: dict[str, dict[str, ArtifactComparisonPolicy]] = {
        POLICY_PATHS[0]: load_program0_policies(root),
        POLICY_PATHS[1]: load_program1_policies(root),
        POLICY_PATHS[2]: load_program2_policies(root),
    }
    allowed = {(0.0, 0.0), (FIXED_TOLERANCE, FIXED_TOLERANCE)}
    for path, policies in groups.items():
        for artifact, policy in policies.items():
            tolerances = [("default", policy.default_numeric_tolerance)]
            tolerances.extend(
                (rule.name, rule.tolerance) for rule in policy.columns if rule.tolerance
            )
            for name, tolerance in tolerances:
                pair = (tolerance.absolute, tolerance.relative)
                if pair not in allowed:
                    problems.append(f"{path}:{artifact}:{name} tolerance {pair}")
    return problems


def _hash_or_none(path: Path) -> str | None:
    try:
        return sha256_file(path, normalize_text=False)
    except OSError:
        return None


def _git_commit(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def collect_environment(root: Path) -> dict[str, str]:
    """Record the interpreter, platform, key package versions and checkout commit."""
    packages = {}
    for name in ("sasguard", "pandas", "numpy", "pyreadstat", "pydantic", "scipy"):
        try:
            packages[f"package_{name}"] = version(name)
        except PackageNotFoundError:
            packages[f"package_{name}"] = "not installed"
    return {
        "python_version": platform.python_version(),
        "python_implementation": sys.implementation.name,
        "operating_system": f"{platform.system()} {platform.release()} {platform.version()}",
        "architecture": platform.machine(),
        "git_commit": _git_commit(root),
        **packages,
    }


def _integrity(root: Path) -> dict[str, int | bool]:
    try:
        result = load_and_verify_integrity(root, root / INTEGRITY_PATH)
    except (OSError, ValueError):
        return {"passed": False, "expected_files": 0, "checked_files": 0}
    return {
        "passed": result.passed,
        "expected_files": result.expected_files,
        "checked_files": result.checked_files,
    }


def _source_hashes(root: Path, stage: StageInput, human_files: tuple[str, ...]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    if stage.source is StageSource.HUMAN_REFERENCE:
        for relative in human_files:
            if (digest := _hash_or_none(root / relative)) is not None:
                hashes[relative] = digest
    if stage.code_path is not None and (digest := _hash_or_none(stage.code_path)) is not None:
        hashes[f"candidate:{stage.code_path.name}"] = digest
    return hashes


def _outcomes(
    filenames: dict[str, str],
    comparisons: dict[str, ArtifactComparison],
    errors: dict[str, str],
) -> list[ArtifactOutcome]:
    outcomes = []
    for filename, artifact in filenames.items():
        comparison = comparisons.get(filename) or comparisons.get(artifact)
        error = errors.get(filename) or errors.get(artifact)
        outcomes.append(
            ArtifactOutcome(
                artifact=artifact,
                filename=filename,
                passed=comparison is not None and comparison.passed and error is None,
                comparison=comparison,
                error=error,
            )
        )
    return outcomes


def _result(
    index: int,
    program: str,
    stage: StageInput,
    status: StageStatus,
    outcomes: list[ArtifactOutcome],
    errors: dict[str, str],
    output_hashes: dict[str, str],
    handoff: list[ArtifactComparison] | None = None,
    handoff_error: str | None = None,
) -> StageResult:
    return StageResult(
        stage=index,
        program=program,
        source=stage.source,
        note=stage.note,
        output_directory=stage.output_directory.name,
        status=status,
        own_status=status,
        artifacts=outcomes,
        handoff=handoff or [],
        handoff_error=handoff_error,
        errors=errors,
        output_hashes=output_hashes,
        human_reference=stage.source is StageSource.HUMAN_REFERENCE,
        direct_model_output=stage.source is StageSource.DIRECT_MODEL_OUTPUT,
        helper_assisted_model_output=stage.source is StageSource.HELPER_ASSISTED_MODEL_OUTPUT,
        manually_corrected_model_output=stage.source is StageSource.MANUALLY_CORRECTED_MODEL_OUTPUT,
    )


def _stage0(root: Path, stage: StageInput) -> StageResult:
    directory = stage.output_directory
    hashes: dict[str, str] = {}
    collection_hashes: dict[str, str] = {}
    for name in PROGRAM0_ARTIFACTS:
        path = find_output_file(directory, name)
        if path is not None and (digest := _hash_or_none(path)) is not None:
            hashes[name] = digest
            # The Program 0 validator hashes text with LF normalization.
            collection_hashes[name] = sha256_file(path)
    # Files are hashed here and checked again inside the validator, so a change between
    # the two reads is reported. Absent files use a placeholder and report missing_outputs.
    expected = {name: collection_hashes.get(name, "0" * 64) for name in PROGRAM0_ARTIFACTS}
    validation = validate_program0_outputs(root, directory, expected)
    program0_status: dict[str, StageStatus] = {
        "passed": "passed",
        "failed": "failed",
        "hash_mismatch": "malformed_outputs",
        "missing_outputs": "missing_outputs",
        "malformed_outputs": "malformed_outputs",
    }
    status = program0_status[validation.status]
    errors = dict(validation.errors)
    return _result(
        0,
        "Program 0",
        stage,
        status,
        _outcomes(PROGRAM0_ARTIFACTS, dict(validation.artifact_results), errors),
        errors,
        hashes,
    )


def _stage1(root: Path, stage: StageInput, program0: StageInput) -> StageResult:
    analysis = find_output_file(program0.output_directory, ANALYSIS_FILENAME)
    validation = validate_program1_outputs(root, stage.output_directory, analysis)
    errors = dict(validation.errors)
    result = _result(
        1,
        "Program 1",
        stage,
        validation.status,
        _outcomes(PROGRAM1_ARTIFACTS, dict(validation.artifact_results), errors),
        errors,
        dict(validation.output_hashes),
        handoff=list(validation.input_passthrough.values()),
        handoff_error=errors.get("program0_analysis")
        or (None if analysis is not None else "Program 0 analysis output is missing"),
    )
    if analysis is not None and (digest := _hash_or_none(analysis)) is not None:
        result.input_hashes[ANALYSIS_FILENAME] = digest
    if result.status == "passed" and not result.handoff_passed:
        result.status = result.own_status = "handoff_failed"
    return result


def _stage2(root: Path, stage: StageInput, program1: StageInput) -> StageResult:
    directory = stage.output_directory
    validation = validate_program2(root, directory)
    errors = dict(validation.errors)
    status: StageStatus
    if validation.status == "passed":
        status = "passed"
    elif validation.status == "failed":
        status = "failed"
    elif all(find_output_file(directory, name) is None for name in PROGRAM2_ARTIFACTS):
        status = "missing_outputs"
    else:
        status = "malformed_outputs"
    handoff: list[ArtifactComparison] = []
    handoff_error: str | None = None
    input_hashes: dict[str, str] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="sasguard-p1-") as scratch:
            staged = Path(scratch)
            for filename in PROGRAM1_ARTIFACTS:
                source = find_output_file(program1.output_directory, filename)
                if source is None:
                    raise ValueError(f"Program 1 output {filename} is missing")
                (staged / filename).write_bytes(source.read_bytes())
                input_hashes[filename] = sha256_file(staged / filename, normalize_text=False)
            handoff.append(check_domain_passthrough(staged, directory))
    except (OSError, ValueError, KeyError, ArtifactLoadError, ComparisonInputError) as error:
        handoff_error = f"{type(error).__name__}: {error}"
    if status == "passed" and (handoff_error or not all(item.passed for item in handoff)):
        status = "handoff_failed"
    result = _result(
        2,
        "Program 2",
        stage,
        status,
        _outcomes(PROGRAM2_ARTIFACTS, dict(validation.comparisons), errors),
        errors,
        dict(validation.output_hashes),
        handoff=handoff,
        handoff_error=handoff_error,
    )
    result.input_hashes.update(input_hashes)
    return result


def _load_pair(
    root: Path,
    paths: ResolvedProjectPaths,
    stage: int,
    outcome: ArtifactOutcome,
    directory: Path,
) -> tuple[LoadedArtifact, LoadedArtifact, Compare, str]:
    """Reload one artifact pair and the comparison function used to judge it."""
    name = outcome.artifact
    path = find_output_file(directory, outcome.filename)
    if path is None:
        raise ValueError("output is missing")
    reference = paths.reference_sas7bdat[name]
    if stage == 0:
        policy = load_program0_policies(root)[name]
        key = policy.keys[0]
        actual, expected = load_artifact(path, key=key), load_artifact(reference, key=key)
        if name == "MEASURE_AVERAGE_STDDEV_2025JUL":
            return actual, expected, lambda a, e: _compare_statistics(a, e, policy), key
    elif stage == 1:
        policy = load_program1_policies(root)[name]
        key = "PROVIDER_ID"
        actual, expected = load_artifact(path, key=key), load_artifact(reference, key=key)
    else:
        policy = load_program2_policies(root)[name]
        if name == "STAR_2025JUL":
            key = "PROVIDER_ID"
            actual, expected = load_artifact(path), load_artifact(reference, key=key)
        else:
            key = "__SASGUARD_ROW"
            actual, expected = load_artifact(path), load_artifact(reference)
            actual = replace(
                actual,
                frame=actual.frame.assign(**{key: [str(i) for i in range(actual.row_count)]}),
            )
            expected = replace(
                expected,
                frame=expected.frame.assign(**{key: [str(i) for i in range(expected.row_count)]}),
            )

    def compare(a: LoadedArtifact, e: LoadedArtifact) -> ArtifactComparison:
        return compare_artifacts(a, e, artifact=name, policy=policy)

    return actual, expected, compare, key


def _first_bad_key(
    actual: LoadedArtifact, expected: LoadedArtifact, compare: Compare, key: str, column: str
) -> str | None:
    """Binary-search the first expected row whose ``column`` the comparator rejects."""
    expected_key = resolve_column_name(key, list(expected.frame.columns))
    actual_key = resolve_column_name(key, list(actual.frame.columns))
    shared = set(actual.frame[actual_key])
    order = [value for value in expected.frame[expected_key] if value in shared]

    def fails(count: int) -> bool:
        chosen = set(order[:count])
        subset_actual = replace(actual, frame=actual.frame[actual.frame[actual_key].isin(chosen)])
        subset_expected = replace(
            expected, frame=expected.frame[expected.frame[expected_key].isin(chosen)]
        )
        return column in compare(subset_actual, subset_expected).mismatched_columns

    if not order or not fails(len(order)):
        return None
    low, high = 1, len(order)
    while low < high:
        middle = (low + high) // 2
        if fails(middle):
            high = middle
        else:
            low = middle + 1
    return str(order[low - 1])


def _first_exact_difference(
    column: str, left: pd.DataFrame, right: pd.DataFrame
) -> tuple[str | None, str | None]:
    """Return the first differing (key, column) between two keyed frames, exactly."""
    merged = left.loc[:, ["PROVIDER_ID", column]].merge(
        right.loc[:, ["PROVIDER_ID", column]],
        on="PROVIDER_ID",
        how="outer",
        suffixes=("_a", "_b"),
    )
    same = (merged[f"{column}_a"] == merged[f"{column}_b"]) | (
        merged[f"{column}_a"].isna() & merged[f"{column}_b"].isna()
    )
    if same.all():
        return None, column
    return str(merged.loc[~same, "PROVIDER_ID"].iloc[0]), column


def _handoff_location(
    result: StageResult,
    comparison: ArtifactComparison,
    stage_input: StageInput,
    program0: StageInput,
    program1: StageInput,
) -> tuple[str | None, str | None]:
    """Locate the first differing copied cell using the same exact rule as the check."""
    column = comparison.mismatched_columns[0] if comparison.mismatched_columns else None
    if column is None:
        return None, None
    if result.stage == 1:
        domain = comparison.artifact.removesuffix("_INPUT_PASSTHROUGH")
        filename = next(name for name, art in PROGRAM1_ARTIFACTS.items() if art == domain)
        output = find_output_file(stage_input.output_directory, filename)
        analysis = find_output_file(program0.output_directory, ANALYSIS_FILENAME)
        assert output is not None and analysis is not None
        return _first_exact_difference(
            column,
            load_artifact(output, key="PROVIDER_ID").frame,
            load_artifact(analysis, key="PROVIDER_ID").frame,
        )
    domain = next(name for name, value in DOMAIN_SCORE_COLUMNS.items() if value == column)
    filename = next(name for name, art in PROGRAM1_ARTIFACTS.items() if art == domain)
    star = find_output_file(stage_input.output_directory, "star_2025jul.csv")
    source = find_output_file(program1.output_directory, filename)
    assert star is not None and source is not None
    scores = load_artifact(source, key="PROVIDER_ID").frame
    return _first_exact_difference(
        column,
        load_artifact(star, key="PROVIDER_ID").frame,
        scores.loc[:, ["PROVIDER_ID", "GRP_SCORE"]].rename(columns={"GRP_SCORE": column}),
    )


def locate_divergence(
    root: Path,
    paths: ResolvedProjectPaths,
    result: StageResult,
    inputs: list[StageInput],
) -> Divergence:
    """Find the first failing artifact of a failing stage and its first differing key/column."""
    stage_input = inputs[result.stage]
    failing = [outcome for outcome in result.artifacts if not outcome.passed]
    # A validator that stops at the first missing or malformed file leaves the other
    # artifacts uncompared with no error. Those are not divergences, so prefer the
    # artifacts that were actually judged or that carry their own error.
    judged = [o for o in failing if o.comparison is not None or o.error is not None]
    for outcome in judged or failing:
        comparison = outcome.comparison
        if comparison is None:
            present = find_output_file(stage_input.output_directory, outcome.filename)
            missing = outcome.error == "file is missing" or present is None
            if missing:
                detail = "file is missing"
            elif outcome.error and outcome.error != "missing_or_malformed_output":
                detail = outcome.error
            else:
                detail = "file is present but could not be read or compared"
            return Divergence(
                stage=result.stage,
                program=result.program,
                artifact=outcome.artifact,
                kind="missing_output" if missing else "malformed_output",
                detail=detail,
            )
        structural: tuple[DivergenceKind, str | None, str | None] | None = None
        if comparison.missing_columns:
            structural = ("schema", comparison.missing_columns[0], None)
        elif comparison.extra_columns:
            structural = ("schema", comparison.extra_columns[0], None)
        elif comparison.missing_keys:
            structural = ("keys", None, comparison.missing_keys[0])
        elif comparison.extra_keys:
            structural = ("keys", None, comparison.extra_keys[0])
        if structural is not None:
            kind, column, key = structural
            return Divergence(
                stage=result.stage,
                program=result.program,
                artifact=outcome.artifact,
                kind=kind,
                column=column,
                key=key,
                detail=f"{kind} differs from the SAS artifact",
            )
        column = comparison.mismatched_columns[0] if comparison.mismatched_columns else None
        key = None
        if column is not None:
            try:
                actual, expected, compare, key_name = _load_pair(
                    root, paths, result.stage, outcome, stage_input.output_directory
                )
                key = _first_bad_key(actual, expected, compare, key_name, column)
            except (OSError, ValueError, KeyError, ArtifactLoadError, ComparisonInputError):
                key = None
        return Divergence(
            stage=result.stage,
            program=result.program,
            artifact=outcome.artifact,
            kind="value",
            column=column,
            key=key,
            detail=f"{comparison.mismatched_cells} mismatched cells, "
            f"{comparison.missingness_mismatches} missingness mismatches",
        )
    # Every SAS comparison passed, so the stage failed to consume the actual upstream output.
    for comparison in result.handoff:
        if comparison.passed:
            continue
        try:
            key, column = _handoff_location(result, comparison, stage_input, inputs[0], inputs[1])
        except (OSError, ValueError, KeyError, AssertionError, ArtifactLoadError):
            key, column = None, None
        return Divergence(
            stage=result.stage,
            program=result.program,
            artifact=comparison.artifact,
            kind="handoff",
            column=column,
            key=key,
            detail="copied input differs from the actual upstream output",
        )
    return Divergence(
        stage=result.stage,
        program=result.program,
        artifact="handoff",
        kind="handoff",
        detail=result.handoff_error or "upstream output could not be compared",
    )


def star_mismatch_count(root: Path, paths: ResolvedProjectPaths, directory: Path) -> int | None:
    """Count SAS hospitals whose STAR differs or is absent; None if the file is unreadable."""
    path = find_output_file(directory, "star_2025jul.csv")
    if path is None:
        return None
    try:
        actual = load_artifact(path, key="PROVIDER_ID").frame
        expected = load_artifact(paths.reference_sas7bdat["STAR_2025JUL"], key="PROVIDER_ID").frame
        merged = expected.loc[:, ["PROVIDER_ID", "STAR"]].merge(
            actual.loc[:, ["PROVIDER_ID", "STAR"]],
            on="PROVIDER_ID",
            how="left",
            suffixes=("_sas", "_py"),
            indicator=True,
        )
        same = (merged["STAR_sas"] == merged["STAR_py"]) | (
            merged["STAR_sas"].isna() & merged["STAR_py"].isna()
        )
        return int((~same | (merged["_merge"] != "both")).sum())
    except (OSError, ValueError, KeyError, ArtifactLoadError):
        return None


def validate_pipeline(
    project_root: Path,
    program0: StageInput,
    program1: StageInput,
    program2: StageInput,
) -> PipelineValidation:
    """Validate all ten artifacts across the chain and return an explicit summary."""
    root = project_root.resolve()
    integrity_before = _integrity(root)
    audit = audit_policies(root)
    paths = load_project_configuration(root / CONFIG_PATH, project_root=root).resolve_paths(root)
    inputs = [program0, program1, program2]

    stages = [_stage0(root, program0), _stage1(root, program1, program0)]
    stages.append(_stage2(root, program2, program1))
    stages[0].source_hashes = _source_hashes(
        root, program0, ("src/sasguard/program0.py", "src/sasguard/verification/program0.py")
    )
    stages[1].source_hashes = _source_hashes(
        root,
        program1,
        ("reference_python/domain_scoring.py", "src/sasguard/verification/program1.py"),
    )
    stages[2].source_hashes = _source_hashes(
        root, program2, ("src/sasguard/verification/program2.py",)
    )
    stages[0].input_hashes[paths.input_sas7bdat.relative_to(root).as_posix()] = sha256_file(
        paths.input_sas7bdat
    )

    earliest: Divergence | None = None
    for stage in stages:
        if stage.own_status == "passed":
            continue
        if earliest is None:
            earliest = locate_divergence(root, paths, stage, inputs)
        else:
            stage.status = "upstream_failure"

    integrity_after = _integrity(root)
    integrity_passed = bool(integrity_before["passed"]) and bool(integrity_after["passed"])
    if earliest is None and not integrity_passed:
        earliest = Divergence(
            stage=-1,
            program="integrity",
            artifact=INTEGRITY_PATH,
            kind="integrity",
            detail="protected files changed or could not be verified",
        )
    elif earliest is None and audit:
        earliest = Divergence(
            stage=-1,
            program="policy",
            artifact=audit[0],
            kind="policy",
            detail="comparison tolerance differs from the fixed 1e-12 contract",
        )

    artifacts_passed = sum(stage.artifacts_passed for stage in stages)
    status = derive_status(
        artifacts_passed=artifacts_passed,
        handoffs_passed=all(stage.handoff_passed for stage in stages),
        integrity_passed=integrity_passed,
        audit_passed=not audit,
    )
    environment = collect_environment(root)
    return PipelineValidation(
        status=status,
        artifacts_passed=artifacts_passed,
        passed_by_program={f"program{s.stage}": s.artifacts_passed for s in stages},
        star_mismatches=star_mismatch_count(root, paths, program2.output_directory),
        stages=stages,
        earliest_divergence=earliest,
        integrity_before=integrity_before,
        integrity_after=integrity_after,
        policy_audit=audit,
        policy_hashes={
            path: digest
            for path in POLICY_PATHS.values()
            if (digest := _hash_or_none(root / path)) is not None
        },
        sas_reference_hashes={
            paths.reference_sas7bdat[name].relative_to(root).as_posix(): sha256_file(
                paths.reference_sas7bdat[name]
            )
            for name in (
                *PROGRAM0_ARTIFACTS.values(),
                *PROGRAM1_ARTIFACTS.values(),
                *PROGRAM2_ARTIFACTS.values(),
            )
        },
        environment=environment,
        environment_sha256=sha256(json.dumps(environment, sort_keys=True).encode()).hexdigest(),
        full_pipeline_parity=status == "PASS",
    )


def render_summary(result: PipelineValidation) -> str:
    """Human-readable summary that states parity only for a full PASS."""
    parity = (
        "established for the supplied July 2025 SAS artifacts"
        if result.full_pipeline_parity
        else "NOT established"
    )
    lines = [
        "# Full-pipeline validation",
        "",
        f"Status: {result.status}. {result.artifacts_passed} of {result.artifacts_total} "
        "artifact comparisons passed.",
        f"Full-pipeline parity: {parity}.",
        f"Scope: {result.scope}. Human review and client approval: not recorded.",
        "",
        "| Program | Source | Status | Artifacts passed | Handoff |",
        "|---|---|---|---:|---|",
    ]
    for stage in result.stages:
        handoff = "n/a" if stage.stage == 0 else ("passed" if stage.handoff_passed else "failed")
        lines.append(
            f"| {stage.program} | {stage.source.value} | {stage.status} "
            f"| {stage.artifacts_passed}/{len(stage.artifacts)} | {handoff} |"
        )
    mismatches = "unknown" if result.star_mismatches is None else str(result.star_mismatches)
    before, after = result.integrity_before, result.integrity_after
    lines.extend(
        [
            "",
            f"STAR mismatches: {mismatches}.",
            "Protected-file integrity before / after: "
            f"{before['checked_files']}/{before['expected_files']} "
            f"({'passed' if before['passed'] else 'failed'}) / "
            f"{after['checked_files']}/{after['expected_files']} "
            f"({'passed' if after['passed'] else 'failed'}).",
        ]
    )
    if result.policy_audit:
        lines.append(f"Policy audit FAILED: {'; '.join(result.policy_audit)}.")
    divergence = result.earliest_divergence
    if divergence is not None:
        lines.extend(
            [
                "",
                f"Earliest divergence: {divergence.program}, artifact {divergence.artifact}, "
                f"{divergence.kind}; column {divergence.column or 'n/a'}, "
                f"key {divergence.key or 'n/a'}. {divergence.detail}",
            ]
        )
    lines.append("")
    return "\n".join(lines)
