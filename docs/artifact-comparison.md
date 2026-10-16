# Keyed Artifact Comparison

SASGuard compares generated and trusted tables by configured identifiers instead of row position.
The comparator consumes `LoadedArtifact` values and an `ArtifactComparisonPolicy`, then returns a
serializable `ArtifactComparison` result.

## Comparison sequence

1. Resolve key and data columns case-insensitively.
2. Reject missing, non-textual, or duplicate comparison keys.
3. Align common rows by their keys.
4. Report identifiers that exist on only one side.
5. Report missing and extra columns.
6. Compare common non-key columns using exact or numeric rules.
7. Count missingness mismatches separately from other cell mismatches.
8. Calculate maximum and mean absolute error across finite numeric pairs.

Missing or extra keys and columns always fail validation. They are retained in the structured
result so diagnostics can explain the failure without exposing complete trusted rows.

## Exact and numeric values

Text, category, and explicitly exact columns use case-sensitive value equality. A missing value
matches only another missing value.

Numeric columns use the tolerance formula defined in `comparison-policy.md`. Errors within the
configured tolerance pass. Maximum and mean absolute error still record the observed finite
differences, including differences that pass tolerance.

`exact_cells` counts values that are exactly equal plus pairs where both values are missing.
`mismatched_cells` counts missingness differences and values that fail their comparison rule.
Tolerated but non-identical numeric values belong to neither count.

## Example

```python
from sasguard.data import load_artifact
from sasguard.verification import ArtifactComparisonPolicy, compare_artifacts

policy = ArtifactComparisonPolicy(keys=("PROVIDER_ID",))
actual = load_artifact(generated_path, key="PROVIDER_ID")
expected = load_artifact(reference_path, key="PROVIDER_ID")

result = compare_artifacts(
    actual,
    expected,
    artifact="OUTCOME_MORTALITY",
    policy=policy,
)
```

The comparator reads the trusted artifact only through the validator process. The generated-code
runner does not receive trusted reference paths or comparison results containing complete rows.
