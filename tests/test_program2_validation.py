"""Host-only gold controls prove Program 2 acceptance rules before model use."""

import json
from pathlib import Path

import pandas as pd
import pytest

from sasguard.config import load_project_configuration
from sasguard.data import load_artifact
from sasguard.prototypes import program2_model
from sasguard.prototypes.program2_model import INPUTS, _verified_chain_sources, program2_messages
from sasguard.verification.program2 import ARTIFACTS, validate_program2

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def golden_control(tmp_path: Path) -> Path:
    """Copy gold on the test host only. These values never enter a model or container."""
    paths = load_project_configuration(
        ROOT / "configs/cms_2025jul.yaml", project_root=ROOT
    ).resolve_paths(ROOT)
    for filename, name in ARTIFACTS.items():
        load_artifact(paths.reference_sas7bdat[name]).frame.to_csv(
            tmp_path / filename, index=False, float_format="%.17g"
        )
    return tmp_path


def test_exact_sas_control_passes_both_artifacts(golden_control: Path) -> None:
    result = validate_program2(ROOT, golden_control)
    assert result.status == "passed"
    assert len(result.comparisons) == 2
    assert result.comparisons["STAR_2025JUL"].actual_rows == 4566


@pytest.mark.parametrize("column", ["STAR", "REPORT_INDICATOR", "TOTAL_MEASURE_GROUP_CNT"])
def test_small_changes_to_exact_decisions_fail(golden_control: Path, column: str) -> None:
    path = golden_control / "star_2025jul.csv"
    frame = load_artifact(path, key="PROVIDER_ID").frame
    frame[column] = frame[column].astype(float)
    index = frame[column].first_valid_index()
    frame.loc[index, column] += 5e-13
    frame.to_csv(path, index=False, float_format="%.17g")
    result = validate_program2(ROOT, golden_control)
    assert result.status == "failed"
    assert column in result.comparisons["STAR_2025JUL"].mismatched_columns


def test_extra_national_row_fails(golden_control: Path) -> None:
    path = golden_control / "national_average_2025jul.csv"
    frame = load_artifact(path).frame
    pd.concat([frame, frame]).to_csv(path, index=False, float_format="%.17g")
    result = validate_program2(ROOT, golden_control)
    assert result.status == "failed"
    assert result.comparisons["NATIONAL_AVERAGE_2025JUL"].extra_keys


def test_missing_file_retains_other_comparison(golden_control: Path) -> None:
    (golden_control / "national_average_2025jul.csv").unlink()
    result = validate_program2(ROOT, golden_control)
    assert result.status == "malformed_outputs"
    assert result.comparisons["STAR_2025JUL"].passed


def test_missing_identifier_cannot_pass(golden_control: Path) -> None:
    path = golden_control / "star_2025jul.csv"
    frame = load_artifact(path, key="PROVIDER_ID").frame.drop(columns="PROVIDER_ID")
    frame.to_csv(path, index=False, float_format="%.17g")
    assert validate_program2(ROOT, golden_control).status == "malformed_outputs"


def test_feedback_omits_private_keys_and_unknown_column_names(golden_control: Path) -> None:
    sentinel = "PRIVATE_HOSPITAL_ROW_9348"
    path = golden_control / "star_2025jul.csv"
    frame = load_artifact(path, key="PROVIDER_ID").frame
    frame.loc[0, "PROVIDER_ID"] = sentinel
    frame[sentinel] = 0
    frame.to_csv(path, index=False, float_format="%.17g")
    result = validate_program2(ROOT, golden_control)
    assert sentinel not in json.dumps(result.feedback)
    assert result.status == "failed"


def test_prompt_contains_source_headers_but_no_input_rows(tmp_path: Path) -> None:
    sentinel = "PRIVATE_INPUT_VALUE_812934"
    for name in INPUTS:
        (tmp_path / f"{name.lower()}.csv").write_text(
            f"PROVIDER_ID,GRP_SCORE\n{sentinel},123.987654321\n", encoding="utf-8"
        )
    text = json.dumps(program2_messages(ROOT, tmp_path))
    assert sentinel not in text and "123.987654321" not in text
    assert "FASTCLUS" in text.upper() and "GRP_SCORE" in text
    assert "reference_python" not in text


def test_unverified_chain_never_stages_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _verified_chain_sources(ROOT, tmp_path)


@pytest.mark.parametrize("echo_key", [False, True])
def test_provider_failure_never_retries_executes_or_persists_credentials(
    monkeypatch: pytest.MonkeyPatch, echo_key: bool
) -> None:
    key = "fake-program2-credential-913478"
    calls = []

    def submit(*args: object):
        calls.append(1)
        return 429, key.encode() if echo_key else b'{"error":{"code":"rate_limit"}}'

    def forbidden(*args: object, **kwargs: object):
        raise AssertionError("provider failure must not execute code")

    monkeypatch.setenv("SASGUARD_API_KEY", key)
    monkeypatch.setattr(program2_model, "_submit_request", submit)
    monkeypatch.setattr(program2_model.DockerExecutionRunner, "run", forbidden)
    record, path = program2_model.run_program2_model(ROOT, upstream_chain=None, image="unused")
    assert record.status == "error" and len(calls) == 1
    assert record.attempts[0].execution_status == "not_run"
    assert record.attempts[0].generation_status == "failed"
    for file in path.parent.rglob("*"):
        if file.is_file():
            assert key.encode() not in file.read_bytes()
