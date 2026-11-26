"""Run the human Program 1 reference on a verified Python Program 0 intermediate."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sasguard.config import load_project_configuration
from sasguard.data import LoadedArtifact, load_artifact
from sasguard.execution.manifest import RunManifest
from sasguard.execution.result import ExecutionResult
from sasguard.execution.runner import DockerExecutionRunner, RunnerLimits
from sasguard.prototypes.program0_model import ModelWorkflow
from sasguard.provenance.hashing import hash_files, sha256_file
from sasguard.reporting.models import RunReport, ScopeStatus
from sasguard.reporting.reader import read_run_report, report_runs_directory, safe_file
from sasguard.verification import ArtifactComparisonPolicy, compare_artifacts
from sasguard.verification.artifact import ArtifactComparison
from sasguard.verification.integrity import load_and_verify_integrity
from sasguard.verification.policy import ColumnComparisonPolicy, ComparisonKind

DOMAINS = ("OUTCOME_MORTALITY", "OUTCOME_SAFETY", "OUTCOME_READMISSION", "PTEXP", "PROCESS")
INTERMEDIATE = "std_data_2025jul_analysis.csv"
REFERENCE = "reference_python/domain_scoring.py"
POLICY = "configs/program1-comparison-policies.json"
ENTRY_POINT = '''"""Execute the human reference on a Python-generated CSV intermediate."""
import os
from pathlib import Path
import pandas as pd
from domain_scoring import calculate_all_domains

inputs = Path(os.environ["SASGUARD_INPUT_DIR"])
output = Path(os.environ["SASGUARD_OUTPUT_DIR"])
frame = pd.read_csv(inputs / "std_data_2025jul_analysis.csv",
                    converters={"PROVIDER_ID": str}, float_precision="round_trip")
for name, table in calculate_all_domains(frame).items():
    table.to_csv(output / f"{name}.csv", index=False, float_format="%.17g")
'''


class Program01Report(BaseModel):
    """Keep upstream evidence, reference execution, and downstream comparisons separate."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    scope: Literal["Program 0 Python output through human-reference Program 1; CMS July 2025"] = (
        "Program 0 Python output through human-reference Program 1; CMS July 2025"
    )
    status: Literal["passed", "failed", "runner_error", "integrity_failed"]
    upstream: RunReport
    upstream_directory: str
    input_path: str
    input_sha256_bytes: str
    program1_code_origin: Literal["human_reference"] = "human_reference"
    execution_result: ExecutionResult | None = None
    policies: dict[str, ArtifactComparisonPolicy]
    comparisons: dict[str, ArtifactComparison] = Field(default_factory=dict)
    input_passthrough: dict[str, ArtifactComparison] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)
    snapshot_hashes_lf: dict[str, str]
    output_hashes_bytes: dict[str, str] = Field(default_factory=dict)
    human_review: Literal["not_recorded"] = "not_recorded"
    full_pipeline_verified: Literal[False] = False

    @model_validator(mode="after")
    def require_all_stages_for_pass(self) -> Self:
        if self.status == "passed" and (
            self.upstream.scope_status is not ScopeStatus.VERIFIED
            or self.execution_result is None
            or not self.execution_result.passed
            or set(self.comparisons) != set(DOMAINS)
            or set(self.input_passthrough) != set(DOMAINS)
            or any(not item.passed for item in self.comparisons.values())
            or any(not item.passed for item in self.input_passthrough.values())
            or self.errors
        ):
            raise ValueError("a chain pass requires verified upstream and all five domain checks")
        return self


def _upstream_input(root: Path, directory: Path) -> tuple[RunReport, Path, Path]:
    run = (directory if directory.is_absolute() else root / directory).resolve()
    report = read_run_report(root, run)
    if report.report_kind != "program0" or report.scope_status is not ScopeStatus.VERIFIED:
        raise ValueError("Program 1 requires a verified Program 0 run with all three outputs")
    if (run / "workflow.json").exists():
        workflow = ModelWorkflow.model_validate_json(safe_file(run, "workflow.json").read_bytes())
        execution = safe_file(root, workflow.attempts[-1].execution_report or "")
        execution_run = execution.parent
    else:
        execution_run = run
    if execution_run.parent != report_runs_directory(root):
        raise ValueError("upstream execution must be a top-level saved project run")
    intermediate = safe_file(execution_run, f"output/{INTERMEDIATE}")
    # The report reader confirms the collection and validation hashes before this handoff.
    return report, intermediate, run


def _copy_check(
    actual: LoadedArtifact, input_data: LoadedArtifact, domain: str
) -> ArtifactComparison:
    copied = tuple(name for name in actual.columns if name.upper().startswith("STD_"))
    if not copied:
        raise ValueError("domain output has no copied standardized measure columns")
    columns = ["PROVIDER_ID", *copied]
    source = LoadedArtifact(
        frame=input_data.frame.loc[:, columns],
        source_path=input_data.source_path,
        format=input_data.format,
        key_column="PROVIDER_ID",
    )
    output = LoadedArtifact(
        frame=actual.frame.loc[:, columns],
        source_path=actual.source_path,
        format=actual.format,
        key_column="PROVIDER_ID",
    )
    return compare_artifacts(
        output,
        source,
        artifact=f"{domain}_INPUT_PASSTHROUGH",
        policy=ArtifactComparisonPolicy(
            keys=("PROVIDER_ID",),
            columns=tuple(
                ColumnComparisonPolicy(name=name, kind=ComparisonKind.EXACT) for name in copied
            ),
        ),
    )


def _summary(report: Program01Report) -> str:
    lines = [
        "# Program 0 to Program 1 validation",
        "",
        f"Scope: {report.scope}. Status: {report.status}.",
        f"Program 0 code origin: {report.upstream.code_origin}.",
        "Program 1 code origin: human-written reference Python.",
        "Full pipeline and final CMS ratings: NOT VERIFIED.",
        "Human review and client release approval: not recorded.",
        "",
        "| Domain | SAS comparison | Exact copy from Python input | Rows |",
        "|---|---|---|---|",
    ]
    for name in DOMAINS:
        comparison = report.comparisons.get(name)
        copied = report.input_passthrough.get(name)
        lines.append(
            f"| {name} | {'passed' if comparison.passed else 'failed'} | "
            f"{'passed' if copied and copied.passed else 'failed'} | {comparison.actual_rows} |"
            if comparison
            else f"| {name} | not checked | not checked | unknown |"
        )
    lines.extend(
        [
            "",
            "Program 1 consumes the verified Python-generated CSV, not the SAS intermediate.",
            "SAS reference outputs are read only by host-side verification.",
            "See chain.json for hashes, comparison policies, and execution evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_program01_chain(
    project_root: Path,
    program0_directory: Path,
    *,
    image: str,
    limits: RunnerLimits | None = None,
) -> tuple[Program01Report, Path]:
    """Stage verified Python output, run Program 1 in Docker, and verify five artifacts.

    No model calls occur. The human reference is copied unchanged, and the isolated
    container receives no SAS intermediate or trusted domain outputs. Comparison
    tolerances remain those in the committed Program 1 policies; copied inputs must
    separately survive unchanged, even when a SAS numeric comparison allows tolerance.
    """
    root = project_root.resolve()
    protected = root / "configs/protected-artifacts.json"
    if not load_and_verify_integrity(root, protected).passed:
        raise ValueError("protected artifacts changed before Program 1 execution")
    upstream, intermediate, upstream_directory = _upstream_input(root, program0_directory)
    configuration = load_project_configuration(root / "configs/cms_2025jul.yaml", project_root=root)
    paths = configuration.resolve_paths(root)
    payload = json.loads(safe_file(root, POLICY).read_bytes())
    policies = {
        name: ArtifactComparisonPolicy.model_validate(policy)
        for name, policy in payload["artifacts"].items()
    }
    if payload.get("schema_version") != 1 or set(policies) != set(DOMAINS):
        raise ValueError("Program 1 policies must cover exactly five domains")
    # Freeze the host verifier as well as both stages' source/input evidence.
    relatives = [
        REFERENCE,
        POLICY,
        "configs/cms_2025jul.yaml",
        "configs/protected-artifacts.json",
        "src/sasguard/prototypes/program01.py",
        "src/sasguard/data/loading.py",
        "src/sasguard/verification/comparator.py",
        "src/sasguard/verification/policy.py",
        *[path.relative_to(root).as_posix() for path in (*paths.programs, *paths.macros)],
        *[paths.reference_sas7bdat[name].relative_to(root).as_posix() for name in DOMAINS],
        intermediate.relative_to(root).as_posix(),
        *[
            key.removeprefix("project:")
            for key in upstream.evidence_hashes
            if key.startswith("project:")
        ],
    ]
    snapshot = hash_files(root, relatives)
    input_hash = sha256_file(intermediate, normalize_text=False)
    run = report_runs_directory(root) / f"program01-chain-{uuid4()}"
    source, inputs, output = (run / name for name in ("source", "input", "output"))
    for directory in (source, inputs, output):
        directory.mkdir(parents=True)
    shutil.copyfile(safe_file(root, REFERENCE), source / "domain_scoring.py")
    (source / "main.py").write_bytes(ENTRY_POINT.encode())
    shutil.copyfile(intermediate, inputs / INTERMEDIATE)
    if (
        sha256_file(inputs / INTERMEDIATE, normalize_text=False) != input_hash
        or sha256_file(source / "domain_scoring.py") != snapshot[REFERENCE]
    ):
        raise ValueError("Program 1 staged input or reference differs from selected source")
    manifest = RunManifest.create(
        source_hashes=snapshot,
        input_hashes={
            intermediate.relative_to(root).as_posix(): snapshot[
                intermediate.relative_to(root).as_posix()
            ]
        },
    )
    (run / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    report = Program01Report(
        status="failed",
        upstream=upstream,
        upstream_directory=upstream_directory.relative_to(root).as_posix(),
        input_path=intermediate.relative_to(root).as_posix(),
        input_sha256_bytes=input_hash,
        policies=policies,
        snapshot_hashes_lf=snapshot,
    )
    try:
        execution = DockerExecutionRunner(image=image, limits=limits).run(
            source_directory=source,
            input_directory=inputs,
            output_directory=output,
            forbidden_host_paths=(root / "data", root / "reference_python"),
        )
        report.execution_result = execution
        manifest = manifest.with_execution_result(execution)
        (run / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
        if not execution.passed:
            report.errors["execution"] = execution.status.value
        else:
            if hash_files(root, snapshot) != snapshot:
                raise ValueError("chain snapshot changed during execution")
            input_data = load_artifact(inputs / INTERMEDIATE, key="PROVIDER_ID")
            expected_names = {f"{name}.csv" for name in DOMAINS}
            for path in output.rglob("*"):
                relative = path.relative_to(output).as_posix()
                if relative == ".tmp" or relative.startswith(".tmp/"):
                    continue
                if (
                    path.is_symlink()
                    or getattr(path.lstat(), "st_file_attributes", 0) & 0x400
                    or relative not in expected_names
                    or not path.is_file()
                ):
                    report.errors["output_contract"] = "undeclared_or_unsafe_output"
            for name in DOMAINS:
                try:
                    path = safe_file(output, f"{name}.csv")
                    before = sha256_file(path, normalize_text=False)
                    actual = load_artifact(path, key="PROVIDER_ID")
                    expected = load_artifact(paths.reference_sas7bdat[name], key="PROVIDER_ID")
                    report.comparisons[name] = compare_artifacts(
                        actual, expected, artifact=name, policy=policies[name]
                    )
                    report.input_passthrough[name] = _copy_check(actual, input_data, name)
                    if sha256_file(path, normalize_text=False) != before:
                        raise ValueError("output changed during comparison")
                    report.output_hashes_bytes[name] = before
                except (OSError, ValueError, KeyError):
                    report.errors[name] = "missing_or_malformed_output"
            if (
                not report.errors
                and all(item.passed for item in report.comparisons.values())
                and all(item.passed for item in report.input_passthrough.values())
            ):
                report.status = "passed"
        if (
            hash_files(root, snapshot) != snapshot
            or sha256_file(inputs / INTERMEDIATE, normalize_text=False) != input_hash
            or sha256_file(source / "domain_scoring.py") != snapshot[REFERENCE]
            or (source / "main.py").read_bytes() != ENTRY_POINT.encode()
            or not load_and_verify_integrity(root, protected).passed
            or read_run_report(root, upstream_directory).scope_status is not ScopeStatus.VERIFIED
        ):
            report.status = "integrity_failed"
            report.errors["integrity"] = "chain_evidence_changed"
    except (OSError, ValueError, RuntimeError):
        report.status = "runner_error"
        report.errors["controller"] = "execution_or_validation_could_not_complete"
    report = Program01Report.model_validate(report.model_dump())
    report_path = run / "chain.json"
    report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (run / "summary.md").write_text(_summary(report), encoding="utf-8")
    return report, report_path
