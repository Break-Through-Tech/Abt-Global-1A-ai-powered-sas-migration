# Program 0 output validation

`validate_program0_outputs` checks the three Program 0 output CSVs against the trusted SAS
artifacts. It is the host-side validator for issue #44. It runs after candidate execution has
finished and never runs candidate code itself.

```python
from pathlib import Path

from sasguard.verification.program0 import validate_program0_outputs

result = validate_program0_outputs(
    project_root=Path("."),
    output_directory=Path("reports/runs/<run>/output"),
    expected_sha256={  # filename -> SHA-256 recorded when the outputs were collected
        "less100_measure.csv": "...",
        "measure_average_stddev_2025jul.csv": "...",
        "std_data_2025jul_analysis.csv": "...",
    },
)
print(result.status)
```

## What it checks

The validator stops at the first stage that fails:

1. **Presence.** All three CSVs must exist as regular files. Symlinks count as missing.
2. **Hashes.** Each file's SHA-256 must match the hash recorded at collection, so the files being
   compared are the ones the runner collected. Hashes use the same LF normalization as the
   protected-artifact check.
3. **Readability.** Each CSV is loaded with the shared `load_artifact`. Missing or duplicate key
   values, a missing key column, or non-numeric values in a numeric column make the file
   malformed.
4. **Comparison.** Each CSV is compared with its SAS binary using `compare_artifacts` and the
   committed policy in `configs/program0-comparison-policies.json`.

| Artifact | Key | Policy |
|---|---|---|
| `LESS100_MEASURE` | `MEASURE_NAME` | Exact. Empty for July 2025, so a candidate passes only if it also excludes no measures. |
| `MEASURE_AVERAGE_STDDEV_2025JUL` | `_STAT_` | `N`, `MIN`, and `MAX` rows exact. For `MEAN` and `STD`, measure columns use `1e-12` tolerances. `_TYPE_` and `_FREQ_` are always exact. |
| `STD_DATA_2025JUL_ANALYSIS` | `PROVIDER_ID` | The 46 `STD_` columns use `1e-12` tolerances; all other columns are exact. |

These rules match the Program 0 reference check in #53. The committed policy declares the
exact statistic rows. The controller compares those rows separately with the shared comparator
and combines their diagnostics with the tolerant comparison of the remaining rows. Numeric
error summaries cover the tolerant rows; exact-row differences still count as mismatched cells.

## Result

`Program0Validation` has three fields:

| Field | Meaning |
|---|---|
| `status` | `passed`, `failed`, `hash_mismatch`, `missing_outputs`, or `malformed_outputs` |
| `artifact_results` | Output filename → existing `ArtifactComparison`. Filled only when all three files were compared. |
| `errors` | Output filename → short reason, for missing, changed, or unreadable files |

`failed` means every file was compared and at least one comparison failed. The comparison lists
the mismatched columns, missing or extra providers, missingness differences, and the largest
numeric error.

The function raises `ValueError` if `expected_sha256` does not name exactly the three outputs,
because that is a caller error rather than a candidate failure.

## Connecting the #55 runner

The runner's `CandidateValidationResult` accepts the same `status` and `artifact_results`. A
callback can convert the result with:

```python
CandidateValidationResult.model_validate(result.model_dump(exclude={"errors"}))
```

## Tests

`tests/integration/test_program0_validation.py` uses the real supplied data and covers:

- The Program 0 human reference passes all three checks.
- A deliberate semantic error (one lower-is-better measure not reversed) runs but fails, naming
  the affected column.
- A dropped hospital, a missing file, a file changed after collection, and a duplicate provider row.

```sh
docker compose run --rm sasguard pytest tests/integration/test_program0_validation.py
```
