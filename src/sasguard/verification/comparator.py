"""Policy-driven comparison of generated and trusted tabular artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

from sasguard.columns import resolve_column_name
from sasguard.data import LoadedArtifact
from sasguard.verification.artifact import ArtifactComparison, ReferenceSource
from sasguard.verification.policy import (
    ArtifactComparisonPolicy,
    ColumnComparisonPolicy,
    ComparisonKind,
    NumericTolerance,
)

Key = tuple[str, ...]


class ComparisonInputError(ValueError):
    """Raised when an artifact cannot be aligned under a comparison policy."""


@dataclass(frozen=True, slots=True)
class _ColumnOutcome:
    exact_cells: int
    mismatched_cells: int
    missingness_mismatches: int
    absolute_errors: tuple[float, ...] = ()


def _column_map(frame: pd.DataFrame, label: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for column in frame.columns:
        if not isinstance(column, str) or not column.strip():
            raise ComparisonInputError(f"{label} artifact columns must be non-blank strings")
        canonical = column.casefold()
        if canonical in mapping:
            raise ComparisonInputError(
                f"{label} artifact has ambiguous case-insensitive columns: "
                f"{mapping[canonical]!r} and {column!r}"
            )
        mapping[canonical] = column
    return mapping


def _resolve_keys(frame: pd.DataFrame, requested: tuple[str, ...], label: str) -> tuple[str, ...]:
    try:
        return tuple(resolve_column_name(name, list(frame.columns)) for name in requested)
    except (KeyError, ValueError) as error:
        raise ComparisonInputError(f"invalid {label} comparison key: {error}") from error


def _key_positions(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> dict[Key, int]:
    key_frame = frame.loc[:, list(columns)]
    if key_frame.isna().any(axis=None):
        count = int(key_frame.isna().any(axis=1).sum())
        raise ComparisonInputError(
            f"{label} artifact has {count} rows with missing comparison keys"
        )

    positions: dict[Key, int] = {}
    duplicate_count = 0
    for position, values in enumerate(key_frame.itertuples(index=False, name=None)):
        if any(not isinstance(value, str) for value in values):
            raise ComparisonInputError(f"{label} artifact comparison keys must be textual")
        key = tuple(values)
        if key in positions:
            duplicate_count += 1
        else:
            positions[key] = position

    if duplicate_count:
        raise ComparisonInputError(
            f"{label} artifact has {duplicate_count} duplicate comparison-key rows"
        )
    return positions


def _render_key(key: Key, names: tuple[str, ...]) -> str:
    if len(key) == 1:
        return key[0]
    payload = dict(zip(names, key, strict=True))
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _aligned_series(
    frame: pd.DataFrame,
    column: str,
    positions: dict[Key, int],
    keys: list[Key],
) -> pd.Series:
    row_positions = [positions[key] for key in keys]
    return frame.iloc[row_positions][column].reset_index(drop=True)


def _compare_exact(expected: pd.Series, actual: pd.Series) -> _ColumnOutcome:
    expected_missing = expected.isna().to_numpy(dtype=bool)
    actual_missing = actual.isna().to_numpy(dtype=bool)
    both_missing = expected_missing & actual_missing
    missingness_mismatch = expected_missing ^ actual_missing
    both_present = ~(expected_missing | actual_missing)

    equal = np.zeros(len(expected.index), dtype=bool)
    if both_present.any():
        expected_values = expected.to_numpy(dtype=object)[both_present]
        actual_values = actual.to_numpy(dtype=object)[both_present]
        equal[both_present] = np.asarray(expected_values == actual_values, dtype=bool)

    mismatched = missingness_mismatch | (both_present & ~equal)
    return _ColumnOutcome(
        exact_cells=int((both_missing | equal).sum()),
        mismatched_cells=int(mismatched.sum()),
        missingness_mismatches=int(missingness_mismatch.sum()),
    )


def _compare_numeric(
    expected: pd.Series,
    actual: pd.Series,
    tolerance: NumericTolerance,
    column: str,
) -> _ColumnOutcome:
    if (
        not is_numeric_dtype(expected.dtype)
        or not is_numeric_dtype(actual.dtype)
        or is_bool_dtype(expected.dtype)
        or is_bool_dtype(actual.dtype)
    ):
        raise ComparisonInputError(
            f"numeric comparison requires numeric values on both sides for column {column!r}"
        )

    expected_missing = expected.isna().to_numpy(dtype=bool)
    actual_missing = actual.isna().to_numpy(dtype=bool)
    both_missing = expected_missing & actual_missing
    missingness_mismatch = expected_missing ^ actual_missing
    both_present = ~(expected_missing | actual_missing)

    expected_values = expected.to_numpy(dtype=float, na_value=np.nan)
    actual_values = actual.to_numpy(dtype=float, na_value=np.nan)
    finite_pairs = both_present & np.isfinite(expected_values) & np.isfinite(actual_values)
    exact = both_present & (expected_values == actual_values)

    absolute_error = np.zeros(len(expected.index), dtype=float)
    absolute_error[finite_pairs] = np.abs(
        actual_values[finite_pairs] - expected_values[finite_pairs]
    )
    allowed_error = tolerance.absolute + tolerance.relative * np.abs(expected_values)
    within_tolerance = exact | (finite_pairs & (absolute_error <= allowed_error))
    mismatched = missingness_mismatch | (both_present & ~within_tolerance)

    return _ColumnOutcome(
        exact_cells=int((both_missing | exact).sum()),
        mismatched_cells=int(mismatched.sum()),
        missingness_mismatches=int(missingness_mismatch.sum()),
        absolute_errors=tuple(float(value) for value in absolute_error[finite_pairs]),
    )


def _rule_map(policy: ArtifactComparisonPolicy) -> dict[str, ColumnComparisonPolicy]:
    return {rule.name.casefold(): rule for rule in policy.columns}


def compare_artifacts(
    actual: LoadedArtifact,
    expected: LoadedArtifact,
    *,
    artifact: str,
    policy: ArtifactComparisonPolicy,
) -> ArtifactComparison:
    """Compare an actual artifact with a trusted expected artifact by configured keys."""
    expected_columns = _column_map(expected.frame, "expected")
    actual_columns = _column_map(actual.frame, "actual")
    expected_key_columns = _resolve_keys(expected.frame, policy.keys, "expected")
    actual_key_columns = _resolve_keys(actual.frame, policy.keys, "actual")
    expected_positions = _key_positions(expected.frame, expected_key_columns, "expected")
    actual_positions = _key_positions(actual.frame, actual_key_columns, "actual")

    expected_keys = set(expected_positions)
    actual_keys = set(actual_positions)
    missing_key_values = sorted(
        expected_keys - actual_keys, key=lambda key: _render_key(key, policy.keys)
    )
    extra_key_values = sorted(
        actual_keys - expected_keys, key=lambda key: _render_key(key, policy.keys)
    )
    common_keys = sorted(expected_keys & actual_keys, key=lambda key: _render_key(key, policy.keys))

    missing_column_names = [
        column for canonical, column in expected_columns.items() if canonical not in actual_columns
    ]
    extra_column_names = [
        column for canonical, column in actual_columns.items() if canonical not in expected_columns
    ]

    rules = _rule_map(policy)
    known_columns = set(expected_columns) | set(actual_columns)
    unknown_rules = [
        rule.name for canonical, rule in rules.items() if canonical not in known_columns
    ]
    if unknown_rules:
        rendered = ", ".join(unknown_rules)
        raise ComparisonInputError(f"comparison policy refers to unknown columns: {rendered}")

    key_names = {name.casefold() for name in policy.keys}
    common_columns = [
        canonical
        for canonical in expected_columns
        if canonical in actual_columns and canonical not in key_names
    ]

    exact_cells = 0
    mismatched_cells = 0
    missingness_mismatches = 0
    absolute_errors: list[float] = []
    mismatched_columns: list[str] = []

    for canonical in common_columns:
        expected_name = expected_columns[canonical]
        actual_name = actual_columns[canonical]
        expected_values = _aligned_series(
            expected.frame, expected_name, expected_positions, common_keys
        )
        actual_values = _aligned_series(actual.frame, actual_name, actual_positions, common_keys)

        rule = rules.get(canonical)
        numeric = rule is not None and rule.kind is ComparisonKind.NUMERIC
        if rule is None:
            numeric = (
                is_numeric_dtype(expected_values.dtype)
                and is_numeric_dtype(actual_values.dtype)
                and not is_bool_dtype(expected_values.dtype)
                and not is_bool_dtype(actual_values.dtype)
            )

        if numeric:
            tolerance = (
                rule.tolerance
                if rule is not None and rule.tolerance is not None
                else policy.default_numeric_tolerance
            )
            outcome = _compare_numeric(expected_values, actual_values, tolerance, expected_name)
        else:
            outcome = _compare_exact(expected_values, actual_values)

        exact_cells += outcome.exact_cells
        mismatched_cells += outcome.mismatched_cells
        missingness_mismatches += outcome.missingness_mismatches
        absolute_errors.extend(outcome.absolute_errors)
        if outcome.mismatched_cells:
            mismatched_columns.append(expected_name)

    missing_keys = [_render_key(key, policy.keys) for key in missing_key_values]
    extra_keys = [_render_key(key, policy.keys) for key in extra_key_values]
    failed = any(
        (
            missing_keys,
            extra_keys,
            missing_column_names,
            extra_column_names,
            mismatched_columns,
        )
    )

    return ArtifactComparison(
        artifact=artifact,
        passed=not failed,
        reference_source=ReferenceSource(expected.format.value),
        expected_rows=expected.row_count,
        actual_rows=actual.row_count,
        expected_columns=list(expected.columns),
        actual_columns=list(actual.columns),
        missing_keys=missing_keys,
        extra_keys=extra_keys,
        missing_columns=missing_column_names,
        extra_columns=extra_column_names,
        mismatched_columns=mismatched_columns,
        exact_cells=exact_cells,
        mismatched_cells=mismatched_cells,
        missingness_mismatches=missingness_mismatches,
        max_abs_error=max(absolute_errors) if absolute_errors else None,
        mean_abs_error=(sum(absolute_errors) / len(absolute_errors)) if absolute_errors else None,
    )
