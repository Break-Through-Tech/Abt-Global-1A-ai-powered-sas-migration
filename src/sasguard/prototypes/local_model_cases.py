"""Synthetic evaluation fixtures with handwritten, documentation-based expectations."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SyntheticCase:
    """One frozen source, runtime contract, input, and host-only expected result."""

    name: str
    prompt_version: str
    sas_source: str
    input_csv: str
    expected_csv: str
    prompt: str
    key: str = "PROVIDER_ID"


_DOUBLE_SOURCE = """data adjusted;
    set scores;
    if missing(SCORE) then ADJUSTED = .;
    else ADJUSTED = SCORE * 2;
run;
"""
_SCORE_INPUT = """PROVIDER_ID,SCORE
000001,2.5
000002,
000003,-3
NA,0
NULL,0.25
000006,-0.125
000007,10
"""
_DOUBLE_EXPECTED = """PROVIDER_ID,SCORE,ADJUSTED
000001,2.5,5
000002,,
000003,-3,-6
NA,0,0
NULL,0.25,0.5
000006,-0.125,-0.25
000007,10,20
"""
# Preserve the original v1 prompt byte-for-byte for the updated-runtime comparison.
_DOUBLE_PROMPT = f"""Translate this synthetic DATA step using pandas:

{_DOUBLE_SOURCE}
Runtime contract:
- Read input.csv from the directory in the SASGUARD_INPUT_DIR environment variable.
- Write adjusted.csv into the directory in SASGUARD_OUTPUT_DIR.
- Input columns are PROVIDER_ID and SCORE. SCORE is numeric; an empty field is missing.
- PROVIDER_ID is text. Preserve leading zeros and the literal identifiers NA and NULL.
- Output columns must be exactly PROVIDER_ID, SCORE, ADJUSTED. Preserve every input row.
- Represent missing numeric output values as empty CSV fields. Do not write a CSV index.
- Do not invent input filenames, embed data, or access any other files or the network.
Return a JSON object with exactly one property named code containing executable Python.
"""


def _prompt(source: str, schema: str, columns: str, rows: str) -> str:
    return f"""Translate this synthetic SAS using pandas:

{source}
Runtime contract:
- Read input.csv from the directory in the SASGUARD_INPUT_DIR environment variable.
- Write adjusted.csv into the directory in SASGUARD_OUTPUT_DIR.
- {schema}
- Output columns must be exactly {columns}. {rows}
- Represent missing numeric output values as empty CSV fields. Do not write a CSV index.
- Do not invent input filenames, embed data, or access any other files or the network.
Return a JSON object with exactly one property named code containing executable Python.
"""


_MISSING_SOURCE = """data adjusted;
    set scores;
    if SCORE < 0 then FLAG = 1;
    else FLAG = 0;
run;
"""
_SUM_SOURCE = """data adjusted;
    set scores;
    ARITH_SUM = SCORE + OTHER;
    FUNC_SUM = sum(SCORE, OTHER);
run;
"""
_GROUP_SOURCE = """proc means data=scores nway noprint;
    class GROUP;
    var SCORE;
    output out=adjusted(drop=_TYPE_ _FREQ_) n=COUNT mean=MEAN;
run;
"""
_IDENTIFIER_CONTRACT = (
    "PROVIDER_ID is text. Preserve leading zeros and the literal identifiers NA and NULL. "
    "Numeric columns use an empty field for missing values."
)

CASES = {
    "double-score": SyntheticCase(
        name="double-score",
        prompt_version="synthetic-double-score-v1",
        sas_source=_DOUBLE_SOURCE,
        input_csv=_SCORE_INPUT,
        expected_csv=_DOUBLE_EXPECTED,
        prompt=_DOUBLE_PROMPT,
    ),
    "missing-comparison": SyntheticCase(
        name="missing-comparison",
        prompt_version="synthetic-missing-comparison-v1",
        sas_source=_MISSING_SOURCE,
        input_csv=_SCORE_INPUT,
        expected_csv="""PROVIDER_ID,SCORE,FLAG
000001,2.5,0
000002,,1
000003,-3,1
NA,0,0
NULL,0.25,0
000006,-0.125,1
000007,10,0
""",
        prompt=_prompt(
            _MISSING_SOURCE,
            "Input columns are PROVIDER_ID and numeric SCORE. " + _IDENTIFIER_CONTRACT,
            "PROVIDER_ID, SCORE, FLAG",
            "Preserve every input row.",
        ),
    ),
    "sum-missing": SyntheticCase(
        name="sum-missing",
        prompt_version="synthetic-sum-missing-v1",
        sas_source=_SUM_SOURCE,
        input_csv="""PROVIDER_ID,SCORE,OTHER
000001,2,3
000002,,3
000003,-2,
NA,,
NULL,0,0
000006,,0
""",
        expected_csv="""PROVIDER_ID,SCORE,OTHER,ARITH_SUM,FUNC_SUM
000001,2,3,5,5
000002,,3,,3
000003,-2,,,-2
NA,,,,
NULL,0,0,0,0
000006,,0,,0
""",
        prompt=_prompt(
            _SUM_SOURCE,
            "Input columns are PROVIDER_ID, numeric SCORE, and numeric OTHER. "
            + _IDENTIFIER_CONTRACT,
            "PROVIDER_ID, SCORE, OTHER, ARITH_SUM, FUNC_SUM",
            "Preserve every input row.",
        ),
    ),
    "grouped-mean": SyntheticCase(
        name="grouped-mean",
        prompt_version="synthetic-grouped-mean-v1",
        sas_source=_GROUP_SOURCE,
        input_csv="""GROUP,SCORE
A,1
A,
A,3
B,-2
B,2
C,
C,
""",
        expected_csv="""GROUP,COUNT,MEAN
A,2,2
B,2,0
C,0,
""",
        prompt=_prompt(
            _GROUP_SOURCE,
            "Input columns are textual GROUP and numeric SCORE. "
            "GROUP is never missing; empty SCORE fields are missing numeric values.",
            "GROUP, COUNT, MEAN",
            "Produce one row per GROUP as specified by the SAS.",
        ),
        key="GROUP",
    ),
}
