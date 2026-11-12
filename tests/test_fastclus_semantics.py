"""Synthetic counterexamples for documented rules, not SAS execution results."""

import math

import pytest

from sasguard.semantics.fastclus import (
    percentile_definition5,
    quintile_medians,
    star_for_cluster,
    stars_by_cluster_center,
    strict_cluster_identifier,
)


@pytest.mark.parametrize(
    "values,percent,expected",
    [
        ([10, 20, 30, 40], 20, 10),  # Definition 4 gives an interpolated 10 here too.
        ([10, 20, 30, 40], 40, 20),  # Definition 4 instead gives 20 exactly.
        ([10, 20, 30, 40, 50], 20, 15),  # n*p=1, unlike common linear interpolation.
        ([10, 20, 30, 40, 50], 40, 25),
        ([0, 10, 20, 30], 50, 15),
        ([0, 10, 20], 50, 10),
        ([7], 20, 7),
        ([40, None, 10, float("nan"), 30, 20], 0, 10),
        ([40, None, 10, float("nan"), 30, 20], 100, 40),
        ([5, 5, 5, 5, 5], 80, 5),
        (list(range(1, 51)), 58, 29.5),  # 0.58 * 50 is not exactly 29 in binary floats.
    ],
)
def test_definition5_hand_calculated_cases(values, percent, expected):
    assert percentile_definition5(values, percent) == expected


@pytest.mark.parametrize("percent", [-1, 101, 20.0, True])
def test_percentile_rejects_unsupported_percentages(percent):
    with pytest.raises(ValueError, match="integer"):
        percentile_definition5([1, 2, 3], percent)


@pytest.mark.parametrize("values", [[], [None, float("nan")], [1, float("inf")]])
def test_no_observed_or_nonfinite_scores_fail_explicitly(values):
    with pytest.raises(ValueError):
        percentile_definition5(values, 20)


def test_initial_medians_keep_quintile_order_when_rows_are_reversed():
    values = list(range(1, 11))
    expected = {1: 1.5, 2: 3.5, 3: 5.5, 4: 7.5, 5: 9.5}
    assert quintile_medians(values) == expected
    assert list(quintile_medians(values[::-1]).items()) == list(expected.items())


def test_ties_do_not_invent_or_renumber_empty_initial_intervals():
    assert quintile_medians([1] * 5 + [2] * 5) == {1: 1, 3: 2}
    assert quintile_medians([0, None, 0, float("nan")]) == {1: 0}


@pytest.mark.parametrize(
    "distance,expected",
    [(0, 3), (math.nextafter(1, 0), 3), (1, 3), (math.nextafter(1, math.inf), -3)],
)
def test_strict_boundary_uses_distance_and_preserves_one_based_identity(distance, expected):
    assert strict_cluster_identifier(3, distance, strict=1) == expected


def test_strict_distance_is_not_squared_distance():
    assert strict_cluster_identifier(2, 1.5, strict=2) == 2
    assert strict_cluster_identifier(2, 2.1, strict=2) == -2


@pytest.mark.parametrize("cluster", [0, -1, True, 1.0])
def test_strict_rejects_zero_based_or_invalid_nearest_cluster(cluster):
    with pytest.raises(ValueError, match="one-based"):
        strict_cluster_identifier(cluster, 0)


@pytest.mark.parametrize("distance,strict", [(-1, 1), (math.nan, 1), (1, -1), (1, math.inf)])
def test_strict_rejects_invalid_distances(distance, strict):
    with pytest.raises(ValueError):
        strict_cluster_identifier(1, distance, strict)


def test_outlier_sign_and_center_order_do_not_shift_star_labels():
    stars = stars_by_cluster_center({1: 2, 2: -2, 3: 0, 4: 1, 5: -1})
    assert stars == {2: 1, 5: 2, 3: 3, 4: 4, 1: 5}
    assert star_for_cluster(strict_cluster_identifier(2, 1.1), stars) == 1
    assert star_for_cluster(2, stars) == 1
    assert star_for_cluster(-1, stars) == 5
    assert star_for_cluster(None, stars) is None


def test_nonconsecutive_ids_still_use_their_recorded_centers():
    stars = stars_by_cluster_center({5: -3, 1: 1, 3: 0})
    assert star_for_cluster(-5, stars) == 1
    assert star_for_cluster(1, stars) == 3


@pytest.mark.parametrize("cluster", [0, 4, True, 1.0])
def test_no_zero_based_or_unknown_cluster_can_become_a_rating(cluster):
    with pytest.raises(ValueError):
        star_for_cluster(cluster, {1: 1, 2: 2, 3: 3})


@pytest.mark.parametrize("star", [0, 6, True, 1.0])
def test_invalid_star_values_cannot_hide_a_label_conversion_error(star):
    with pytest.raises(ValueError, match="stars must"):
        star_for_cluster(-1, {1: star})


def test_equal_centers_are_unresolved_instead_of_assumed_to_follow_input_order():
    with pytest.raises(ValueError, match="runtime evidence"):
        stars_by_cluster_center({1: 0, 2: 0})


@pytest.mark.parametrize("centers", [{}, {0: 1}, {1: math.nan}, {1: math.inf}])
def test_invalid_center_tables_cannot_produce_stars(centers):
    with pytest.raises(ValueError):
        stars_by_cluster_center(centers)
