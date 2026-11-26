"""Exercise the proposed host handoff without implementing SAS comparison rules."""

from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

import pytest

from sasguard.execution.program0 import (
    OUTPUT_FILENAMES,
    CandidateReport,
    CandidateStatus,
    CandidateValidationResult,
    apply_program0_validation,
    collect_program0_outputs,
)
from sasguard.execution.result import ExecutionResult, ExecutionStatus
from sasguard.provenance.hashing import sha256_file
from sasguard.verification.artifact import ArtifactComparison, ReferenceSource


def comparisons(*, passed: bool = True) -> dict[str, ArtifactComparison]:
    return {
        filename: ArtifactComparison(
            artifact=Path(filename).stem.upper(),
            passed=passed,
            reference_source=ReferenceSource.SAS7BDAT,
            expected_rows=1,
            actual_rows=1,
            expected_columns=["VALUE"],
            actual_columns=["VALUE"],
            mismatched_cells=0 if passed else 1,
        )
        for filename in OUTPUT_FILENAMES
    }


@pytest.fixture
def collected(tmp_path: Path) -> tuple[Path, CandidateReport]:
    output = tmp_path / "reports/runs/candidate-test/output"
    output.mkdir(parents=True)
    for filename in OUTPUT_FILENAMES:
        (output / filename).write_text("VALUE\n1\n", encoding="utf-8")
    execution = ExecutionResult(
        execution_id=uuid4(),
        status=ExecutionStatus.SUCCEEDED,
        exit_code=0,
        runtime_seconds=0.1,
        output_files=list(OUTPUT_FILENAMES),
    )
    report = collect_program0_outputs(output).model_copy(update={"execution_result": execution})
    return output, report


@pytest.mark.parametrize(
    "status", ["passed", "failed", "hash_mismatch", "missing_outputs", "malformed_outputs"]
)
def test_each_validator_outcome_is_separate_from_execution(
    tmp_path: Path, collected: tuple[Path, CandidateReport], status: str
) -> None:
    output, report = collected
    expected = {name: item.sha256 for name, item in report.artifacts.items()}
    results = comparisons(passed=status == "passed") if status in ("passed", "failed") else {}
    outcome = CandidateValidationResult.model_validate(
        {"status": status, "artifact_results": results}
    )
    calls = []

    def validator(
        project_root: Path, output_directory: Path, expected_sha256: Mapping[str, str]
    ) -> CandidateValidationResult:
        calls.append((project_root, output_directory, dict(expected_sha256)))
        return outcome

    actual = apply_program0_validation(tmp_path, output, report, validator)
    assert calls == [(tmp_path.resolve(), output.resolve(), expected)]
    assert actual.validation_status == status
    assert actual.validation_results == results
    assert actual.status is CandidateStatus.READY
    assert actual.execution_result == report.execution_result
    assert actual.human_review == "not_recorded"
    assert CandidateReport.model_validate_json(actual.model_dump_json()) == actual
    assert report.validation_status == "not_run"
    assert report.validation_results == {}


@pytest.mark.parametrize(
    "status", [item for item in CandidateStatus if item is not CandidateStatus.READY]
)
def test_collection_or_execution_failures_never_call_validator(
    tmp_path: Path, collected: tuple[Path, CandidateReport], status: CandidateStatus
) -> None:
    output, report = collected

    def forbidden(*args: object) -> CandidateValidationResult:
        raise AssertionError("failed collection must not reach a validator")

    report = report.model_copy(update={"status": status})
    assert apply_program0_validation(tmp_path, output, report, forbidden) is report


@pytest.mark.parametrize(
    "execution_status", [None, ExecutionStatus.FAILED, ExecutionStatus.TIMED_OUT]
)
def test_ready_without_successful_execution_does_not_call_validator(
    tmp_path: Path,
    collected: tuple[Path, CandidateReport],
    execution_status: ExecutionStatus | None,
) -> None:
    output, report = collected
    execution = (
        None
        if execution_status is None
        else ExecutionResult(
            execution_id=uuid4(),
            status=execution_status,
            exit_code=7 if execution_status is ExecutionStatus.FAILED else None,
            runtime_seconds=0.1,
        )
    )
    report = report.model_copy(update={"execution_result": execution})

    def forbidden(*args: object) -> CandidateValidationResult:
        raise AssertionError("unsuccessful execution must not reach a validator")

    assert apply_program0_validation(tmp_path, output, report, forbidden) is report


@pytest.mark.parametrize(
    "error",
    [
        OSError("unreadable"),
        ValueError("bad result"),
        RuntimeError("stopped"),
        KeyError("missing result"),
    ],
)
def test_validator_errors_never_become_analytical_passes(
    tmp_path: Path, collected: tuple[Path, CandidateReport], error: Exception
) -> None:
    output, report = collected

    def validator(*args: object) -> CandidateValidationResult:
        raise error

    result = apply_program0_validation(tmp_path, output, report, validator)
    assert result.validation_status == "validator_error"
    assert result.validation_results == {}
    assert result.validation_error == str(error)
    assert result.execution_result == report.execution_result


@pytest.mark.parametrize(
    "change",
    [
        "incomplete",
        "failed_comparison",
        "unknown_file",
        "wrong_artifact",
        "csv",
        "unknown_status",
        "empty_failure",
    ],
)
def test_inconsistent_validator_results_fail_closed(
    tmp_path: Path, collected: tuple[Path, CandidateReport], change: str
) -> None:
    output, report = collected
    results = comparisons()
    status = "passed"
    first = OUTPUT_FILENAMES[0]
    if change == "incomplete":
        del results[first]
    elif change == "failed_comparison":
        results = comparisons(passed=False)
    elif change == "unknown_file":
        results["unknown.csv"] = results.pop(first)
    elif change == "wrong_artifact":
        results[first] = results[first].model_copy(update={"artifact": "OTHER"})
    elif change == "csv":
        results[first] = results[first].model_copy(update={"reference_source": ReferenceSource.CSV})
    elif change == "unknown_status":
        status = "unknown"
    else:
        status, results = "failed", {}

    def validator(*args: object) -> CandidateValidationResult:
        # Simulate a callback returning an unchecked or inconsistent object.
        return CandidateValidationResult.model_construct(status=status, artifact_results=results)

    result = apply_program0_validation(tmp_path, output, report, validator)
    assert result.validation_status == "validator_error"
    assert result.validation_results == {}


@pytest.mark.parametrize("change", ["missing_metadata", "bad_hash", "wrong_path", "outside"])
def test_invalid_handoff_is_rejected_before_calling_validator(
    tmp_path: Path, collected: tuple[Path, CandidateReport], change: str
) -> None:
    output, report = collected
    artifacts = dict(report.artifacts)
    first = OUTPUT_FILENAMES[0]
    if change == "missing_metadata":
        del artifacts[first]
    elif change == "bad_hash":
        artifacts[first] = artifacts[first].model_copy(update={"sha256": "invalid"})
    elif change == "wrong_path":
        artifacts[first] = artifacts[first].model_copy(update={"relative_path": "../gold.csv"})
    else:
        output = tmp_path.parent / "outside/output"
    report = report.model_copy(update={"artifacts": artifacts})
    calls = []

    def forbidden(*args: object) -> CandidateValidationResult:
        calls.append(args)
        raise AssertionError("invalid metadata must not reach a validator")

    assert (
        apply_program0_validation(tmp_path, output, report, forbidden).validation_status
        == "validator_error"
    )
    assert calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"validation_status": "passed"},
        {"validation_results": comparisons()},
        {"validation_status": "failed"},
        {"validation_status": "validator_error"},
        {
            "validation_status": "passed",
            "validation_results": comparisons(),
            "execution_result": None,
        },
        {
            "validation_status": "validator_error",
            "validation_error": "error",
            "validation_results": comparisons(),
        },
    ],
)
def test_saved_candidate_report_rejects_inconsistent_validation_claims(
    collected: tuple[Path, CandidateReport], change: dict[str, object]
) -> None:
    _, report = collected
    with pytest.raises(ValueError):
        CandidateReport.model_validate({**report.model_dump(), **change})


def test_validator_receives_original_hashes_after_output_changes(
    tmp_path: Path, collected: tuple[Path, CandidateReport]
) -> None:
    output, report = collected
    (output / OUTPUT_FILENAMES[0]).write_text("VALUE\n999\n", encoding="utf-8")

    def validator(
        project_root: Path, output_directory: Path, expected_sha256: Mapping[str, str]
    ) -> CandidateValidationResult:
        assert expected_sha256[OUTPUT_FILENAMES[0]] == report.artifacts[OUTPUT_FILENAMES[0]].sha256
        assert (
            sha256_file(output_directory / OUTPUT_FILENAMES[0])
            != expected_sha256[OUTPUT_FILENAMES[0]]
        )
        return CandidateValidationResult(status="hash_mismatch")

    result = apply_program0_validation(tmp_path, output, report, validator)
    assert result.validation_status == "hash_mismatch"


def test_existing_validation_is_not_silently_replaced(
    tmp_path: Path, collected: tuple[Path, CandidateReport]
) -> None:
    output, report = collected
    report = report.model_copy(update={"validation_status": "hash_mismatch"})

    def forbidden(*args: object) -> CandidateValidationResult:
        raise AssertionError("recorded validation must not be silently replaced")

    assert apply_program0_validation(tmp_path, output, report, forbidden) is report


def test_legacy_collection_record_still_loads_as_unvalidated(
    collected: tuple[Path, CandidateReport],
) -> None:
    _, report = collected
    legacy = report.model_dump()
    del legacy["validation_results"]
    del legacy["validation_error"]
    loaded = CandidateReport.model_validate(legacy)
    assert loaded.validation_status == "not_run"
    assert loaded.validation_results == {}
    assert loaded.validation_error is None
    assert loaded.execution_result == report.execution_result
