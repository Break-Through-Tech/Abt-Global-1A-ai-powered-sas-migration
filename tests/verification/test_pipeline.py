"""Full-pipeline validator: classes of wrong, missing, malformed and mis-chained output.

Program 0 and Program 1 outputs come from the human references. No human Program 2
exists, so Program 2 uses a control built on the test host from the SAS star and national
average artifacts with the actual Program 1 scores copied in, as a faithful Program 2
would. Trusted values never reach any candidate; these controls only prove the validator.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from sasguard.cli import app
from sasguard.config import load_project_configuration
from sasguard.data import load_artifact
from sasguard.prototypes.pipeline_reference import run_human_program0, run_human_program1
from sasguard.verification.pipeline import (
    DOMAIN_SCORE_COLUMNS,
    StageInput,
    StageSource,
    audit_policies,
    derive_status,
    validate_pipeline,
)
from sasguard.verification.program1 import PROGRAM1_ARTIFACTS

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = "std_data_2025jul_analysis.csv"
STD_COLUMN = "STD_MORT_30_AMI"


def write(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, float_format="%.17g")


def present(frame: pd.DataFrame, column: str, nth: int = 0) -> int:
    """Row label of the nth non-missing value, so a change is never applied to NaN."""
    return int(frame.index[frame[column].notna()][nth])


def read(path: Path) -> pd.DataFrame:
    return load_artifact(path, key="PROVIDER_ID").frame


def build_program2_control(program1: Path, destination: Path) -> None:
    """SAS stars and averages, with the actual Program 1 domain scores in the copied columns."""
    paths = load_project_configuration(
        ROOT / "configs/cms_2025jul.yaml", project_root=ROOT
    ).resolve_paths(ROOT)
    destination.mkdir(parents=True, exist_ok=True)
    star = load_artifact(paths.reference_sas7bdat["STAR_2025JUL"], key="PROVIDER_ID").frame.copy()
    for domain, column in DOMAIN_SCORE_COLUMNS.items():
        scores = read(program1 / f"{domain.lower()}.csv").set_index("PROVIDER_ID")["GRP_SCORE"]
        star[column] = star["PROVIDER_ID"].map(scores)
    write(star, destination / "star_2025jul.csv")
    write(
        load_artifact(paths.reference_sas7bdat["NATIONAL_AVERAGE_2025JUL"]).frame,
        destination / "national_average_2025jul.csv",
    )


@pytest.fixture(scope="module")
def clean(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("pipeline-clean")
    run_human_program0(ROOT, base / "p0")
    run_human_program1(ROOT, base / "p0", base / "p1")
    build_program2_control(base / "p1", base / "p2")
    return base


@pytest.fixture
def work(clean: Path, tmp_path: Path) -> Path:
    """A private copy of the clean chain that a test may corrupt."""
    for name in ("p0", "p1", "p2"):
        shutil.copytree(clean / name, tmp_path / name)
    return tmp_path


def stages(
    base: Path,
    p0: StageSource = StageSource.HUMAN_REFERENCE,
    p1: StageSource = StageSource.HUMAN_REFERENCE,
    p2: StageSource = StageSource.HELPER_ASSISTED_MODEL_OUTPUT,
) -> tuple[StageInput, StageInput, StageInput]:
    return (
        StageInput(source=p0, output_directory=base / "p0"),
        StageInput(source=p1, output_directory=base / "p1"),
        StageInput(source=p2, output_directory=base / "p2"),
    )


def run(base: Path, **sources: StageSource):
    return validate_pipeline(ROOT, *stages(base, **sources))


def test_clean_chain_passes_all_ten(work: Path) -> None:
    result = run(work)
    assert result.status == "PASS"
    assert result.full_pipeline_parity
    assert result.artifacts_passed == 10
    assert result.passed_by_program == {"program0": 3, "program1": 5, "program2": 2}
    assert result.star_mismatches == 0
    assert result.earliest_divergence is None
    assert result.policy_audit == []
    assert result.integrity_before["passed"] and result.integrity_after["passed"]
    assert (
        result.integrity_before["checked_files"] == result.integrity_before["expected_files"] == 29
    )
    assert all(stage.handoff_passed for stage in result.stages)


def test_records_source_flags_and_all_hash_classes(work: Path) -> None:
    result = run(work, p2=StageSource.DIRECT_MODEL_OUTPUT)
    flags = {
        stage.program: (
            stage.human_reference,
            stage.direct_model_output,
            stage.helper_assisted_model_output,
        )
        for stage in result.stages
    }
    assert flags == {
        "Program 0": (True, False, False),
        "Program 1": (True, False, False),
        "Program 2": (False, True, False),
    }
    assert len(result.policy_hashes) == 3
    assert len(result.sas_reference_hashes) == 10
    assert len(result.environment_sha256) == 64
    assert result.environment["python_version"] and result.environment["git_commit"]
    assert result.stages[0].source_hashes  # human reference source files
    assert result.stages[0].input_hashes  # supplied hospital input
    assert ANALYSIS in result.stages[1].input_hashes  # the actual Program 0 output consumed
    assert len(result.stages[2].input_hashes) == 5  # the actual Program 1 outputs consumed
    assert all(len(stage.output_hashes) == len(stage.artifacts) for stage in result.stages)


def test_candidate_code_hash_is_recorded(work: Path) -> None:
    candidate = work / "candidate.py"
    candidate.write_text("print('candidate')\n", encoding="utf-8")
    p0, p1, p2 = stages(work)
    p2 = p2.model_copy(update={"code_path": candidate})
    result = validate_pipeline(ROOT, p0, p1, p2)
    assert list(result.stages[2].source_hashes) == ["candidate:candidate.py"]


def test_missing_program2_is_partial_not_pass(work: Path) -> None:
    shutil.rmtree(work / "p2")
    result = run(work)
    assert result.status == "PARTIAL"
    assert not result.full_pipeline_parity
    assert result.artifacts_passed == 8
    divergence = result.earliest_divergence
    assert divergence is not None
    assert (divergence.stage, divergence.kind) == (2, "missing_output")


def test_nothing_usable_is_fail(work: Path) -> None:
    for name in ("p0", "p1", "p2"):
        shutil.rmtree(work / name)
    result = run(work)
    assert result.status == "FAIL"
    assert result.artifacts_passed == 0
    assert result.earliest_divergence is not None
    assert result.earliest_divergence.stage == 0


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"artifacts_passed": 10, "handoffs_passed": True}, "PASS"),
        ({"artifacts_passed": 10, "handoffs_passed": False}, "PARTIAL"),
        ({"artifacts_passed": 9, "handoffs_passed": True}, "PARTIAL"),
        ({"artifacts_passed": 1, "handoffs_passed": False}, "PARTIAL"),
        ({"artifacts_passed": 0, "handoffs_passed": True}, "FAIL"),
        ({"artifacts_passed": 10, "handoffs_passed": True, "integrity_passed": False}, "FAIL"),
        ({"artifacts_passed": 10, "handoffs_passed": True, "audit_passed": False}, "FAIL"),
    ],
)
def test_summary_status_rules(kwargs: dict[str, object], expected: str) -> None:
    defaults: dict[str, object] = {"integrity_passed": True, "audit_passed": True}
    assert derive_status(**{**defaults, **kwargs}) == expected  # type: ignore[arg-type]


def test_program0_wrong_but_executable_is_earliest_and_flags_downstream_as_upstream(
    work: Path,
) -> None:
    """A wrong Program 0 value flows into Program 1 and Program 2 without being their bug."""
    analysis = read(work / "p0" / ANALYSIS)
    row = present(analysis, STD_COLUMN, 7)
    analysis.loc[row, STD_COLUMN] = analysis.loc[row, STD_COLUMN] + 1e-6
    wrong_provider = analysis.loc[row, "PROVIDER_ID"]
    write(analysis, work / "p0" / ANALYSIS)
    # Program 1 runs on the corrupted output, so it is internally consistent.
    shutil.rmtree(work / "p1")
    run_human_program1(ROOT, work / "p0", work / "p1")
    result = run(work)
    assert result.status == "PARTIAL"
    divergence = result.earliest_divergence
    assert divergence is not None
    assert (divergence.stage, divergence.artifact, divergence.kind) == (
        0,
        "STD_DATA_2025JUL_ANALYSIS",
        "value",
    )
    assert divergence.column == STD_COLUMN
    assert divergence.key == wrong_provider
    program1 = result.stages[1]
    assert program1.own_status in {"failed", "handoff_failed"}
    assert program1.status == "upstream_failure"
    assert result.stages[2].status in {"upstream_failure", "passed"}
    assert result.stages[0].status == "failed"


def test_program0_corruption_with_clean_program1_reports_handoff_upstream(work: Path) -> None:
    """Program 1 that did not consume the actual Program 0 output is not blamed first."""
    analysis = read(work / "p0" / ANALYSIS)
    row = present(analysis, STD_COLUMN, 3)
    analysis.loc[row, STD_COLUMN] = analysis.loc[row, STD_COLUMN] + 1e-6
    write(analysis, work / "p0" / ANALYSIS)
    result = run(work)
    assert result.earliest_divergence is not None
    assert result.earliest_divergence.stage == 0
    assert result.stages[1].status == "upstream_failure"
    assert result.stages[1].own_status == "handoff_failed"
    assert not result.stages[1].handoff_passed
    assert result.status == "PARTIAL"


def test_program1_wrong_but_executable_reports_program1_first(work: Path) -> None:
    path = work / "p1" / "process.csv"
    frame = read(path)
    row = present(frame, "GRP_SCORE", 11)
    frame.loc[row, "GRP_SCORE"] = frame.loc[row, "GRP_SCORE"] + 1e-6
    wrong_provider = frame.loc[row, "PROVIDER_ID"]
    write(frame, path)
    result = run(work)
    assert result.status == "PARTIAL"
    divergence = result.earliest_divergence
    assert divergence is not None
    assert (divergence.stage, divergence.artifact, divergence.column) == (1, "PROCESS", "GRP_SCORE")
    assert divergence.key == wrong_provider
    assert result.stages[1].status == "failed"
    assert result.stages[2].status == "upstream_failure"  # its copied scores no longer match


def test_program1_not_consuming_actual_program0_is_its_own_handoff_failure(work: Path) -> None:
    """A change below the SAS tolerance still fails the exact copied-input check."""
    analysis = read(work / "p0" / ANALYSIS)
    row = present(analysis, STD_COLUMN, 5)
    value = analysis.loc[row, STD_COLUMN]
    analysis.loc[row, STD_COLUMN] = value + abs(value) * 1e-14
    shifted = work / "p0-shifted"
    shifted.mkdir()
    write(analysis, shifted / ANALYSIS)
    shutil.rmtree(work / "p1")
    run_human_program1(ROOT, shifted, work / "p1")  # Program 1 consumed different input
    result = run(work)
    assert result.status == "PARTIAL"
    program1 = result.stages[1]
    assert program1.artifacts_passed == 5  # within 1e-12 of SAS
    assert program1.status == "handoff_failed"
    divergence = result.earliest_divergence
    assert divergence is not None
    assert (divergence.stage, divergence.kind, divergence.column) == (1, "handoff", STD_COLUMN)
    assert divergence.key == analysis.loc[row, "PROVIDER_ID"]


def test_program2_wrong_star_is_flagged_with_key_and_counted(work: Path) -> None:
    path = work / "p2" / "star_2025jul.csv"
    frame = read(path)
    index = int(frame["STAR"].first_valid_index())  # type: ignore[arg-type]
    frame.loc[index, "STAR"] = 1.0 if frame.loc[index, "STAR"] != 1.0 else 2.0
    write(frame, path)
    result = run(work)
    assert result.status == "PARTIAL"
    assert result.artifacts_passed == 9
    assert result.star_mismatches == 1
    divergence = result.earliest_divergence
    assert divergence is not None
    assert (divergence.stage, divergence.artifact, divergence.column) == (2, "STAR_2025JUL", "STAR")
    assert divergence.key == frame.loc[index, "PROVIDER_ID"]


def test_program2_copied_scores_must_equal_program1_exactly(work: Path) -> None:
    path = work / "p2" / "star_2025jul.csv"
    frame = read(path)
    column = "STD_PROCESS_SCORE"
    index = int(frame[column].first_valid_index())  # type: ignore[arg-type]
    frame.loc[index, column] = frame.loc[index, column] * (1 + 1e-14)
    write(frame, path)
    result = run(work)
    assert result.stages[2].artifacts_passed == 2  # inside the 1e-12 tolerance
    assert result.stages[2].status == "handoff_failed"
    assert result.status == "PARTIAL"
    divergence = result.earliest_divergence
    assert divergence is not None
    assert (divergence.stage, divergence.kind, divergence.column) == (2, "handoff", column)
    assert divergence.key == frame.loc[index, "PROVIDER_ID"]


def test_numeric_difference_beyond_tolerance_fails_program2_value(work: Path) -> None:
    path = work / "p2" / "star_2025jul.csv"
    frame = read(path)
    index = int(frame["SUMMARY_SCORE"].first_valid_index())  # type: ignore[arg-type]
    frame.loc[index, "SUMMARY_SCORE"] += 1e-9
    write(frame, path)
    result = run(work)
    divergence = result.earliest_divergence
    assert divergence is not None
    assert (divergence.stage, divergence.column) == (2, "SUMMARY_SCORE")
    assert divergence.key == frame.loc[index, "PROVIDER_ID"]


def test_missing_domain_file_is_a_program1_missing_output(work: Path) -> None:
    (work / "p1" / "ptexp.csv").unlink()
    result = run(work)
    assert result.status == "PARTIAL"
    assert result.stages[1].status == "missing_outputs"
    assert result.earliest_divergence is not None
    assert (result.earliest_divergence.stage, result.earliest_divergence.kind) == (
        1,
        "missing_output",
    )
    assert result.stages[2].status == "upstream_failure"


@pytest.mark.parametrize(
    ("stage", "filename", "artifact"),
    [
        (0, "less100_measure.csv", "LESS100_MEASURE"),
        (1, "outcome_safety.csv", "OUTCOME_SAFETY"),
        (2, "star_2025jul.csv", "STAR_2025JUL"),
    ],
)
def test_malformed_output_is_reported_per_program(
    work: Path, stage: int, filename: str, artifact: str
) -> None:
    (work / f"p{stage}" / filename).write_text("not,a\nvalid", encoding="utf-8")
    result = run(work)
    assert result.status == "PARTIAL"
    divergence = result.earliest_divergence
    assert divergence is not None
    assert (divergence.stage, divergence.artifact) == (stage, artifact)
    assert divergence.kind in {"malformed_output", "schema", "keys"}


@pytest.mark.parametrize(
    ("damage", "kind"),
    [("delete", "missing_output"), ("empty", "malformed_output"), ("garbage", "malformed_output")],
)
def test_broken_later_program0_file_is_named_not_the_first_artifact(
    work: Path, damage: str, kind: str
) -> None:
    """The divergence names the broken file, not an earlier file left uncompared."""
    path = work / "p0" / ANALYSIS
    if damage == "delete":
        path.unlink()
    elif damage == "empty":
        path.write_text("", encoding="utf-8")
    else:
        path.write_text("not,a\nvalid", encoding="utf-8")
    result = validate_pipeline(
        ROOT, *stages(work, p0=StageSource.DIRECT_MODEL_OUTPUT, p2=StageSource.DIRECT_MODEL_OUTPUT)
    )
    divergence = result.earliest_divergence
    assert divergence is not None
    assert (divergence.stage, divergence.artifact, divergence.kind) == (
        0,
        "STD_DATA_2025JUL_ANALYSIS",
        kind,
    )
    assert divergence.detail != "output could not be compared"


def test_missing_program2_file_detail_says_missing(work: Path) -> None:
    (work / "p2" / "star_2025jul.csv").unlink()
    divergence = run(work).earliest_divergence
    assert divergence is not None
    assert (divergence.stage, divergence.kind, divergence.detail) == (
        2,
        "missing_output",
        "file is missing",
    )


def test_missing_key_column_is_malformed_not_a_pass(work: Path) -> None:
    path = work / "p1" / "outcome_mortality.csv"
    write(read(path).drop(columns="PROVIDER_ID"), path)
    result = run(work)
    assert result.stages[1].status == "malformed_outputs"
    assert result.status == "PARTIAL"
    assert result.earliest_divergence is not None
    assert result.earliest_divergence.kind == "malformed_output"


def test_leading_zero_provider_ids_are_preserved(work: Path) -> None:
    path = work / "p1" / "process.csv"
    frame = read(path)
    assert frame["PROVIDER_ID"].map(len).eq(6).all()
    frame["PROVIDER_ID"] = frame["PROVIDER_ID"].str.lstrip("0")  # as if parsed as numbers
    write(frame, path)
    result = run(work)
    assert result.status != "PASS"
    divergence = result.earliest_divergence
    assert divergence is not None
    assert (divergence.stage, divergence.kind) == (1, "keys")


def test_filename_case_does_not_change_the_verdict(work: Path) -> None:
    for name in PROGRAM1_ARTIFACTS:
        (work / "p1" / name).rename(work / "p1" / name.upper().replace(".CSV", ".csv"))
    assert run(work).status == "PASS"


def test_policy_audit_accepts_committed_policies_and_rejects_loosened_ones(
    tmp_path: Path,
) -> None:
    assert audit_policies(ROOT) == []
    shutil.copytree(ROOT / "configs", tmp_path / "configs")
    path = tmp_path / "configs/program1-comparison-policies.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["artifacts"]["PROCESS"]["columns"][-1]["tolerance"] = {
        "absolute": 1e-9,
        "relative": 1e-9,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    problems = audit_policies(tmp_path)
    assert len(problems) == 1 and "PROCESS" in problems[0]


def test_command_exits_nonzero_for_partial_and_writes_the_record() -> None:
    run_directory = ROOT / "reports" / "runs" / f"pipeline-test-{uuid.uuid4()}"
    missing = run_directory.parent / f"missing-{uuid.uuid4()}"
    try:
        outcome = CliRunner().invoke(
            app,
            [
                "validate-pipeline",
                "--run-human-references",
                "--program2-output",
                str(missing),
                "--program2-source",
                "direct_model_output",
                "--output-directory",
                str(run_directory),
            ],
        )
        assert outcome.exit_code == 1
        assert "Status: PARTIAL" in outcome.output
        assert "NOT established" in outcome.output
        assert "Earliest divergence: Program 2" in outcome.output
        record = json.loads((run_directory / "pipeline-validation.json").read_text("utf-8"))
        assert record["status"] == "PARTIAL"
        assert record["full_pipeline_parity"] is False
        assert [s["source"] for s in record["stages"]] == [
            "human_reference",
            "human_reference",
            "direct_model_output",
        ]
    finally:
        shutil.rmtree(run_directory, ignore_errors=True)


def test_command_rejects_output_outside_reports_runs(tmp_path: Path) -> None:
    outcome = CliRunner().invoke(
        app,
        [
            "validate-pipeline",
            "--run-human-references",
            "--program2-output",
            str(tmp_path),
            "--program2-source",
            "direct_model_output",
            "--output-directory",
            str(tmp_path / "elsewhere"),
        ],
    )
    assert outcome.exit_code == 2


def invoke_reference_program2(*extra: str) -> tuple[object, Path]:
    run_directory = ROOT / "reports" / "runs" / f"pipeline-test-{uuid.uuid4()}"
    outcome = CliRunner().invoke(
        app,
        [
            "validate-pipeline",
            "--run-human-references",
            "--run-reference-program2",
            "--output-directory",
            str(run_directory),
            *extra,
        ],
    )
    return outcome, run_directory


def test_reference_program2_defaults_to_helper_assisted_label() -> None:
    outcome, run_directory = invoke_reference_program2()
    try:
        assert outcome.exit_code == 0, outcome.output
        record = json.loads((run_directory / "pipeline-validation.json").read_text("utf-8"))
        assert record["status"] == "PASS"
        assert record["passed_by_program"] == {"program0": 3, "program1": 5, "program2": 2}
        program2 = record["stages"][2]
        assert program2["source"] == "helper_assisted_model_output"
        assert program2["helper_assisted_model_output"] is True
        assert program2["human_reference"] is False
        assert "pending teammate review" in program2["note"]
        assert "candidate:program2.py" in program2["source_hashes"]
        assert (run_directory / "program2/star_2025jul.csv").is_file()
    finally:
        shutil.rmtree(run_directory, ignore_errors=True)


def test_reference_program2_is_human_reference_only_when_requested() -> None:
    outcome, run_directory = invoke_reference_program2("--program2-source", "human_reference")
    try:
        assert outcome.exit_code == 0, outcome.output
        record = json.loads((run_directory / "pipeline-validation.json").read_text("utf-8"))
        assert record["stages"][2]["source"] == "human_reference"
    finally:
        shutil.rmtree(run_directory, ignore_errors=True)


def test_reference_program2_rejects_model_source_labels() -> None:
    outcome, run_directory = invoke_reference_program2("--program2-source", "direct_model_output")
    try:
        assert outcome.exit_code == 2
        assert not (run_directory / "pipeline-validation.json").exists()
    finally:
        shutil.rmtree(run_directory, ignore_errors=True)


def test_command_requires_program2_output_without_the_reference_flag() -> None:
    run_directory = ROOT / "reports" / "runs" / f"pipeline-test-{uuid.uuid4()}"
    try:
        outcome = CliRunner().invoke(
            app,
            [
                "validate-pipeline",
                "--run-human-references",
                "--output-directory",
                str(run_directory),
            ],
        )
        assert outcome.exit_code == 2
    finally:
        shutil.rmtree(run_directory, ignore_errors=True)
