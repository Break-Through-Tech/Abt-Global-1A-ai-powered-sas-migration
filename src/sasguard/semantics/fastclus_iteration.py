"""Seed selection, seed replacement and the update loop for Program 2's FASTCLUS step.
Works on one score per hospital (summary_score) and only covers the FASTCLUS
options the %kmeans macro uses. When the SAS docs don't say what happens, the
code raises UnresolvedSASBehavior instead of guessing.

Not connected to the model workflow yet.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sasguard.semantics.fastclus import (
    quintile_medians,
    star_for_cluster,
    stars_by_cluster_center,
    strict_cluster_identifier,
)

TieResolver = Callable[[float, tuple[int, ...]], int]
"""Chooses a cluster for a score that is exactly equidistant from several seeds.
Receives the score and the tied one-based cluster IDs, and must return one of them.
Equidistant assignment is tracked separately in issue #69; until that rule is
resolved, leaving the resolver as None raises UnresolvedSASBehavior on any tie.
"""

_REPLACE_METHODS = frozenset({"FULL", "PART", "NONE"})


class UnresolvedSASBehavior(ValueError):
    """Raised where SAS documentation does not determine the result."""


@dataclass(frozen=True)
class FastclusResult:
    """Outcome of one PROC FASTCLUS run.
    initial_seeds: seeds after selection and replacement, in cluster-number order.
    final_seeds: seeds after the last update; these define the final assignment.
    final_means: means of the positively assigned scores per cluster after the final
        assignment, or None for a cluster with no positive members. These equal
        final_seeds when the run converged.
    clusters: one signed one-based cluster ID per input score, in input order.
        A negative ID means STRICT excluded the score; abs() is its nearest cluster.
    max_seed_changes: largest absolute seed movement in each iteration.
    """

    initial_seeds: tuple[float, ...]
    final_seeds: tuple[float, ...]
    final_means: tuple[float | None, ...]
    clusters: tuple[int, ...]
    iterations: int
    converged: bool
    max_seed_changes: tuple[float, ...]


@dataclass(frozen=True)
class Program2Clustering:
    """Both FASTCLUS passes of the %kmeans macro and the resulting stars."""

    pass1: FastclusResult
    pass2: FastclusResult
    stars: tuple[int, ...]


def _finite_scores(values: Sequence[float], name: str) -> list[float]:
    scores = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be numbers; filter missing scores before clustering")
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite; filter missing scores before clustering")
        scores.append(float(value))
    return scores


def _minimum_pairwise(seeds: Sequence[float]) -> tuple[float, list[tuple[int, int]]]:
    """Return the smallest distance between seeds and every index pair at that distance."""
    best = math.inf
    pairs: list[tuple[int, int]] = []
    for i in range(len(seeds)):
        for j in range(i + 1, len(seeds)):
            distance = abs(seeds[i] - seeds[j])
            if distance < best:
                best, pairs = distance, [(i, j)]
            elif distance == best:
                pairs.append((i, j))
    return best, pairs


def _nearest(score: float, seeds: Sequence[float]) -> tuple[float, list[int]]:
    """Return the nearest distance and every zero-based seed index at that distance."""
    distances = [abs(score - seed) for seed in seeds]
    best = min(distances)
    return best, [index for index, distance in enumerate(distances) if distance == best]


def _replacement_target(score: float, seeds: list[float], full: bool) -> int | None:
    """Apply the two documented replacement tests; return the index to replace, if any."""
    if len(seeds) < 2:
        raise UnresolvedSASBehavior(
            "seed replacement needs a minimum distance between seeds, which one seed lacks"
        )
    nearest_distance, nearest_indexes = _nearest(score, seeds)
    between, closest_pairs = _minimum_pairwise(seeds)

    # Test 1: the observation is farther from its closest seed than the two closest
    # seeds are from each other. One seed of that closest pair is replaced.
    if nearest_distance > between:
        if len(closest_pairs) > 1:
            raise UnresolvedSASBehavior("several seed pairs tie for the minimum distance")
        first, second = closest_pairs[0]
        distance_if_replaced: dict[int, float] = {}
        # The other seeds plus the observation, which takes the replaced seed's place.
        remaining = [s for i, s in enumerate(seeds) if i not in (first, second)]
        remaining.append(score)
        for kept in (first, second):
            # Distance from this seed to the closest remaining seed when the other
            # seed of the pair is replaced by the current observation.
            distance_if_replaced[kept] = min(abs(seeds[kept] - s) for s in remaining)
        if distance_if_replaced[first] == distance_if_replaced[second]:
            raise UnresolvedSASBehavior("both seeds of the closest pair qualify for replacement")
        return min(distance_if_replaced, key=lambda index: distance_if_replaced[index])

    if not full:
        return None

    # Test 2: the observation is farther from every seed except its nearest one than
    # that nearest seed is from all other seeds. The nearest seed is replaced.
    passing = []
    for nearest in nearest_indexes:
        others = [s for i, s in enumerate(seeds) if i != nearest]
        to_other_seeds = min(abs(score - s) for s in others)
        nearest_to_others = min(abs(seeds[nearest] - s) for s in others)
        if to_other_seeds > nearest_to_others:
            passing.append(nearest)
    if not passing:
        return None
    if len(nearest_indexes) > 1:
        raise UnresolvedSASBehavior("the observation is equidistant from two replaceable seeds")
    return passing[0]


def select_initial_seeds(
    rows: Sequence[float | None],
    maxc: int,
    radius: float = 0.0,
    replace: str = "FULL",
) -> list[float]:
    """Pick the starting seeds from the SEED= rows, going in row order.
    The first row becomes seed 1. Each next row becomes a new seed if there's
    still room (fewer than MAXC) and it isn't too close to an existing seed.
    Otherwise SAS's replacement tests decide whether it swaps out an old seed.
    A swapped seed keeps its spot, so cluster numbers don't shift.
    Missing rows are skipped. Duplicate rows raise an error, because the SAS
    docs contradict each other on that case.
    """
    if type(maxc) is not int or maxc < 1:
        raise ValueError("maxc must be a positive integer")
    if isinstance(radius, bool) or not math.isfinite(radius) or radius < 0:
        raise ValueError("radius must be finite and nonnegative")
    if replace not in _REPLACE_METHODS:
        raise ValueError("replace must be FULL, PART or NONE")

    seeds: list[float] = []
    for row in rows:
        if row is None or (isinstance(row, float) and math.isnan(row)):
            continue
        (score,) = _finite_scores([row], "seed rows")
        if not seeds:
            seeds.append(score)
            continue
        nearest_distance, _ = _nearest(score, seeds)
        if len(seeds) < maxc:
            if nearest_distance > radius:
                seeds.append(score)
                continue
            if nearest_distance == radius:
                raise UnresolvedSASBehavior(
                    "a seed row lies exactly RADIUS from a seed; SAS documentation gives "
                    "both 'at least' and 'exceeds' for this comparison"
                )
        if replace == "NONE":
            continue
        target = _replacement_target(score, seeds, full=replace == "FULL")
        if target is not None:
            seeds[target] = score
    if not seeds:
        raise ValueError("at least one complete seed row is required")
    return seeds


def assign_nearest(
    scores: Sequence[float],
    seeds: Sequence[float],
    strict: float | None = None,
    on_tie: TieResolver | None = None,
) -> list[int]:
    """Assign each score to its nearest seed, returning signed one-based cluster IDs.
    With STRICT, a score farther than STRICT from its nearest seed gets the negative
    of that cluster's ID (distance equal to STRICT is accepted). An exact tie between
    seeds raises unless on_tie is given.
    """
    points = _finite_scores(scores, "scores")
    centers = _finite_scores(seeds, "seeds")
    if not centers:
        raise ValueError("at least one seed is required")
    clusters = []
    for point in points:
        distance, indexes = _nearest(point, centers)
        tied = tuple(index + 1 for index in indexes)
        if len(tied) == 1:
            cluster = tied[0]
        elif on_tie is None:
            raise UnresolvedSASBehavior(
                f"score {point!r} is equidistant from clusters {tied}; equidistant "
                "assignment is not yet resolved"
            )
        else:
            cluster = on_tie(point, tied)
            if cluster not in tied:
                raise ValueError("on_tie must return one of the tied cluster IDs")
        if strict is not None:
            cluster = strict_cluster_identifier(cluster, distance, strict)
        clusters.append(cluster)
    return clusters


def _cluster_means(
    scores: Sequence[float], clusters: Sequence[int], count: int
) -> list[float | None]:
    members: list[list[float]] = [[] for _ in range(count)]
    for score, cluster in zip(scores, clusters, strict=True):
        if cluster > 0:  # STRICT-excluded (negative) scores do not update centers.
            members[cluster - 1].append(score)
    return [math.fsum(group) / len(group) if group else None for group in members]


def run_fastclus(
    scores: Sequence[float],
    seed_rows: Sequence[float | None],
    *,
    maxc: int,
    maxiter: int = 1,
    converge: float = 0.02,
    strict: float | None = None,
    radius: float = 0.0,
    replace: str = "FULL",
    on_tie: TieResolver | None = None,
) -> FastclusResult:
    """Run one FASTCLUS pass.
    Pick the starting seeds, then repeat up to MAXITER times: put each hospital
    in its nearest group, then move each seed to the average of its group.
    Stop once the seeds barely move (with CONVERGE=0, once they don't move at
    all). Finally, put each hospital in its nearest group one last time.
    If a group ends up with no hospitals, this raises an error, because the SAS
    docs don't say what happens then.
    """
    points = _finite_scores(scores, "scores")
    if not points:
        raise ValueError("at least one score is required")
    if type(maxiter) is not int or maxiter < 0:
        raise ValueError("maxiter must be a nonnegative integer")
    if isinstance(converge, bool) or not math.isfinite(converge) or converge < 0:
        raise ValueError("converge must be finite and nonnegative")

    seeds = select_initial_seeds(seed_rows, maxc, radius, replace)
    initial = tuple(seeds)
    scale = _minimum_pairwise(seeds)[0] if len(seeds) > 1 else None
    if converge > 0 and maxiter > 0 and not scale:
        raise UnresolvedSASBehavior(
            "a positive CONVERGE needs a nonzero minimum distance between initial seeds"
        )

    changes: list[float] = []
    converged = False
    for _ in range(maxiter):
        clusters = assign_nearest(points, seeds, strict, on_tie)
        means = _cluster_means(points, clusters, len(seeds))
        if any(mean is None for mean in means):
            raise UnresolvedSASBehavior("a cluster has no assigned scores during an iteration")
        updated = [mean for mean in means if mean is not None]
        change = max(abs(new - old) for new, old in zip(updated, seeds, strict=True))
        changes.append(change)
        seeds = updated
        if change == 0 or (scale and change / scale <= converge):
            converged = True
            break

    final = assign_nearest(points, seeds, strict, on_tie)
    return FastclusResult(
        initial_seeds=initial,
        final_seeds=tuple(seeds),
        final_means=tuple(_cluster_means(points, final, len(seeds))),
        clusters=tuple(final),
        iterations=len(changes),
        converged=converged,
        max_seed_changes=tuple(changes),
    )


def program2_two_pass(
    scores: Sequence[float], on_tie: TieResolver | None = None
) -> Program2Clustering:
    """Run the %kmeans macro's two passes for one peer group and assign stars.

    Pass 1 seeds are the quintile-interval medians in interval order, with MAXC=5,
    CONVERGE=0 and MAXITER=1000.

    Pass 2 reuses pass 1's final seeds and adds STRICT=1.
    Stars rank pass 2's final centers from lowest (1 star) upward; STRICT-excluded
    scores take the star of their nearest cluster through ABS().
    Raises if either pass stops before converging, because the documentation does
    not say whether the macro then reuses final seeds or final cluster means.
    """
    points = _finite_scores(scores, "scores")
    medians = quintile_medians(points)
    seed_rows = [medians[group] for group in sorted(medians)]
    pass1 = run_fastclus(points, seed_rows, maxc=5, maxiter=1000, converge=0, on_tie=on_tie)
    if not pass1.converged:
        raise UnresolvedSASBehavior("pass 1 reached MAXITER before converging")
    pass2 = run_fastclus(
        points, pass1.final_seeds, maxc=5, maxiter=1000, converge=0, strict=1, on_tie=on_tie
    )
    if not pass2.converged:
        raise UnresolvedSASBehavior("pass 2 reached MAXITER before converging")
    star_map = stars_by_cluster_center(
        {cluster: center for cluster, center in enumerate(pass2.final_seeds, start=1)}
    )
    stars = []
    for cluster in pass2.clusters:
        star = star_for_cluster(cluster, star_map)
        assert star is not None  # every finite score has a cluster
        stars.append(star)
    return Program2Clustering(pass1=pass1, pass2=pass2, stars=tuple(stars))
