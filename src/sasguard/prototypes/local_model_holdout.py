"""Separate, not-yet-model-evaluated cases frozen after the helper development runs."""

from sasguard.prototypes.local_model_cases import SyntheticCase


def _prompt(source: str, schema: str, columns: str, rows: str = "Preserve every input row.") -> str:
    return f"""Translate this synthetic SAS using pandas:

{source}
Runtime contract:
- Read input.csv from the directory in SASGUARD_INPUT_DIR.
- Write adjusted.csv into the directory in SASGUARD_OUTPUT_DIR.
- {schema}
- Empty numeric input fields are missing. Keep missing numeric outputs as empty fields.
- Output columns must be exactly {columns}. {rows}
- Numeric results and flags must be numeric, not text or Boolean values.
- Do not write a CSV index, embed data, or access other files or the network.
Return a JSON object with exactly one property named code containing executable Python.
"""


_KEY = "PROVIDER_ID is text; preserve leading zeros and literal NA and NULL identifiers."
_THRESHOLD = """data adjusted;
    set scores;
    if SCORE < 5 then FLAG = 1;
    else FLAG = 0;
run;
"""
_SUM = """data adjusted;
    set scores;
    ARITH_TOTAL = A + B + C;
    FUNC_TOTAL = sum(A, B, C);
run;
"""
_GROUP = """proc means data=scores nway noprint;
    class GROUP;
    var SCORE;
    output out=adjusted(drop=_TYPE_ _FREQ_) n=COUNT mean=MEAN;
run;
"""
_AFFINE = """data adjusted;
    set scores;
    if missing(SCORE) then ADJUSTED = .;
    else ADJUSTED = SCORE * 1.5 - 2;
run;
"""

HOLDOUT_CASES = {
    "holdout-threshold": SyntheticCase(
        name="holdout-threshold",
        prompt_version="holdout-threshold-v1",
        sas_source=_THRESHOLD,
        input_csv="PROVIDER_ID,SCORE\n001024,\nNA,5\nNULL,4.75\n000078,5.25\n000079,-8\n",
        expected_csv=(
            "PROVIDER_ID,SCORE,FLAG\n001024,,1\nNA,5,0\nNULL,4.75,1\n000078,5.25,0\n000079,-8,1\n"
        ),
        prompt=_prompt(
            _THRESHOLD,
            "Input columns are PROVIDER_ID and numeric SCORE. " + _KEY,
            "PROVIDER_ID, SCORE, FLAG",
        ),
    ),
    "holdout-sum-three": SyntheticCase(
        name="holdout-sum-three",
        prompt_version="holdout-sum-three-v1",
        sas_source=_SUM,
        input_csv=(
            "PROVIDER_ID,A,B,C\n000101,,,\nNA,,0,\nNULL,-2,,3\n"
            "000104,1,2,3\n000105,0,0,0\n000106,0.25,-0.5,0.25\n"
        ),
        expected_csv=(
            "PROVIDER_ID,A,B,C,ARITH_TOTAL,FUNC_TOTAL\n000101,,,,,\nNA,,0,,,0\n"
            "NULL,-2,,3,,1\n000104,1,2,3,6,6\n000105,0,0,0,0,0\n"
            "000106,0.25,-0.5,0.25,0,0\n"
        ),
        prompt=_prompt(
            _SUM,
            "Input columns are PROVIDER_ID and numeric A, B, C. " + _KEY,
            "PROVIDER_ID, A, B, C, ARITH_TOTAL, FUNC_TOTAL",
        ),
    ),
    "holdout-grouped-keys": SyntheticCase(
        name="holdout-grouped-keys",
        prompt_version="holdout-grouped-keys-v1",
        sas_source=_GROUP,
        input_csv=(
            "GROUP,SCORE\n0001,2\n0001,\n0001,4\n0001,\n0001,12\n"
            "NA,\nNA,\nNULL,0\nNULL,-10\n0002,\n0002,6\n"
        ),
        expected_csv="GROUP,COUNT,MEAN\n0001,3,6\nNA,0,\nNULL,2,-5\n0002,1,6\n",
        prompt=_prompt(
            _GROUP,
            "Input columns are text GROUP and numeric SCORE. GROUP is never missing; "
            "preserve leading zeros and literal NA and NULL group labels.",
            "GROUP, COUNT, MEAN",
            "Produce one row per GROUP as specified by the SAS.",
        ),
        key="GROUP",
    ),
    "holdout-affine": SyntheticCase(
        name="holdout-affine",
        prompt_version="holdout-affine-v1",
        sas_source=_AFFINE,
        input_csv="PROVIDER_ID,SCORE\n000031,-4\nNA,\nNULL,0\n000034,0.5\n000035,3\n",
        expected_csv=(
            "PROVIDER_ID,SCORE,ADJUSTED\n000031,-4,-8\nNA,,\nNULL,0,-2\n"
            "000034,0.5,-1.25\n000035,3,2.5\n"
        ),
        prompt=_prompt(
            _AFFINE,
            "Input columns are PROVIDER_ID and numeric SCORE. " + _KEY,
            "PROVIDER_ID, SCORE, ADJUSTED",
        ),
    ),
}
