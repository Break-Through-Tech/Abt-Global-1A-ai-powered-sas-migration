# Program 1 domain scoring (human reference)

This is the human-written Python reference for Program 1 (issue #50). It reads the supplied
Program 0 standardized SAS binary, `STD_DATA_2025JUL_ANALYSIS`, and produces the five domain
artifacts. Each artifact is then compared with its trusted SAS output.

It is not a model-backed translation, a repair loop, or Program 2 code.

## What it calculates

For each domain, every hospital gets:

| Step | Output column | Rule |
|---|---|---|
| Availability flags | `C1` ... `Cn` | 1 if the measure is present, 0 if missing |
| Available-measure count | `TOTAL_CNT` | Number of present measures |
| Weight | `MEASURE_WT` | `1 / TOTAL_CNT`; missing when `TOTAL_CNT = 0` |
| Domain average | `SCORE_BEFORE_STD` | `SUM(measures) * MEASURE_WT`, matching SAS |
| Domain mean and std dev | `MEAN`, `STDDEV` | Across hospitals with a non-missing average; sample std dev (`ddof=1`) |
| Group score | `GRP_SCORE` | `(SCORE_BEFORE_STD - MEAN) / STDDEV` |

Hospitals with zero available measures stay in the output, with zero flags and count and
missing weight and scores (missing, not zero).

The five domains and their measures are defined in `DOMAIN_MEASURES`, following the
Program 1 analysis in [`program-1-analysis.md`](program-1-analysis.md):

| Domain artifact | Measures |
|---|---|
| `OUTCOME_MORTALITY` | 7 |
| `OUTCOME_SAFETY` | 8 |
| `OUTCOME_READMISSION` | 11 |
| `PTEXP` | 8 |
| `PROCESS` | 12 |

## Files

| File | Purpose |
|---|---|
| `reference_python/domain_scoring.py` | Standalone reference: measure lists, scoring, and a `main()` that writes the five CSVs |
| `tests/reference/test_domain_scoring.py` | Synthetic tests and real-data comparison tests |
| `configs/program1-comparison-policies.json` | Per-domain comparison policies used by the real-data tests |

`reference_python/mortality.py` and its controller are unchanged. Mortality is computed again
here as one of the five domains.

## Comparison results

Each generated artifact was compared with its trusted SAS binary in
`data/Project_1/SAS Output/` using `sasguard.verification.compare_artifacts`. Rows are aligned
by `PROVIDER_ID`. Each domain has its own policy in
`configs/program1-comparison-policies.json`, in the same per-artifact format as
`configs/program0-comparison-policies.json`. Every output column is listed:

| Columns | Rule |
|---|---|
| `C1` ... `Cn`, `TOTAL_CNT` | Exact |
| `STD_` measure columns, `MEASURE_WT`, `SCORE_BEFORE_STD`, `MEAN`, `STDDEV`, `GRP_SCORE` | Absolute and relative tolerances of `1e-12`, as in the Mortality policy |

Missing values must match exactly.

| Artifact | Rows (Python / SAS) | Columns | Missing `GRP_SCORE` | Schema | Providers | Missingness | Numeric |
|---|---|---|---|---|---|---|---|
| `OUTCOME_MORTALITY` | 4566 / 4566 | 21 | 884 | Match | Match | Match | Match |
| `OUTCOME_SAFETY` | 4566 / 4566 | 23 | 1176 | Match | Match | Match | Match |
| `OUTCOME_READMISSION` | 4566 / 4566 | 29 | 244 | Match | Match | Match | Match |
| `PTEXP` | 4566 / 4566 | 23 | 1387 | Match | Match | Match | Match |
| `PROCESS` | 4566 / 4566 | 31 | 22 | Match | Match | Match | Match |

The largest numeric differences observed were about `1e-15`, which is floating-point
roundoff and well within the `1e-12` tolerance.

These results apply to the supplied July 2025 cohort, this reference implementation, and the
committed policy. They do not show that every SAS behavior is reproduced, for example for
degenerate cohorts, which the reference rejects explicitly.

## Tests

`tests/reference/test_domain_scoring.py` contains:

| Test | Checks |
|---|---|
| `test_counts_weights_missing_and_scores` | Missing measures, row-specific weights, and a zero-measure hospital kept with missing scores |
| `test_sample_standard_deviation` | Sample std dev (`ddof=1`), not population |
| `test_does_not_change_input` | The input frame is not modified |
| `test_rejects_missing_column` | Missing measure columns raise an error |
| `test_rejects_duplicate_hospitals` | Duplicate provider IDs raise an error |
| `test_each_domain_has_a_measure_list` | All five domains exist with the expected measure counts |
| `test_all_five_domains_run` | Every domain scores a simple synthetic cohort |
| `test_policies_cover_every_domain_column` | Each domain policy lists every output column, with flags and counts exact |
| `test_domain_matches_trusted_sas_output` | Runs once per domain against the trusted SAS output |
| `test_comparison_catches_a_wrong_score` | A planted wrong score makes the comparison fail |

## Run it

From the repository root, with Docker Desktop running:

```bash
# Tests, including the five real-data comparisons
docker compose run --rm sasguard pytest tests/reference/test_domain_scoring.py -v

# Write the five domain CSVs
docker compose run --rm sasguard python reference_python/domain_scoring.py \
  --input "data/Project_1/SAS Output/std_data_2025jul_analysis.sas7bdat" \
  --output-dir reports/runs/program1
```

The CSVs are written to `reports/runs/program1/`, which is git-ignored. They are local run
outputs (not to be committed).
