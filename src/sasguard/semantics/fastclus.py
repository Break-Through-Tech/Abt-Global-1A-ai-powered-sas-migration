"""Documented pieces of Program 2 clustering, not a FASTCLUS implementation.

Seed replacement, iterative center updates and equidistant assignments are not
implemented here. See docs/fastclus-synthetic-probes.md for evidence and limits.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Mapping, Sequence


def _observed(values: Sequence[float | None]) -> list[float]:
    observed = []
    for value in values:
        if value is None or math.isnan(value):
            continue
        if not math.isfinite(value):
            raise ValueError("scores must be finite or missing")
        observed.append(float(value))
    if not observed:
        raise ValueError("at least one nonmissing score is required")
    return sorted(observed)


def percentile_definition5(values: Sequence[float | None], percent: int) -> float:
    """Compute unweighted PCTLDEF=5 at an integer percentage from 0 to 100.

    At an integer n*p position, average the two adjacent order statistics;
    otherwise use the next observation. Integer arithmetic avoids deciding
    that a decimal percentile position is nonintegral due to float rounding.
    """
    if type(percent) is not int or not 0 <= percent <= 100:
        raise ValueError("percent must be an integer from 0 through 100")
    ordered = _observed(values)
    if percent == 0:
        return ordered[0]
    if percent == 100:
        return ordered[-1]
    position, remainder = divmod(len(ordered) * percent, 100)
    if remainder == 0:
        return ordered[position - 1] / 2 + ordered[position] / 2
    return ordered[position]


def quintile_medians(values: Sequence[float | None]) -> dict[int, float]:
    """Return observed quintile labels and their median, in ascending order.

    Empty intervals remain absent. These keys are the macro's GRP interval
    labels, not the subsequent FASTCLUS cluster identifiers. A SEED= table
    still undergoes FASTCLUS seed selection and replacement.
    """
    ordered = _observed(values)
    boundaries = [percentile_definition5(ordered, percent) for percent in (20, 40, 60, 80)]
    groups: dict[int, list[float]] = {}
    for value in ordered:
        group = bisect_left(boundaries, value) + 1
        groups.setdefault(group, []).append(value)
    return {group: percentile_definition5(scores, 50) for group, scores in groups.items()}


def _positive_cluster(cluster: int) -> None:
    if type(cluster) is not int or cluster <= 0:
        raise ValueError("cluster identifiers must be positive one-based integers")


def strict_cluster_identifier(nearest_cluster: int, distance: float, strict: float = 1) -> int:
    """Encode a known nearest cluster using the documented STRICT distance rule.

    This does not find the nearest seed or update a center. Equality is
    accepted; a distance exceeding STRICT produces a negative identifier.
    """
    _positive_cluster(nearest_cluster)
    if not math.isfinite(distance) or distance < 0:
        raise ValueError("distance must be finite and nonnegative")
    if not math.isfinite(strict) or strict < 0:
        raise ValueError("strict must be finite and nonnegative")
    return -nearest_cluster if distance > strict else nearest_cluster


def stars_by_cluster_center(centers: Mapping[int, float]) -> dict[int, int]:
    """Rank distinct finite centers without treating cluster IDs as star values.

    Equal centers are deliberately rejected until SAS execution establishes
    their ordering. This is a Python boundary, not a SAS tie-breaking claim.
    """
    if not 1 <= len(centers) <= 5:
        raise ValueError("between one and five cluster centers are required")
    for cluster, center in centers.items():
        _positive_cluster(cluster)
        if not math.isfinite(center):
            raise ValueError("cluster centers must be finite")
    if len(set(centers.values())) != len(centers):
        raise ValueError("tied centers require SAS runtime evidence")
    ordered = sorted(centers, key=lambda cluster: centers[cluster])
    return {cluster: star for star, cluster in enumerate(ordered, start=1)}


def star_for_cluster(cluster: int | None, stars: Mapping[int, int]) -> int | None:
    """Apply the macro's ABS(cluster) join without converting IDs to zero-based indexes.

    Missing identifiers stay unassigned. Unknown identifiers raise instead of
    manufacturing a star; this helper does not emulate a general SAS merge.
    """
    if cluster is None:
        return None
    if type(cluster) is not int:
        raise ValueError("cluster identifiers must be signed one-based integers")
    _positive_cluster(abs(cluster))
    try:
        star = stars[abs(cluster)]
    except KeyError as error:
        raise ValueError("cluster has no recorded star mapping") from error
    if type(star) is not int or not 1 <= star <= 5:
        raise ValueError("stars must be integers from 1 through 5")
    return star
