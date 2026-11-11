import pytest

# percentile boundry check
def assign_quintile(score, p20, p40, p60, p80):
    """Reference the interval rules in the SAS %kmeans macro."""
    if score is None:
        return None
    if score <= p20:
        return 1
    if score <= p40:
        return 2
    if score <= p60:
        return 3
    if score <= p80:
        return 4
    return 5

@pytest.mark.parametrize(
    "score, expected_group",
    [
        (10, 1),
        (20, 1),  # Exactly P20
        (30, 2),
        (40, 2),  # Exactly P40
        (60, 3),
        (80, 4),
        (90, 5),
    ],
)
def test_quintile_group_boundaries(score, expected_group):
    assert assign_quintile(score, p20=20, p40=40, p60=60, p80=80) == expected_group


# test the median initilization with how SAS chose 5 star median
from statistics import median


def calculate_group_medians(grouped_scores):
    """Calculate initial seeds from group medians."""
    return {group: median(scores) for group, scores in grouped_scores.items()}


def test_median_initilization():
    grouped_scores = {
        1: [10, 15, 20],
        2: [25, 30, 35],
        3: [40, 45, 50],
        4: [55, 60, 65],
        5: [70, 75, 80],
    }

    expected_seeds = {
        1: 15,
        2: 30,
        3: 45,
        4: 60,
        5: 75,
    }

    assert calculate_group_medians(grouped_scores) == expected_seeds


def test_median_initilization_even_count():
    grouped_scores = {
        1: [10, 20],
        2: [30, 40],
        3: [50, 60],
        4: [70, 80],
        5: [90, 100],
    }

    expected_seeds = {
        1: 15,
        2: 35,
        3: 55,
        4: 75,
        5: 95,
    }

    assert calculate_group_medians(grouped_scores) == expected_seeds


# ensure consistency
import re
from pathlib import Path

SAS_MACRO = (
    Path(__file__).resolve().parents[1] / "data" / "Project_1" / "SAS Programs" / "Star_Macros.sas"
)


def test_first_fastclus_pass_configuration():
    """Verify first-pass FASTCLUS settings in the SAS source."""
    source = SAS_MACRO.read_text(errors="replace")

    passes = re.findall(
        r"proc\s+fastclus\b([^;]*);",
        source,
        flags=re.IGNORECASE,
    )

    assert len(passes) == 2, "Expected two FASTCLUS passes"

    first_pass = passes[0].lower()

    assert re.search(r"\bmaxc\s*=\s*5\b", first_pass)
    assert re.search(r"\bconverge\s*=\s*0\b", first_pass)
    assert re.search(r"\bmaxiter\s*=\s*1000\b", first_pass)
    assert re.search(r"\bseed\s*=\s*s33\b", first_pass)
    assert not re.search(r"\bstrict\s*=", first_pass)


# second pass with Strict = 1
def test_second_fastclus_pass_configuration():
    """Verify second-pass FASTCLUS settings in the SAS source."""
    source = SAS_MACRO.read_text(errors="replace")

    passes = re.findall(
        r"proc\s+fastclus\b([^;]*);",
        source,
        flags=re.IGNORECASE,
    )

    assert len(passes) == 2, "Expected two FASTCLUS passes"

    second_pass = passes[1].lower()

    assert re.search(r"\bmaxc\s*=\s*5\b", second_pass)
    assert re.search(r"\bconverge\s*=\s*0\b", second_pass)
    assert re.search(r"\bmaxiter\s*=\s*1000\b", second_pass)
    assert re.search(r"\bseed\s*=\s*seeds2\b", second_pass)
    assert re.search(r"\bstrict\s*=\s*1\b", second_pass)
    assert re.search(r"\bout\s*=\s*clusters\b", second_pass)


def test_second_pass_uses_first_pass_centers():
    """Verify the first pass exports seeds used by the second."""
    source = SAS_MACRO.read_text(errors="replace").lower()

    assert re.search(
        r"ods\s+output\s+clustercenters\s*=\s*seeds2\s*;",
        source,
    )

    assert re.search(
        r"seed\s*=\s*seeds2\b",
        source,
    )

    assert re.search(
        r"ods\s+output\s+clustercenters\s*=\s*cluster_mean\s*;",
        source,
    )


# Cluster ordering and star mapping reference probes


def assign_stars_by_cluster_mean(cluster_means):
    """Assign stars by ascending cluster-center score."""
    sorted_clusters = sorted(
        cluster_means,
        key=cluster_means.get,
    )

    return {cluster_id: star for star, cluster_id in enumerate(sorted_clusters, start=1)}


# cluster ordering and star mapping
def test_cluster_ordering_and_star_mapping():
    cluster_means = {
        1: 0.8,
        2: -0.5,
        3: 0.2,
        4: 1.4,
        5: -1.1,
    }

    expected_stars = {
        5: 1,
        2: 2,
        3: 3,
        1: 4,
        4: 5,
    }

    assert assign_stars_by_cluster_mean(cluster_means) == expected_stars


def test_star_mapping_independent_of_cluster_id():
    cluster_means = {
        5: 0.1,
        3: 0.3,
        1: 0.5,
        4: 0.7,
        2: 0.9,
    }

    expected_stars = {
        5: 1,
        3: 2,
        1: 3,
        4: 4,
        2: 5,
    }

    assert assign_stars_by_cluster_mean(cluster_means) == expected_stars


# check the outlier investigation

# Outlier investigation: synthetic reference probes

from statistics import mean


def test_outlier_effect_on_mean():
    """Show how an extreme value can shift a mean."""
    normal_scores = [0.10, 0.15, 0.20, 0.25, 0.30]
    with_outlier = normal_scores + [5.00]

    assert mean(with_outlier) > mean(normal_scores)


def test_outlier_effect_on_median():
    """Compare the median's response to an extreme value."""
    normal_scores = [0.10, 0.15, 0.20, 0.25, 0.30]
    with_outlier = normal_scores + [5.00]

    mean_shift = abs(mean(with_outlier) - mean(normal_scores))
    median_shift = abs(median(with_outlier) - median(normal_scores))
    assert median_shift < mean_shift