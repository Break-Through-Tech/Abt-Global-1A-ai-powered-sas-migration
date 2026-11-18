# Numeric output reassessment, October 20, 2026

The stricter policy rejects the Qwen3 4B Boolean flag output. Its helper v2 score drops from
two of four to one of four. Qwen3.5 9B stays at three of four. No new generations or candidate
executions were performed for this reassessment. Original reports and candidates remain intact.

| Model | Original helper v2 policy | Explicit numeric policy |
|---|---:|---:|
| `qwen3:4b` | 2 of 4 | 1 of 4 |
| `qwen3.5:9b-q4_K_M` | 3 of 4 | 3 of 4 |

All four retained, valid suites were reassessed, 32 attempts in total. The original October 18
baseline and the October 19 direct control both remain 0/4 for 4B and 1/4 for 9B. Helper v1
changes from 2/4 to 1/4 for 4B and stays at 0/4 for 9B. The invalid old-image pilot was not
used to score either policy. See [the original helper results](local-model-helper-comparison.md)
for that environment failure and the helper path-interface fix.

## What changed

`synthetic-numeric-v2` declares every non-key output column as numeric. The existing shared
comparator already rejects Boolean and nonnumeric dtypes when it receives an explicit numeric
rule. We did not change the comparator's default behavior or relax any tolerance. Keys remain
textual, numeric comparisons are exact, and missingness stays strict.
This checks loaded numeric dtypes, not raw CSV quoting or every SAS datatype constraint.

The old policy inferred how to compare columns. For the 4B flag output, inference selected
exact equality, where Python treats Boolean flags as equal to numeric 0/1. The new numeric
rule rejects that output before cell comparison. A failed dtype check is a validation failure,
not a generation or execution failure.

The reassessment verifies every saved artifact hash before comparison. It records the source
suite and report hashes, original outcomes, new outcomes, and new policy files in a separate
directory. Changed or missing files fail rather than silently becoming a new baseline.
Original generation or execution failures remain unpassed and are not rerun. Human review
remains `not_recorded`. Hashes detect changes relative to the saved records; they are not
signed attestations of their origin.

## Local audit records

The reassessment directories below are under ignored `reports/runs/`. Each contains
`report.json` and the policies used for successfully executed candidates.

| Source suite | Reassessment directory |
|---|---|
| October 18 direct baseline | `local-model-reassessment-90a587fa-6a41-49b1-a32b-dbb7f8f3c7ca` |
| October 19 direct control | `local-model-reassessment-e00ac615-3680-4b55-ba10-be3f3cf53314` |
| Helper v1 | `local-model-reassessment-ce376458-d63b-451c-b5aa-49971575855a` |
| Helper v2 | `local-model-reassessment-74e15f82-564b-4826-8d31-d9e9c6f2c1bc` |

The original candidate, input, expected-result, and policy hashes stay in the source reports.
The reassessment copies their hash mappings and records links instead of replacing them.

## Prospective cases

The separate `holdout-v1` set has four new cases and no model scores yet. It checks a nonzero
threshold, three-argument SUM with missing values and zero, grouped nonmissing counts with
leading-zero and literal NA/NULL keys, and affine arithmetic with missing values.
Independent scalar Python tests cross-check the handwritten expected results. This is not
SAS-runtime validation. The cases were designed after the development experiments, so they
should not be described as a blind benchmark.

The frozen fixture file SHA-256 is
`184bc8a8fec0eda07386ef383da7f75ecfd16ba1ddff86812102afca17918394`.

The numeric policy applies to both sets going forward. New reports identify the set and
policy version. Freeze and review the prospective cases before their first model run, keep
all failures, and do not combine their scores with the original four development cases.
Commands are in [Test a local model](local-model-smoke.md#numeric-policy-and-separate-case-set-october-20).
