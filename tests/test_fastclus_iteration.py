"""Synthetic, hand-calculated cases for FASTCLUS seed selection and iteration.
These check the documented rules in docs/fastclus-iteration.md. They are not
outputs captured from a SAS runtime, and no hospital data is used.
"""

import math

import pytest

from sasguard.semantics.fastclus_iteration import (
    UnresolvedSASBehavior,
    assign_nearest,
    program2_two_pass,
    run_fastclus,
    select_initial_seeds,
)

POINTS = [0, 1, 2, 10, 11, 12]


# Initial seed selection


def test_distinct_rows_become_seeds_in_row_order():
    assert select_initial_seeds([3, 1, 2], maxc=5) == [3, 1, 2]


def test_missing_rows_are_skipped_because_seeds_must_be_complete():
    assert select_initial_seeds([None, math.nan, 2, 5], maxc=5) == [2, 5]


def test_fewer_rows_than_maxc_leaves_fewer_seeds():
    assert select_initial_seeds([1, 4], maxc=5) == [1, 4]


def test_duplicate_seed_row_is_unresolved_under_default_radius():
    # Distance 0 equals RADIUS=0; the docs say both "at least" and "exceeds".
    with pytest.raises(UnresolvedSASBehavior, match="RADIUS"):
        select_initial_seeds([1, 1], maxc=5)


def test_duplicate_row_after_seeds_are_full_replaces_nothing():
    # Both tests compare with ">", and a duplicate only ever ties.
    assert select_initial_seeds([0, 3, 3], maxc=2) == [0, 3]


# Seed replacement


def test_first_test_replaces_the_closer_seed_of_the_closest_pair():
    # Seeds 0 and 1 are 1 apart; 10 is 9 from its nearest seed, so test 1 fires.
    # Replacing 0 would leave 1 at distance 9 from 10; replacing 1 leaves 0 at 10.
    # The seed with the shorter distance (1) is replaced.
    assert select_initial_seeds([0, 1, 10], maxc=2) == [0, 10]


def test_second_test_replaces_the_nearest_seed():
    # RADIUS=1 stops 5.5 from becoming a new seed (0.5 from seed 5). Test 1 fails
    # (0.5 is not above 5). Test 2: 5.5 is 5.5 from the other seed, more than the
    # 5 between seed 5 and seed 0, so seed 5 is replaced.
    assert select_initial_seeds([0, 5, 5.5], maxc=5, radius=1) == [0, 5.5]


def test_replace_part_runs_only_the_first_test():
    assert select_initial_seeds([0, 5, 5.5], maxc=5, radius=1, replace="PART") == [0, 5]
    assert select_initial_seeds([0, 1, 10], maxc=2, replace="PART") == [0, 10]


def test_replace_none_keeps_the_first_seeds():
    assert select_initial_seeds([0, 1, 10], maxc=2, replace="NONE") == [0, 1]


def test_replaced_seed_keeps_its_cluster_position():
    # 6 replaces seed 5 by test 2 (slot 3). Then 20 replaces seed 1 by test 1
    # (slot 2), so cluster numbers follow slots, not values.
    assert select_initial_seeds([0, 1, 5, 6, 20], maxc=3) == [0, 20, 6]


def test_tied_closest_pairs_are_unresolved():
    with pytest.raises(UnresolvedSASBehavior, match="pairs tie"):
        select_initial_seeds([0, 1, 2, 10], maxc=3)


def test_tied_replacement_candidates_are_unresolved():
    # Closest pair is 0 and 1. Either replacement leaves the kept seed 5 from
    # its closest remaining seed (-5 or the new 6), so the rule does not decide.
    with pytest.raises(UnresolvedSASBehavior, match="both seeds"):
        select_initial_seeds([-5, 0, 1, 6], maxc=3)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"maxc": 0},
        {"maxc": True},
        {"maxc": 5, "radius": -1},
        {"maxc": 5, "radius": math.inf},
        {"maxc": 5, "replace": "RANDOM"},
    ],
)
def test_unsupported_seed_options_are_rejected(kwargs):
    with pytest.raises(ValueError):
        select_initial_seeds([1, 2], **kwargs)


def test_all_missing_seed_rows_are_rejected():
    with pytest.raises(ValueError, match="complete seed row"):
        select_initial_seeds([None, math.nan], maxc=5)


# Assignment


def test_equidistant_score_is_unresolved_without_a_tie_rule():
    with pytest.raises(UnresolvedSASBehavior, match="equidistant"):
        assign_nearest([1], [0, 2])


def test_tie_resolver_must_choose_a_tied_cluster():
    assert assign_nearest([1], [0, 2], on_tie=lambda score, tied: tied[-1]) == [2]
    with pytest.raises(ValueError, match="tied cluster"):
        assign_nearest([1], [0, 2, 9], on_tie=lambda score, tied: 3)


@pytest.mark.parametrize("choice", [1.0, True])
def test_tie_resolver_must_return_an_integer_cluster(choice):
    # 1.0 and True both compare equal to 1, so they would slip past "in tied".
    with pytest.raises(ValueError, match="tied cluster"):
        assign_nearest([1], [0, 2], on_tie=lambda score, tied: choice)


def test_strict_marks_far_scores_negative_and_keeps_equality():
    assert assign_nearest([0, 1, 2.5], [0], strict=1) == [1, 1, -1]


@pytest.mark.parametrize("scores", [[None], [math.nan], [math.inf], [True]])
def test_missing_or_invalid_scores_are_rejected(scores):
    with pytest.raises(ValueError):
        assign_nearest(scores, [0])


# Iteration


def test_maxiter_zero_only_assigns_to_initial_seeds():
    result = run_fastclus([0, 1, 9, 10], [0, 10], maxc=5, maxiter=0)
    assert result.iterations == 0
    assert result.final_seeds == (0, 10)
    assert result.clusters == (1, 1, 2, 2)
    assert result.final_means == (0.5, 9.5)


def test_converge_zero_iterates_until_no_seed_moves():
    # Iteration 1: {0, 1} and {2, 10, 11, 12} -> means 0.5 and 8.75.
    # Iteration 2: {0, 1, 2} and {10, 11, 12} -> means 1 and 11.
    # Iteration 3: no change, so the run converges.
    result = run_fastclus(POINTS, [1, 2], maxc=5, maxiter=1000, converge=0)
    assert result.max_seed_changes == (6.75, 2.25, 0.0)
    assert result.converged and result.iterations == 3
    assert result.final_seeds == result.final_means == (1, 11)
    assert result.clusters == (1, 1, 1, 2, 2, 2)


def test_maxiter_cap_separates_final_seeds_from_final_means():
    result = run_fastclus(POINTS, [1, 2], maxc=5, maxiter=1, converge=0)
    assert not result.converged
    assert result.final_seeds == (0.5, 8.75)
    assert result.final_means == (1, 11)


def test_converge_scales_by_minimum_distance_between_initial_seeds():
    # Seeds 0 and 3 are 3 apart. Iteration 1 moves a seed by 5.75, a relative
    # change of about 1.92: within CONVERGE=2 but not CONVERGE=1.9.
    assert run_fastclus(POINTS, [0, 3], maxc=5, maxiter=1000, converge=2).iterations == 1
    assert run_fastclus(POINTS, [0, 3], maxc=5, maxiter=1000, converge=1.9).iterations == 2


def test_strict_excluded_scores_do_not_move_centers():
    scores = [0, 1, 10, 11, 30]
    strict = run_fastclus(scores, [0.5, 10.5], maxc=5, maxiter=1000, converge=0, strict=1)
    assert strict.final_seeds == (0.5, 10.5)
    assert strict.clusters == (1, 1, 2, 2, -2)
    loose = run_fastclus(scores, [0.5, 10.5], maxc=5, maxiter=1000, converge=0)
    assert loose.final_seeds == (0.5, 17)


def test_empty_cluster_during_iteration_is_unresolved():
    with pytest.raises(UnresolvedSASBehavior, match="no assigned scores"):
        run_fastclus([0, 1], [0.5, 100], maxc=5, maxiter=1000, converge=0)


def test_positive_converge_with_one_seed_is_unresolved():
    with pytest.raises(UnresolvedSASBehavior, match="CONVERGE"):
        run_fastclus([0, 2], [1], maxc=5, maxiter=5, converge=0.02)


def test_seed_row_order_changes_cluster_ids_not_centers():
    forward = run_fastclus(POINTS, [1, 11], maxc=5, maxiter=1000, converge=0)
    reverse = run_fastclus(POINTS, [11, 1], maxc=5, maxiter=1000, converge=0)
    assert forward.clusters == (1, 1, 1, 2, 2, 2)
    assert reverse.clusters == (2, 2, 2, 1, 1, 1)
    assert sorted(forward.final_seeds) == sorted(reverse.final_seeds)


# Two-pass macro composition

FIVE_GROUPS = [-4.1, -4.0, -3.9, -2.1, -2.0, -1.9, -0.1, 0.0, 0.1, 1.9, 2.0, 2.1, 3.9, 4.0, 4.1]


def test_two_pass_separated_groups_get_ordered_stars():
    result = program2_two_pass(FIVE_GROUPS)
    assert result.pass1.initial_seeds == (-4, -2, 0, 2, 4)
    assert result.pass2.final_seeds == pytest.approx((-4, -2, 0, 2, 4))
    assert result.stars == (1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 5)


def test_two_pass_strict_exclusion_keeps_the_nearest_clusters_star():
    # With an outlier at 20, pass 1 gives it its own cluster and centers the
    # fourth cluster at 3. In pass 2, 1.9 and 4.1 are 1.1 from that center,
    # so STRICT=1 marks them -4; ABS still gives them 4 stars.
    result = program2_two_pass([*FIVE_GROUPS, 20.0])
    assert result.pass2.final_seeds == pytest.approx((-4, -2, 0, 3, 20))
    assert result.pass2.clusters[9] == -4 and result.pass2.clusters[14] == -4
    assert result.stars == (1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 4, 4, 4, 5)


def test_two_pass_rejects_missing_scores():
    with pytest.raises(ValueError):
        program2_two_pass([1.0, None, 2.0])
