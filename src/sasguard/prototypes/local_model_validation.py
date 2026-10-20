"""Versioned numeric contracts for synthetic experiments, independent of model output."""

from sasguard.prototypes.local_model_cases import CASES, SyntheticCase
from sasguard.prototypes.local_model_holdout import HOLDOUT_CASES
from sasguard.verification.policy import (
    ArtifactComparisonPolicy,
    ColumnComparisonPolicy,
    ComparisonKind,
)

VALIDATION_POLICY_VERSION = "synthetic-numeric-v2"
CASE_SETS = {"development": CASES, "holdout-v1": HOLDOUT_CASES}
NUMERIC_COLUMNS = {
    "double-score": ("SCORE", "ADJUSTED"),
    "missing-comparison": ("SCORE", "FLAG"),
    "sum-missing": ("SCORE", "OTHER", "ARITH_SUM", "FUNC_SUM"),
    "grouped-mean": ("COUNT", "MEAN"),
    "holdout-threshold": ("SCORE", "FLAG"),
    "holdout-sum-three": ("A", "B", "C", "ARITH_TOTAL", "FUNC_TOTAL"),
    "holdout-grouped-keys": ("COUNT", "MEAN"),
    "holdout-affine": ("SCORE", "ADJUSTED"),
}


def select_cases(case_set: str) -> dict[str, SyntheticCase]:
    if case_set not in CASE_SETS:
        raise ValueError(f"unknown case set {case_set!r}; choose from {', '.join(CASE_SETS)}")
    return CASE_SETS[case_set]


def numeric_policy(fixture: SyntheticCase) -> ArtifactComparisonPolicy:
    """Require numeric columns even if the candidate emits Boolean or textual values."""
    return ArtifactComparisonPolicy(
        keys=(fixture.key,),
        columns=tuple(
            ColumnComparisonPolicy(name=name, kind=ComparisonKind.NUMERIC)
            for name in NUMERIC_COLUMNS[fixture.name]
        ),
    )
