"""Reject unverified upstream runs and preserve exact stage-to-stage values."""

from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest
from test_program0_reporting import bundle

from sasguard.data import ArtifactFormat, LoadedArtifact
from sasguard.prototypes import program01
from sasguard.reporting.reader import read_run_report


def table(values: list[float | None], keys: list[str] | None = None) -> LoadedArtifact:
    return LoadedArtifact(
        frame=pd.DataFrame({"PROVIDER_ID": keys or ["001", "NA", "NULL"], "STD_A": values}),
        source_path=Path("python-intermediate.csv"),
        format=ArtifactFormat.CSV,
        key_column="PROVIDER_ID",
    )


def test_stage_handoff_preserves_literal_identifiers_and_missing_values() -> None:
    source = table([1.0, None, 3.0])
    reordered = LoadedArtifact(
        frame=source.frame.iloc[::-1],
        source_path=Path("output.csv"),
        format=ArtifactFormat.CSV,
        key_column="PROVIDER_ID",
    )
    checked = program01._copy_check(reordered, source, "TEST")
    assert checked.passed
    assert checked.missingness_mismatches == 0


def test_passthrough_change_smaller_than_sas_tolerance_still_fails() -> None:
    source = table([1.0, None, 3.0])
    wrong = table([1.0 + 5e-13, None, 3.0])
    checked = program01._copy_check(wrong, source, "TEST")
    assert not checked.passed and checked.mismatched_cells == 1
    assert checked.mismatched_columns == ["STD_A"]


def test_changed_missingness_and_identifier_cannot_pass_handoff() -> None:
    source = table([1.0, None, 3.0])
    wrong = table([1.0, 0.0, 3.0], ["001", "NA", "EXTRA"])
    checked = program01._copy_check(wrong, source, "TEST")
    assert not checked.passed
    assert checked.missingness_mismatches == 1
    assert checked.missing_keys and checked.extra_keys


@pytest.mark.parametrize("state", ["failed", "malformed_outputs", "not_run"])
def test_unverified_upstream_cannot_launch_program1(tmp_path: Path, state: str) -> None:
    run = bundle(tmp_path, state=state)
    with pytest.raises(ValueError, match="requires a verified Program 0"):
        program01._upstream_input(tmp_path, run)


def test_changed_upstream_output_cannot_be_substituted(tmp_path: Path) -> None:
    run = bundle(tmp_path)
    assert read_run_report(tmp_path, run).scope_status.value == "VERIFIED"
    (run / "output" / program01.INTERMEDIATE).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="requires a verified Program 0"):
        program01._upstream_input(tmp_path, run)


def test_validated_input_is_python_output_and_not_sas_intermediate(tmp_path: Path) -> None:
    run = bundle(tmp_path)
    upstream, source, directory = program01._upstream_input(tmp_path, run)
    assert source == run / "output" / program01.INTERMEDIATE
    assert directory == run and upstream.report_kind == "program0"
    assert source.suffix == ".csv"


def test_scope_pass_requires_all_domain_comparisons(tmp_path: Path) -> None:
    run = bundle(tmp_path)
    upstream = read_run_report(tmp_path, run)
    with pytest.raises(ValueError, match="all five domain checks"):
        program01.Program01Report(
            status="passed",
            upstream=upstream,
            upstream_directory="saved-run",
            input_path="python.csv",
            input_sha256_bytes="a" * 64,
            policies={},
            snapshot_hashes_lf={},
        )


def test_cli_fails_when_upstream_is_not_verified(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from sasguard.cli import app

    run = bundle(tmp_path, state="failed")
    result = CliRunner().invoke(
        app, ["run-program01-chain", str(run), "--project-root", str(tmp_path), "--image", "test"]
    )
    assert result.exit_code == 2
    assert "requires a verified Program 0" in result.output


def test_model_workflow_cannot_link_to_an_outside_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sasguard.prototypes.program0_model import ModelAttempt, ModelSettings, ModelWorkflow

    run = bundle(tmp_path)
    upstream = read_run_report(tmp_path, run)
    model_run = tmp_path / "reports/runs" / f"model-{uuid4()}"
    model_run.mkdir()
    workflow = ModelWorkflow(
        settings=ModelSettings(),
        input_format="csv",
        preview_directory="preview",
        preview_sha256_bytes="a" * 64,
        messages_sha256_bytes="b" * 64,
        project_hashes_lf={},
        controller_hashes_lf={},
        image="test",
        attempts=[ModelAttempt(index=0, condition="direct", execution_report="../outside.json")],
    )
    (model_run / "workflow.json").write_text(workflow.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(program01, "read_run_report", lambda *args: upstream)
    with pytest.raises(ValueError):
        program01._upstream_input(tmp_path, model_run)
