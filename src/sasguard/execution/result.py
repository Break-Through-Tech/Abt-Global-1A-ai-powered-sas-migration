"""Machine-readable results from isolated generated-code execution."""

import json
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sasguard.provenance.hashing import normalize_relative_path


class ExecutionStatus(StrEnum):
    """Terminal state of an isolated execution attempt."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    POLICY_VIOLATION = "policy_violation"
    RUNNER_ERROR = "runner_error"


class ExecutionResult(BaseModel):
    """Structured outcome of running generated Python in isolation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    execution_id: UUID
    status: ExecutionStatus
    exit_code: int | None
    runtime_seconds: float = Field(ge=0, allow_inf_nan=False)
    stdout: str = ""
    stderr: str = ""
    output_files: list[str] = Field(default_factory=list)
    policy_violations: list[str] = Field(default_factory=list)

    @field_validator("output_files")
    @classmethod
    def validate_output_files(cls, values: list[str]) -> list[str]:
        normalized = [normalize_relative_path(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("output file paths must be unique")
        return sorted(normalized)

    @field_validator("policy_violations")
    @classmethod
    def validate_policy_violations(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("policy violations must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("policy violations must be unique")
        return sorted(cleaned)

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status is ExecutionStatus.SUCCEEDED and self.exit_code != 0:
            raise ValueError("successful execution requires exit code 0")
        if self.status is ExecutionStatus.FAILED and (
            self.exit_code is None or self.exit_code == 0
        ):
            raise ValueError("failed execution requires a nonzero exit code")
        if self.status is ExecutionStatus.TIMED_OUT and self.exit_code is not None:
            raise ValueError("timed-out execution must not report an exit code")
        if self.status is ExecutionStatus.POLICY_VIOLATION and not self.policy_violations:
            raise ValueError("policy violation status requires at least one violation")
        if self.status is not ExecutionStatus.POLICY_VIOLATION and self.policy_violations:
            raise ValueError("policy violations require policy violation status")
        return self

    @property
    def passed(self) -> bool:
        """Return whether generated code completed without detected violations."""
        return self.status is ExecutionStatus.SUCCEEDED

    def to_json(self) -> str:
        """Serialize deterministically for run records and command output."""
        payload = self.model_dump(mode="json")
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"
