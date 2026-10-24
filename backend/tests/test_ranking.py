from dataclasses import dataclass
from datetime import date

import pytest

from app.services import ranking


@dataclass
class P:
    beatmap_id: int
    pp: float
    accuracy: float = 100.0


def test_weighted_pp_applies_decay_in_descending_order():
    assert ranking.weighted_pp([100, 200]) == pytest.approx(200 + 100 * 0.95)
    assert ranking.weighted_pp([]) == 0


def test_weighted_pp_geometric_series_limit():
    # 100 plays of 100pp each: 100 * (1 - 0.95^100) / 0.05
    assert ranking.weighted_pp([100] * 100) == pytest.approx(100 * (1 - 0.95**100) / 0.05)


def test_top_plays_keeps_best_per_beatmap_and_limits():
    scores = [P(1, 100), P(1, 150), P(2, 120), P(3, 50)]
    top = ranking.top_plays(scores, limit=2)
    assert [(s.beatmap_id, s.pp) for s in top] == [(1, 150), (2, 120)]


def test_weighted_accuracy():
    plays = [P(1, 200, 100.0), P(2, 100, 90.0)]
    assert ranking.weighted_accuracy(plays) == pytest.approx((100 + 90 * 0.95) / 1.95)
    assert ranking.weighted_accuracy([]) == 0


def test_rank_estimate_is_monotonic():
    on = date(2024, 6, 1)
    assert ranking.estimate_global_rank(0, on) is None
    ranks = [ranking.estimate_global_rank(pp, on) for pp in range(100, 30000, 250)]
    assert all(a >= b for a, b in zip(ranks, ranks[1:]))
    assert ranking.estimate_global_rank(30000, on) == 1


def test_rank_curve_is_era_aware():
    # 6000pp: a top player in 2010, unremarkable in 2024.
    assert ranking.estimate_global_rank(6000, date(2010, 6, 1)) < 1000
    assert ranking.estimate_global_rank(6000, date(2024, 6, 1)) > 10000
    # fewer players back then: the bottom of the ladder is shorter
    assert ranking.estimate_global_rank(10, date(2010, 6, 1)) < ranking.estimate_global_rank(10, date(2024, 6, 1))


@pytest.mark.parametrize("rank", [1, 50, 1000, 20000, 300000])
@pytest.mark.parametrize("on", [date(2011, 3, 1), date(2018, 3, 1), date(2024, 3, 1)])
def test_pp_for_rank_inverts_the_curve(rank, on):
    pp = ranking.pp_for_rank(rank, on)
    back = ranking.estimate_global_rank(pp, on)
    assert back == pytest.approx(rank, rel=0.05, abs=2)
