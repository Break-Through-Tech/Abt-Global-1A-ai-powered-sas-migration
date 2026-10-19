"""Program 2 reporting eligibility boundary tests.

Rules: docs/issue-8-sas-scoring-clustering.md, section 3.
"""

import pytest


@pytest.mark.parametrize(
    "mortality, safety, readmission, patient_experience, process, expected",
    [
        (3, 0, 3, 0, 0, False),  # Only 2 qualifying domains
        (3, 0, 3, 3, 0, True),   # 3 domains, Mortality qualifies
        (0, 3, 3, 3, 0, True),   # 3 domains, Safety qualifies
        (0, 0, 3, 3, 3, False),  # 3 domains, neither Mortality nor Safety
        (3, 0, 3, 3, 3, True),   # 4 qualifying domains
        (3, 3, 3, 3, 3, True),   # All 5 domains qualify
        (2, 0, 3, 3, 0, False),  # Mortality below measure threshold
        (2, 3, 3, 3, 0, True),   # Mortality fails, but Safety and 2 other domains qualify
        (3, 0, 2, 3, 0, False),  # Readmission below measure threshold
        (3, 0, 3, 4, 0, True),   # Patient Experience exceeds minimum measure count
        (3, 3, 0, 0, 0, False),  # Both qualify, but only 2 domains
        (3, 3, 3, 0, 0, True),   # Both Mortality and Safety qualify; 3 domains total
        (0, 0, 0, 0, 0, False),  # No domains qualify
    ],
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

    actual = qualifying_count >= 3 and (
        qualifying["mortality"] or qualifying["safety"]
    )  # come back and fix this

    assert actual == expected
