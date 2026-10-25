"""Analytic best-score model for leaderboard NPCs.

Running the note-by-note simulator for hundreds of NPCs per map would be far too slow, so
NPC leaderboard scores come from a closed-form estimate on the same capability scale
(handled stars = 2 * (0.6 + 0.04 * skill)): demand/capability -> expected misses and accuracy,
best of a few attempts, under the mod meta of the era.
"""

import math
import random
from dataclasses import dataclass
from datetime import date

from app.engine import scoring

MOD_OPTIONS = ["", "HD", "HR", "DT", "HDHR", "HDDT"]


@dataclass(frozen=True)
class MapFacts:
    """What the model needs to know about a map, per mod combination."""

    n_objects: int
    max_combo: int
    aim_share: float  # aim / (aim + speed) difficulty: how jumpy vs streamy the map is
    stars: dict[str, float]  # mods -> stable star rating
    ar: dict[str, float]
    od: dict[str, float]
    difficulty: dict[str, int]  # mods -> ScoreV1 difficulty multiplier


@dataclass
class Estimate:
    mods: str
    accuracy: float
    misses: int
    max_combo: int
    n300: int
    n100: int
    n50: int
    score: int


def mod_allowed(mods: str, on: date, ar: float, rng: random.Random) -> bool:
    """Era meta. DT and HDDT were part of score chasing from the early days (a stronger player simply took the
    higher multiplier), so they are mostly available; only the very first years are thinner, and HDDT on AR10+
    maps wasn't done before ~2010."""
    year = on.year + on.month / 12
    if "DT" in mods:
        if rng.random() > min(0.95, max(0.6, 0.6 + 0.12 * (year - 2008))):
            return False
        if "HD" in mods and ar >= 9.8 and year < 2010:
            return False
    if "HR" in mods and year < 2009 and rng.random() < 0.5:
        return False
    return True


def boost(comps: dict[str, float], bonus: float) -> dict[str, float]:
    """Map mastery: knowing a map by heart is worth a few percent of skill on it."""
    return comps if bonus <= 0 else {g: min(115.0, v * (1 + bonus)) for g, v in comps.items()}


def estimate_best(
    comps: dict[str, float],
    facts: MapFacts,
    on: date,
    attempts: int,
    rng: random.Random,
) -> Estimate | None:
    """The best score an NPC with these composites would hold on the map, or None if they can't pass."""
    base = facts.aim_share * comps["aim"] + (1 - facts.aim_share) * comps["tapping"]
    best: Estimate | None = None
    options = []
    for mods in MOD_OPTIONS:
        ar = facts.ar[mods]
        if not mod_allowed(mods, on, ar, rng):
            continue
        skill = base
        if "HD" in mods or ar > 9.6:
            skill = 0.75 * base + 0.25 * comps["reading"]
        if "HR" in mods:
            skill = 0.8 * skill + 0.2 * comps["technical"]
        ratio = facts.stars[mods] / (2 * (0.6 + 0.04 * skill))
        if ratio > 1.25:
            continue  # can't pass it with these mods
        # Rough expected value: the mod bonus, discounted only when the map gets close to the limit.
        risk = 1.0 if ratio < 0.8 else max(0.05, (1.25 - ratio) / 0.45)
        options.append((scoring.mod_multiplier(mods) * risk, mods, ratio))
    for _, mods, ratio in sorted(options, reverse=True)[:2]:
        for _ in range(attempts):
            est = _attempt(comps, facts, mods, ratio, rng)
            if est is None:
                continue  # failed this attempt
            if best is None or est.score > best.score:
                best = est
    return best


def _poisson(lam: float, rng: random.Random) -> int:
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    threshold, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= threshold:
            return k
        k += 1


# Fitted to the note-by-note simulator (FREEDOM DiVE, uniform skills 85/95/105, NM and HDHR).
MISS_RATE, MISS_CENTER, MISS_WIDTH = 0.0062, 0.9, 0.09
FAIL_CENTER, FAIL_CENTER_HR, FAIL_WIDTH = 1.0, 0.98, 0.033
ACC_LOSS_AT_084, ACC_WIDTH, OD_FACTOR = 1.1, 0.09, 0.6


def _longest_run(n: int, misses: int, rng: random.Random) -> int:
    """Longest unbroken run when `misses` misses land on the map: spread out, or bunched in one hard part."""
    if rng.random() < 0.5:
        positions = rng.sample(range(n), misses)
    else:
        center, spread = rng.randrange(n), max(misses, n // 20)
        positions = [min(n - 1, max(0, round(rng.gauss(center, spread)))) for _ in range(misses)]
    cuts = sorted(set(positions))
    edges = [-1, *cuts, n]
    return max(b - a - 1 for a, b in zip(edges, edges[1:]))


def _attempt(comps: dict[str, float], facts: MapFacts, mods: str, ratio: float, rng: random.Random) -> Estimate | None:
    n = facts.n_objects
    center = FAIL_CENTER_HR if "HR" in mods else FAIL_CENTER
    if rng.random() < 1 / (1 + math.exp(-(ratio - center) / FAIL_WIDTH)):
        return None
    nerves = 1.15 - 0.3 * min(comps["mentality"], 100) / 100  # ~1 at mentality 50
    lam = n * MISS_RATE * math.exp((ratio - MISS_CENTER) / MISS_WIDTH) * nerves * rng.uniform(0.5, 1.5)
    misses = min(n, _poisson(lam, rng))
    precision = 1.6 - min(comps["technical"], 110) / 160
    acc_loss = (ACC_LOSS_AT_084 * math.exp((ratio - 0.84) / ACC_WIDTH) * math.exp(OD_FACTOR * (facts.od[mods] - 8))
                * precision * rng.uniform(0.75, 1.25))
    accuracy = max(60.0, 100 - min(acc_loss, 15) - 100 * misses / n)
    n300, n100, n50 = scoring.counts_from_accuracy(n, accuracy, misses)
    accuracy = 100 * (300 * n300 + 100 * n100 + 50 * n50) / (300 * n)
    if misses == 0:
        max_combo = facts.max_combo
    else:
        max_combo = max(1, round(_longest_run(n, misses, rng) * facts.max_combo / n))
    score = scoring.score_v1(n300, n100, n50, misses, max_combo, facts.max_combo, facts.difficulty[mods], mods)
    return Estimate(mods, accuracy, misses, max_combo, n300, n100, n50, score)
