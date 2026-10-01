"""Machine-readable results for artifact comparisons."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReferenceSource(StrEnum):
    """Supported authorities for a trusted reference artifact."""

    CSV = "csv"
    SAS7BDAT = "sas7bdat"


class ArtifactComparison(BaseModel):
    """Structured outcome of comparing one generated and trusted artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact: str = Field(min_length=1)
    passed: bool
    reference_source: ReferenceSource

    expected_rows: int = Field(ge=0)
    actual_rows: int = Field(ge=0)

    expected_columns: list[str]
    actual_columns: list[str]

    missing_keys: list[str] = Field(default_factory=list)
    extra_keys: list[str] = Field(default_factory=list)
    missing_columns: list[str] = Field(default_factory=list)
    extra_columns: list[str] = Field(default_factory=list)
    mismatched_columns: list[str] = Field(default_factory=list)

    exact_cells: int = Field(default=0, ge=0)
    mismatched_cells: int = Field(default=0, ge=0)
    missingness_mismatches: int = Field(default=0, ge=0)

    max_abs_error: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    mean_abs_error: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("artifact")
    @classmethod
    def validate_artifact_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("artifact name must not be blank")
        return name

    @field_validator(
        "expected_columns",
        "actual_columns",
        "missing_keys",
        "extra_keys",
        "missing_columns",
        "extra_columns",
        "mismatched_columns",
    )
    @classmethod
    def validate_unique_nonempty_values(cls, values: list[str]) -> list[str]:
        """Reject ambiguous diagnostics caused by blank or duplicated names."""
        if any(not value.strip() for value in values):
            raise ValueError("comparison names and keys must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("comparison names and keys must be unique")
        return values

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        """Keep summary fields internally consistent."""
        errors_present = self.max_abs_error is not None or self.mean_abs_error is not None
        if errors_present and (self.max_abs_error is None or self.mean_abs_error is None):
            raise ValueError("maximum and mean absolute error must be recorded together")
        if (
            self.max_abs_error is not None
            and self.mean_abs_error is not None
            and self.mean_abs_error > self.max_abs_error
        ):
            raise ValueError("mean absolute error cannot exceed maximum absolute error")

        if not self.passed:
            return self

        has_failure = any(
            (
                self.expected_rows != self.actual_rows,
                set(self.expected_columns) != set(self.actual_columns),
                bool(self.missing_keys),
                bool(self.extra_keys),
                bool(self.missing_columns),
                bool(self.extra_columns),
                bool(self.mismatched_columns),
                self.mismatched_cells != 0,
                self.missingness_mismatches != 0,
            )
        )
        if has_failure:
            raise ValueError("a passing comparison cannot contain structural mismatches")
        return self
