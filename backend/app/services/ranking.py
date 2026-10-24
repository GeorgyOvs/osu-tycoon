"""Profile-wide aggregates: weighted PP, overall accuracy and global rank."""

import bisect
import math
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Protocol, TypeVar

from app.config import PP_WEIGHT_DECAY, TOP_PLAYS_LIMIT


class _Play(Protocol):
    beatmap_id: int
    pp: float
    accuracy: float


T = TypeVar("T", bound=_Play)


def top_plays(scores: Iterable[T], limit: int = TOP_PLAYS_LIMIT) -> list[T]:
    """Best play per beatmap, sorted by PP descending."""
    best: dict[int, T] = {}
    for s in scores:
        current = best.get(s.beatmap_id)
        if current is None or s.pp > current.pp:
            best[s.beatmap_id] = s
    return sorted(best.values(), key=lambda s: s.pp, reverse=True)[:limit]


def weighted_pp(pps: Sequence[float]) -> float:
    """sum(pp_i * 0.95^(i-1)) over plays sorted descending."""
    ordered = sorted(pps, reverse=True)
    return sum(pp * PP_WEIGHT_DECAY**i for i, pp in enumerate(ordered))


def weighted_accuracy(plays: Sequence[_Play]) -> float:
    """Overall accuracy: weighted mean of top-play accuracies, same weights as PP."""
    if not plays:
        return 0.0
    weights = [PP_WEIGHT_DECAY**i for i in range(len(plays))]
    return sum(p.accuracy * w for p, w in zip(plays, weights)) / sum(weights)


# Modern pp -> rank curve (#1 at 25k). Other eras rescale it: pp is divided by that year's
# top-pp level (4000pp meant far more in 2012 than in 2024) and ranks are multiplied by the
# size of the player base.
_RANK_CURVE: list[tuple[float, int]] = [
    (0, 1_500_000),
    (500, 900_000),
    (1000, 600_000),
    (2000, 300_000),
    (3000, 150_000),
    (4000, 80_000),
    (5000, 45_000),
    (6000, 25_000),
    (7000, 13_000),
    (8000, 6_500),
    (10000, 2_000),
    (12000, 600),
    (15000, 100),
    (20000, 5),
    (25000, 1),
]
_CURVE_PP = [pp for pp, _ in _RANK_CURVE]
_MODERN_TOP_PP = 25000.0

# (year, approximate #1 total pp, player base relative to 2020). Interpolated by date.
_ERA_TABLE: list[tuple[float, float, float]] = [
    (2007.7, 5000, 0.02),
    (2009.0, 7000, 0.08),
    (2011.0, 9000, 0.2),
    (2013.0, 11000, 0.4),
    (2015.0, 13000, 0.6),
    (2017.0, 15000, 0.75),
    (2019.0, 17500, 0.9),
    (2021.0, 20500, 1.0),
    (2023.0, 23500, 1.05),
    (2025.0, 25000, 1.1),
]


def _year_fraction(on: date) -> float:
    return on.year + (on.timetuple().tm_yday - 1) / 366


def _era(on: date) -> tuple[float, float]:
    """(top pp, population factor) for a date."""
    y = _year_fraction(on)
    table = _ERA_TABLE
    if y <= table[0][0]:
        return table[0][1], table[0][2]
    if y >= table[-1][0]:
        return table[-1][1], table[-1][2]
    i = bisect.bisect_right([row[0] for row in table], y)
    (y0, pp0, pop0), (y1, pp1, pop1) = table[i - 1], table[i]
    t = (y - y0) / (y1 - y0)
    return pp0 + t * (pp1 - pp0), pop0 + t * (pop1 - pop0)


def top_pp(on: date) -> float:
    return _era(on)[0]


def _base_rank(modern_pp: float) -> float:
    if modern_pp >= _CURVE_PP[-1]:
        return 1.0
    i = bisect.bisect_right(_CURVE_PP, modern_pp)
    (pp_lo, rank_lo), (pp_hi, rank_hi) = _RANK_CURVE[i - 1], _RANK_CURVE[i]
    # Interpolate in log space so the curve stays smooth across orders of magnitude.
    t = (modern_pp - pp_lo) / (pp_hi - pp_lo)
    return math.exp(math.log(rank_lo) + t * (math.log(rank_hi) - math.log(rank_lo)))


def estimate_global_rank(total_pp: float, on: date) -> int | None:
    if total_pp <= 0:
        return None
    top, population = _era(on)
    return max(1, round(_base_rank(total_pp * _MODERN_TOP_PP / top) * population))


def pp_for_rank(rank: float, on: date) -> float:
    """Inverse of estimate_global_rank (approximately): the pp that sits at `rank` on `on`."""
    top, population = _era(on)
    target = max(1.0, rank / population)
    if target <= 1:
        return top
    for (pp_lo, rank_lo), (pp_hi, rank_hi) in zip(_RANK_CURVE, _RANK_CURVE[1:]):
        if rank_hi <= target <= rank_lo:
            t = (math.log(rank_lo) - math.log(target)) / (math.log(rank_lo) - math.log(rank_hi))
            return (pp_lo + t * (pp_hi - pp_lo)) * top / _MODERN_TOP_PP
    return 0.0
