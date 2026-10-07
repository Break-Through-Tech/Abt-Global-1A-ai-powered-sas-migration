# Artifact Comparison Policy

SASGuard separates comparison policy from comparison execution. The policy states what must
match and which differences cause failure. The comparator in issue #9 will apply this policy to
generated and trusted artifacts.

## Required behavior

- Rows align by one or more configured keys, never by row position.
- CMS comparisons use `PROVIDER_ID` as a string key so leading zeros remain significant.
- Key columns must exist, contain no missing values, and be unique in both artifacts.
- Column names resolve case-insensitively to match SAS conventions. Reports preserve the original
  spelling from each artifact.
- Identifiers, strings, booleans, categories, and configured exact columns compare exactly.
- Numeric columns use both an absolute tolerance and a relative tolerance.
- A missing value matches only another missing value. Missing values are different from numeric
  zero and from empty text.
- Missing or additional rows and columns are always reported and always fail the comparison.
- Ambiguous column names such as `score` and `SCORE` in the same artifact are rejected.

## Numeric rule

Two finite numeric values match when their absolute difference is less than or equal to:

```text
absolute_tolerance + relative_tolerance * abs(reference_value)
```

Tolerances must be finite and non-negative. A value-specific tolerance can override the default
numeric tolerance. Exact column rules cannot define a tolerance.

## Example

```python
from sasguard.verification import (
    ArtifactComparisonPolicy,
    ColumnComparisonPolicy,
    ComparisonKind,
    NumericTolerance,
)

policy = ArtifactComparisonPolicy(
    keys=("PROVIDER_ID",),
    default_numeric_tolerance=NumericTolerance(
        absolute=1e-10,
        relative=1e-8,
    ),
    columns=(
        ColumnComparisonPolicy(name="PEER_GROUP", kind=ComparisonKind.EXACT),
        ColumnComparisonPolicy(
            name="SUMMARY_SCORE",
            kind=ComparisonKind.NUMERIC,
            tolerance=NumericTolerance(absolute=1e-9, relative=1e-7),
        ),
    ),
)

policy_json = policy.to_json()
```

The policy contains no trusted output values. It can therefore be created, reviewed, and shared
without exposing golden artifacts to translation or repair components.

## Responsibility boundary

This module validates and serializes policy. It does not load reference artifacts, align rows, or
judge values. Issue #9 owns the deterministic comparator that consumes this contract. Issue #11
can use the comparator and policy to evaluate the bounded Mortality transformation.
