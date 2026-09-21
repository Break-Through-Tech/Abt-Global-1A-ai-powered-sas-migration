"""Versioned, deterministic execution manifests."""

import json
from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sasguard.execution.result import ExecutionResult
from sasguard.provenance.hashing import normalize_relative_path, validate_sha256
from sasguard.verification.artifact import ArtifactComparison, ReferenceSource


def _validate_hash_mapping(values: dict[str, str]) -> dict[str, str]:
    normalized = {
        normalize_relative_path(path): validate_sha256(digest) for path, digest in values.items()
    }
    if len(normalized) != len(values):
        raise ValueError("file hash paths must be unique after normalization")
    return dict(sorted(normalized.items()))


class TokenUsage(BaseModel):
    """Optional token accounting for a translation request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total tokens must equal input plus output tokens")
        return self


class RunManifest(BaseModel):
    """Audit record for one deterministic execution or migration run."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    schema_version: Literal[1] = 1
    run_id: UUID
    timestamp: datetime
    source_hashes: dict[str, str] = Field(min_length=1)
    input_hashes: dict[str, str] = Field(min_length=1)
    generated_code_hashes: dict[str, str] = Field(default_factory=dict)

    model_name: str | None = Field(
        default=None, min_length=1, validation_alias="model", serialization_alias="model"
    )
    temperature: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    prompt_version: str | None = Field(default=None, min_length=1)
    token_usage: TokenUsage | None = None
    estimated_cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    repair_attempts: int = Field(default=0, ge=0)
    runtime_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    execution_result: ExecutionResult | None = None
    reference_sources: dict[str, ReferenceSource] = Field(default_factory=dict)
    artifact_results: dict[str, ArtifactComparison] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value.astimezone(UTC)

    @field_validator("source_hashes", "input_hashes", "generated_code_hashes")
    @classmethod
    def validate_hashes(cls, values: dict[str, str]) -> dict[str, str]:
        return _validate_hash_mapping(values)

    @field_validator("reference_sources")
    @classmethod
    def sort_reference_sources(
        cls, values: dict[str, ReferenceSource]
    ) -> dict[str, ReferenceSource]:
        return dict(sorted(values.items()))

    @field_validator("artifact_results")
    @classmethod
    def validate_artifact_result_keys(
        cls, values: dict[str, ArtifactComparison]
    ) -> dict[str, ArtifactComparison]:
        for artifact, result in values.items():
            if artifact != result.artifact:
                raise ValueError(
                    f"artifact result key {artifact!r} does not match {result.artifact!r}"
                )
        return dict(sorted(values.items()))

    @model_validator(mode="after")
    def validate_translation_and_references(self) -> Self:
        translation_fields = (self.model_name, self.temperature, self.prompt_version)
        if any(value is not None for value in translation_fields) and any(
            value is None for value in translation_fields
        ):
            raise ValueError("model, temperature, and prompt_version must be recorded together")
        if self.token_usage is not None and self.model_name is None:
            raise ValueError("token usage requires translation metadata")
        if self.estimated_cost_usd is not None and self.model_name is None:
            raise ValueError("estimated cost requires translation metadata")

        for artifact, result in self.artifact_results.items():
            source = self.reference_sources.get(artifact)
            if source is not None and source != result.reference_source:
                raise ValueError(f"reference source for {artifact!r} conflicts with its result")
        if (
            self.execution_result is not None
            and self.runtime_seconds != self.execution_result.runtime_seconds
        ):
            raise ValueError("manifest runtime must match its execution result")
        return self

    def with_execution_result(self, result: ExecutionResult) -> Self:
        """Return a copy populated from an isolated execution result."""
        return self.model_copy(
            update={
                "execution_result": result,
                "runtime_seconds": result.runtime_seconds,
            }
        )

    @classmethod
    def create(cls, **values: Any) -> Self:
        """Create a manifest with a fresh UUID and current UTC timestamp."""
        return cls(
            run_id=uuid4(),
            timestamp=datetime.now(UTC),
            **values,
        )

    def to_json(self) -> str:
        """Serialize deterministically for audit logs and versioned reports."""
        payload = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"
