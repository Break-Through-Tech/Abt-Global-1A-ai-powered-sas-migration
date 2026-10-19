"""Program 2 reporting eligibility boundary tests.

Rules: docs/issue-8-sas-scoring-clustering.md, section 3.
"""

import pytest


@pytest.mark.parametrize(
    "mortality, safety, readmission, patient_experience, process, expected",
[
    (3, 0, 3, 0, 0, False),  # Mortality + Readmission qualify; only 2 domains
    (3, 0, 3, 3, 0, True),   # Mortality + Readmission + Patient Experience qualify
    (0, 3, 3, 3, 0, True),   # Safety + Readmission + Patient Experience qualify
    (0, 0, 3, 3, 3, False),  # Readmission + Patient Experience + Process; no Mortality/Safety
    (3, 0, 3, 3, 3, True),   # Mortality + Readmission + Patient Experience + Process qualify
    (3, 3, 3, 3, 3, True),   # All 5 domains qualify
    (2, 0, 3, 3, 0, False),  # Readmission + Patient Experience; Mortality < 3
    (2, 3, 3, 3, 0, True),   # Safety + Readmission + Patient Experience; Mortality < 3
    (3, 0, 2, 3, 0, False),  # Mortality + Patient Experience qualify;  Readmission < 3
    (3, 0, 3, 4, 0, True),   # Mortality + Readmission + Patient Experience (4 measures) qualify
    (3, 3, 0, 0, 0, False),  # Mortality + Safety qualify; only 2 domains
    (3, 3, 3, 0, 0, True),   # Mortality + Safety + Readmission qualify
    (0, 0, 0, 0, 0, False),  # No domains qualify
]

)
def test_reporting_eligibility(
    mortality,
    safety,
    readmission,
    patient_experience,
    process,
    expected,
):
    measure_counts = {
        "mortality": mortality,
        "safety": safety,
        "readmission": readmission,
        "patient_experience": patient_experience,
        "process": process,
    }

    qualifying = {domain: count >= 3 for domain, count in measure_counts.items()}

    qualifying_count = sum(qualifying.values())

     # TODO: Replace reference logic with the Program 2 implementation when available.
    actual = qualifying_count >= 3 and (
        qualifying["mortality"] or qualifying["safety"]
    ) 
    assert actual == expected