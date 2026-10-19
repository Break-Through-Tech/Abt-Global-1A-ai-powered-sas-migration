"""Program 2 domain-weight redistribution tests.

Rules: docs/issue-8-sas-scoring-clustering.md.
"""

import pytest

BASE_WEIGHTS = {
    "patient_experience": 0.22,
    "readmission": 0.22,
    "mortality": 0.22,
    "safety": 0.22,
    "process": 0.12,
}


def reference_redistribute_weights(available_domains):
    """Redistribute CMS weights across domains with available scores."""
    total_weight = sum(BASE_WEIGHTS[domain] for domain in available_domains)

    return {domain: BASE_WEIGHTS[domain] / total_weight for domain in available_domains}


# Test 1: All five domains available
# Expected Behavior riginal weights remain unchanged
def test_all_domains_available():
    """Original weights remain unchanged when all domains are available."""
    available_domains = list(BASE_WEIGHTS.keys())

    actual = reference_redistribute_weights(available_domains)

    for domain, expected_weight in BASE_WEIGHTS.items():
        assert actual[domain] == pytest.approx(expected_weight)

    assert sum(actual.values()) == pytest.approx(1.0)


# Tests 2-6: Check which domain is missing individually.
# The 5 Domains: Patient Experience, readmission, mortality, Safety, Process
@pytest.mark.parametrize(
    "missing_domain",
    [
        "patient_experience",
        "readmission",
        "mortality",
        "safety",
        "process",
    ],
)

# Domain-weight redistribution when a domain is missing
def test_single_missing_domain(missing_domain):
    """Missing domains receive no weight; remaining weights redistribute."""
    available_domains = [domain for domain in BASE_WEIGHTS if domain != missing_domain]

    actual = reference_redistribute_weights(available_domains)

    # Check that the missing domain receives no weight.
    assert missing_domain not in actual

    # Check the correct redistribution denominator.
    if missing_domain == "process":
        expected_total = 0.88
    else:
        expected_total = 0.78

    # Check each available domain's redistributed weight.
    for domain in available_domains:
        expected_weight = BASE_WEIGHTS[domain] / expected_total
        assert actual[domain] == pytest.approx(expected_weight)

    # All redistributed weights must total 100%.
    assert sum(actual.values()) == pytest.approx(1.0)
