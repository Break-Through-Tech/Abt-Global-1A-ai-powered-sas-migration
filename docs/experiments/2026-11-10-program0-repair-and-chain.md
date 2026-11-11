# Program 0 automatic repair and Program 1 handoff

## Fresh automatic repair experiment

Ran `model-program0` with `gpt-6-luna`, medium reasoning, at most 8,192 output tokens per
request, and one permitted repair. The prompt used Program 0 SAS, its macro dependency,
input column names, and the runtime contract. It excluded input rows, trusted output
values, human-reference Python, and helper implementations.

| Attempt | Feedback | Docker execution | SAS validation |
|---|---|---|---|
| 0 | Direct translation | Succeeded | Malformed statistics output |
| 1 | Automatic aggregate diagnostics | Succeeded | Malformed statistics output |

Both candidates omitted the required `_STAT_` column from
`measure_average_stddev_2025jul.csv`. They represented statistics as suffixed columns
instead of the SAS table's statistic rows. The validator rejected the output structure;
neither attempt established Program 0 parity. A failed internal handoff report was saved.

Attempt 0 used 8,055 input and 3,547 output tokens. Attempt 1 used 9,696 input and 3,730
output tokens. Usage includes the provider's cache and reasoning details in the local
attempt records. No further generation requests were made in this experiment.

The automatic feedback named the failing file and the `malformed_outputs` status, but
did not identify the missing `_STAT_` column or describe the expected schema. The next
repair improvement should expose deterministic structural diagnostics without sending
reference rows or raw exception text. This run does not prove that richer feedback will
produce a passing repair; that requires a separate experiment.

## Separate passing chain

To test integration independently, used the earlier passing Luna candidate from the
repair experiment that included human-curated diagnostics and explicit code hints.
Its Python-generated Program 0 output had been rerun unchanged in Docker and validated
against all three supplied SAS artifacts.

Fed that candidate's `std_data_2025jul_analysis.csv` into the merged human-written
Program 1 reference in isolated Docker. The supplied SAS intermediate was not used as
Program 1's input.

| Domain | Provider rows | SAS comparison | Exact preservation of Python input measures |
|---|---|---|---|
| OUTCOME_MORTALITY | 4,566 | Passed | Passed |
| OUTCOME_SAFETY | 4,566 | Passed | Passed |
| OUTCOME_READMISSION | 4,566 | Passed | Passed |
| PTEXP | 4,566 | Passed | Passed |
| PROCESS | 4,566 | Passed | Passed |

This establishes the bounded handoff from the earlier human-guided model candidate to
the human Program 1 reference on July 2025 data. It does not turn the fresh automatic
repair failure into a success, establish a model-generated Program 1 translation, or
verify Program 2 and final CMS ratings.

Local records retain the full prompts, responses, source, hashes, execution evidence,
and comparisons. Generated artifacts and credentials are excluded from Git.
