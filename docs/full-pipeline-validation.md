# Full-pipeline validation

`sasguard validate-pipeline` checks that Program 0, Program 1 and Program 2 outputs work as
one chain and match the supplied SAS artifacts. It validates actual Python output files on
the host, records where each stage came from, and reports `PASS` only when all ten declared
artifacts match. It never runs candidate code and never gives trusted outputs to a candidate.

## Command

Use the project Python environment from [Development setup](development-setup.md).

```text
sasguard validate-pipeline --run-human-references \
  --program2-output PROGRAM2_OUTPUT_DIR --program2-source helper_assisted_model_output
```

To run all three stages locally with no supplied outputs, use the Program 2 reference
implementation (see [the labeling caveat](#program-2-reference-implementation)):

```text
sasguard validate-pipeline --run-human-references --run-reference-program2
```

The command is the same in PowerShell and zsh apart from line continuation. Other
combinations:

| Stages | Options |
|---|---|
| Program 0 and Program 1 from the human references | `--run-human-references` |
| Program 2 reference run on the Program 0 and 1 outputs | `--run-reference-program2` (with `--run-human-references`, or with supplied Program 0 and 1 outputs) |
| Supplied Program 0, human Program 1 run on it | `--program0-output DIR --program0-source SOURCE --run-human-program1` |
| All three stages supplied | `--program0-output`, `--program0-source`, `--program1-output`, `--program1-source`, `--program2-output`, `--program2-source` |

`SOURCE` is one of `human_reference`, `direct_model_output`,
`helper_assisted_model_output`, or `manually_corrected_model_output`. The source is always
explicit and is stored as one flag per origin. Optional `--programN-code FILE` records the
hash of a candidate file, and `--program2-note` records free text.
Supplied directories hold CSVs named like the SAS artifacts
(`less100_measure.csv`, `outcome_mortality.csv`, `star_2025jul.csv`, and so on). Program 1
file names are matched ignoring case. No team-member-written Program 2 exists in this
repository. Program 2 output comes either from the reference implementation below or from a
model candidate run (for example `model-program2` or the
[STRICT replay](experiments/2026-11-16-program2-strict-replay.md)).

The record is written to a new `reports/runs/pipeline-*` directory as
`pipeline-validation.json` and `summary.md`. The exit code is 0 only for `PASS`.

## Program 2 reference implementation

`reference_python/program2.py` implements Program 2 (weights and summary score, `%report`
counts and eligibility, `%kmeans`, national averages). It reads only the Program 1 CSVs and
Program 0's `std_data_2025jul_analysis.csv`, never trusted SAS outputs, and reuses the
FASTCLUS helpers in `src/sasguard/semantics`. Those helpers raise
`UnresolvedSASBehavior` on exact ties, empty clusters and MAXITER instead of picking a rule.

**Labeling caveat.** This file was not written by a team member and is pending teammate
review. With `--run-reference-program2` the stage is therefore recorded as
`helper_assisted_model_output` (the FASTCLUS helpers are used) with the note "Program 2
reference implementation pending teammate review", and the file's hash is recorded in
`source_hashes`. The origin is fixed: `--program2-source` is rejected with this flag, so the
same bundled code can never be relabelled `human_reference`. After a teammate reviews the
file, record that with `--program2-reviewed-by "<name>"`. The review is stored in the stage's
`reviewed_by` field and shown in the reports; the origin stays
`helper_assisted_model_output`. A `PASS` is therefore not a "human Program 2" result.

`report-run` only labels a run `VERIFIED` when every stage's recorded outputs are present
in the run directory and re-hash to the recorded values. A missing or partly re-checked
stage folder makes the report `NOT VERIFIED` and withholds hospital totals. The CMS summary
never names a provider and shows a column only if it is in the SAS reference schema; the
first differing key and any unexpected header stay in the technical record.

With `--run-reference-program2` the record always hashes the bundled
`reference_python/program2.py`, the code that ran; `--program2-code` is rejected.

## What is checked

| Stage | Artifacts | Validator |
|---|---|---|
| Program 0 | `LESS100_MEASURE`, `MEASURE_AVERAGE_STDDEV_2025JUL`, `STD_DATA_2025JUL_ANALYSIS` | `verification/program0.py` |
| Program 1 | `OUTCOME_MORTALITY`, `OUTCOME_SAFETY`, `OUTCOME_READMISSION`, `PTEXP`, `PROCESS` | `verification/program1.py` |
| Program 2 | `STAR_2025JUL`, `NATIONAL_AVERAGE_2025JUL` | `verification/program2.py` |

Each artifact is compared with its supplied SAS binary under a fixed policy in
`configs/program0-comparison-policies.json`, `configs/program1-comparison-policies.json` or
`configs/program2-comparison-policies.json`. The comparator checks column names, key sets
(so hospital IDs and row counts), missingness, exact cells (flags, counts, eligibility,
peer groups, stars) and calculated values at an absolute and relative tolerance of
`1e-12`. Provider IDs are text, so leading zeros matter, and rows are aligned by
`PROVIDER_ID` (Program 0 statistics by `_STAT_`, national averages by their single row).
Before any comparison, every tolerance in all three policy files is audited: any nonzero
tolerance other than exactly `1e-12` absolute and relative fails the run.

Handoffs are checked exactly, with no tolerance:

* Program 1's copied `STD_` measures must equal the actual Program 0
  `std_data_2025jul_analysis.csv`.
* Program 2's copied domain scores must equal the actual Program 1 `GRP_SCORE` values.

These checks catch a stage that did not consume the real upstream output, even when its
values are within the SAS tolerance. The 29 protected files are verified before and after
the run, and the count is recorded.

## Result and status

| Status | Meaning |
|---|---|
| `PASS` | All ten artifact comparisons, both handoffs, the policy audit and both integrity checks passed. |
| `PARTIAL` | At least one but not all ten comparisons passed, or a handoff failed. Never treated as parity. |
| `FAIL` | No comparison passed, or integrity or the policy audit failed. |

`summary.md` says "Full-pipeline parity: NOT established" for anything but `PASS`, and a
`PASS` is scoped to the supplied July 2025 SAS artifacts. Human review and client approval
are not recorded by this command.

The record lists per-stage source flags, statuses, artifact comparisons, handoff
comparisons, STAR mismatch count, integrity results, and these hashes: source (human
reference files or candidate file), inputs (the supplied hospital file, and the actual
upstream files each stage consumed), policies, the ten SAS reference files, environment
(Python, OS, package versions, git commit) and every output file.

### Earliest divergence

Stages are examined in order. The first failing stage supplies the earliest divergence:
stage, artifact, kind (`missing_output`, `malformed_output`, `schema`, `keys`, `value`,
`handoff`), the first differing column, and the first differing key in SAS row order.
Later stages that fail after an earlier failure are marked `upstream_failure`; their own
result is kept in `own_status`. For example, a wrong Program 0 value that flows into
Program 1 is reported at Program 0, and Program 1 is `upstream_failure`, not a Program 1
bug. A Program 1 that did not consume the real Program 0 output, with Program 0 correct,
is `handoff_failed` and is reported as Program 1's own failure.

## Synthetic tests

`tests/verification/test_pipeline.py` and `tests/verification/test_program1.py` cover:
a wrong but executable value in each program, a Program 0 corruption that flows into
Program 1 and Program 2 (upstream failure), a Program 1 that skipped the real Program 0
output (own handoff failure), changes below the tolerance that still fail the exact copy
check, missing and malformed files for each program, dropped keys and leading-zero IDs,
the status rules, tolerance auditing, and the command's exit code. The `PASS` path is
tested with a Program 2 control built on the test host from SAS values and the actual
Program 1 scores. That control proves only the validator, not any Program 2 translation.

## Recording an independent replay

An independent replay records, in the issue or review note:

| Field | Value |
|---|---|
| OS | from `environment.operating_system` in `pipeline-validation.json` |
| Commit | `environment.git_commit` |
| Runner image ID | `sha256:...` from the Docker run that produced candidate output |
| Candidate hashes | `source_hashes` per stage, and the recorded expected hashes |
| Passed by program | `passed_by_program` (Program 0 of 3, Program 1 of 5, Program 2 of 2) |
| STAR mismatches | `star_mismatches` |
| Integrity | `integrity_before` and `integrity_after` (29/29 files) |
| Status | `PASS`, `PARTIAL` or `FAIL` |

Row-level files and raw run records stay local. The Docker integration tests need a current
runner image: rebuild it with `docker build --file Dockerfile.runner --tag sasguard-runner:test .`
after pulling source changes, because an older image can lack current helpers.

## Recorded result and what remains

On the human references, `--run-human-references` produced Program 0 and Program 1 output
on the supplied July 2025 input. Program 0 passed 3/3 and Program 1 passed 5/5, with the
Program 1 handoff exact and 29/29 protected files verified before and after. Without a
Program 2 output the status is `PARTIAL` (8 of 10), earliest divergence Program 2
`STAR_2025JUL`, missing output. The command refuses `--run-human-references` alone (exit 2,
a Program 2 source is required), so reproduce this result by passing an empty directory with
`--program2-output` and a `--program2-source` flag, as in the [demo runbook](demo-runbook.md).

With `--run-reference-program2` the full local chain reached `PASS`, 10 of 10: Program 0
3/3, Program 1 5/5, Program 2 2/2 (source `helper_assisted_model_output`), both handoffs
exact, 0 STAR mismatches, 29/29 protected files before and after. No
`UnresolvedSASBehavior` occurred on the real data (no exact ties, empty clusters or
MAXITER stops), and no tolerance, policy or data file was changed. The largest numeric
difference on Program 2 was about 1.8e-13. This is one July 2025 result against the
supplied SAS artifacts. It is consistent with the STRICT behavior in
[fastclus-iteration](fastclus-iteration.md), not a confirmation from SAS itself.

Remaining work:

* Teammate review of `reference_python/program2.py`, after which `human_reference` may be
  used.
* An independent replay of this command on a clean checkout and runner image.
* Chained runs of the Program 0 and Program 2 model candidates from #68 and #70 (direct
  and helper-assisted), recorded with the correct source flag.
* A prospective Program 2 result without manual correction, and other CMS releases.
* Abt review and approval before any result is shared with CMS.
