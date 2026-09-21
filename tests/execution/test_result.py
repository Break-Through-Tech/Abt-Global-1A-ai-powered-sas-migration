"""Tests for isolated execution result validation."""

import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from sasguard.execution.result import ExecutionResult, ExecutionStatus

EXECUTION_ID = UUID("12345678-1234-5678-1234-567812345678")


def test_successful_result_is_deterministic_and_passes() -> None:
    result = ExecutionResult(
        execution_id=EXECUTION_ID,
        status=ExecutionStatus.SUCCEEDED,
        exit_code=0,
        runtime_seconds=1.25,
        stdout="complete\n",
        output_files=["results/output.csv", "summary.json"],
    )

    assert result.passed
    assert result.to_json() == result.to_json()
    assert json.loads(result.to_json())["status"] == "succeeded"


@pytest.mark.parametrize(
    "values",
    [
        {"status": "succeeded", "exit_code": 1},
        {"status": "failed", "exit_code": 0},
        {"status": "timed_out", "exit_code": 137},
        {"status": "policy_violation", "exit_code": 0},
        {
            "status": "failed",
            "exit_code": 1,
            "policy_violations": ["forbidden output"],
        },
    ],
)
def test_inconsistent_status_is_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ExecutionResult(
            execution_id=EXECUTION_ID,
            runtime_seconds=1,
            **values,
        )


def test_output_paths_are_normalized_and_must_be_relative() -> None:
    result = ExecutionResult(
        execution_id=EXECUTION_ID,
        status="succeeded",
        exit_code=0,
        runtime_seconds=1,
        output_files=[r"results\output.csv"],
    )

    assert result.output_files == ["results/output.csv"]

    with pytest.raises(ValidationError, match="repository-relative"):
        ExecutionResult(
            execution_id=EXECUTION_ID,
            status="succeeded",
            exit_code=0,
            runtime_seconds=1,
            output_files=["../outside.csv"],
        )
