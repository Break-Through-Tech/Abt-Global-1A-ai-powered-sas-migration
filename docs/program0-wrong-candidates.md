# Program 0 wrong-candidate tests (#45)

These tests run Program 0 with deliberate, realistic mistakes. Each candidate
executes without error, and the validator must still reject it. The tests only
change in-memory copies of the input; supplied SAS files, reference outputs, and
comparison policy are never modified (checked by the protected-artifact fixture).

Command:

    docker compose run --rm sasguard pytest tests/integration/test_program0_wrong_candidates.py -v

Outcome: 3 passed.

| Mistake | Validator result |
|---|---|
| Direction reversal skipped | `failed`; mismatch in `STD_*` columns of `std_data_2025jul_analysis.csv` |
| Missing values changed to zero | `failed`; `std_data_2025jul_analysis.csv` does not match |
| Leading-zero provider IDs lost | `malformed_outputs`; error on `std_data_2025jul_analysis.csv` |

Population vs sample standard deviation is covered by the Mortality test in PR #40
and is not repeated here.