# Program 0 automatic repair with structural feedback

## Change under test

The previous automatic repair run failed because its feedback named a malformed file
without identifying the missing `_STAT_` key. Its malformed-file outcome also discarded
the validator's partial comparisons, hiding precision failures in another output.

Added `program0-aggregate-v2` feedback. The host reads expected schemas and row counts
from SAS metadata, reports missing keys and columns, and supplies the fixed comparison
policies. Independent diagnostic comparisons use the existing comparator to expose
other artifact failures. They do not replace the validator's outcome or change any
tolerance. Candidate column names outside the trusted schema are counted without
being transmitted.

## Fresh model experiment

Ran `gpt-6-luna` with medium reasoning, at most 8,192 output tokens per request, and
two permitted automatic repairs. The direct prompt contained the same source/header
payload as the previous experiment. No human-reference Python, input rows, reference
output values, or compatibility helper implementation entered the prompt.

| Attempt | Docker execution | SAS validation | Result |
|---|---|---|---|
| 0 | Succeeded | Malformed outputs | Statistics table did not have the required structure |
| 1 | Succeeded | Failed | Structure and standardized data passed; 15 statistics cells still mismatched |
| 2 | Succeeded | Passed | All three Program 0 artifacts passed |

The model received only automatically constructed diagnostics between attempts.
No candidate was edited manually, and no run-specific code hints were added.
All failed attempts, responses, requests, and diagnostics remain saved alongside the
successful attempt. The previous failed experiment's 11 files remain byte-for-byte
unchanged.

| Final Program 0 artifact | Rows | Comparison |
|---|---|---|
| LESS100_MEASURE | 0 | Passed |
| MEASURE_AVERAGE_STDDEV_2025JUL | 5 | Passed |
| STD_DATA_2025JUL_ANALYSIS | 4,566 | Passed |

All final comparisons have zero mismatched cells and zero missingness mismatches under
the existing policies. Statistics N, MIN, and MAX retain their exact comparisons.
Calculated numeric fields retain their committed tolerances. The report reader confirms
the request, response, candidate, execution, policy, and source evidence before marking
the scoped Program 0 report VERIFIED and recording two repairs.

The three requests used 45,899 input and 9,177 output tokens in total. Provider cache
and reasoning-token details are retained in the local attempt records. No price is
inferred from those totals in the workflow report.

## Downstream check

Fed the newly passing model candidate's Python-generated intermediate into the
human-written Program 1 reference in Docker. All five domain outputs passed against
their supplied SAS binary references for 4,566 hospitals. Each output also passed the
exact check of standardized measures copied from the Python input.

This chain uses the new automatically repaired Program 0 candidate. It does not rely
on the earlier candidate repaired with human-written hints. Program 1 remains a
human-written reference, and no supplied SAS intermediate is substituted at the handoff.

## Limits

This is one recorded experiment on the supplied July 2025 release. It does not measure
the probability of success across repeated generations or establish correctness on
different inputs. Program 2, eligibility, clustering, and final CMS ratings remain
unverified. Human review and approval for a client release are not recorded.

The implementation changes no comparison policies, validator acceptance rules, or
protected artifacts. All 29 protected files passed integrity verification. Local run
artifacts and credentials are excluded from Git.
