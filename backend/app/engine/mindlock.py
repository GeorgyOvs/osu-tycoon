"""Mindlock: getting stuck on one spot of one map.

Mostly luck. A player who keeps dying or choking at the same place of a map can start to tense up there; the block
then adds nerves around that place until a break, a calm clean pass or a lucky "click" dissolves it. Mastery of the
map weakens it. Everything is per (player, map); the spot is a slice of the 40-slice timeline.
"""

import random

BUCKETS = 40
NEAR = 2  # slices around the spot that count as "the same place"
LOCK_AFTER = 3  # failures at the same place before a block can appear
INITIAL = 0.35
GROW = 0.10
RELIEF = 0.22
CLICK_CHANCE = 0.05  # per attempt that gets past the spot
DAILY_RETENTION = 0.93  # a block fades by itself in ~10 days away from the map
FORGET_BELOW = 0.04


def trouble_bucket(attempt, n_objects: int) -> int | None:
    """Where an attempt went wrong: the fail point, the choke, or the worst stretch of misses."""
    if attempt.fail_progress is not None:
        return min(BUCKETS - 1, int(attempt.fail_progress * BUCKETS))
    if attempt.choke_note is not None and n_objects:
        # choke_note = (combo, objects left, time): 'objects left' locates it
        left = attempt.choke_note[1]
        return min(BUCKETS - 1, max(0, int((1 - left / n_objects) * BUCKETS)))
    if attempt.misses >= 3 and attempt.timeline:
        worst = max(range(len(attempt.timeline)), key=lambda i: attempt.timeline[i].misses)
        return worst if attempt.timeline[worst].misses >= 2 else None
    return None


def onset_chance(streak: int, nerve: float, tilt_resilience: float) -> float:
    """Chance a block appears after `streak` failures at the same place (0 below LOCK_AFTER)."""
    if streak < LOCK_AFTER:
        return 0.0
    shaky = 1.5 - min(nerve, 100) / 100 + (0.5 - min(tilt_resilience, 100) / 200)
    return max(0.0, min(0.6, 0.07 * (streak - LOCK_AFTER + 1) * shaky))


def effective(severity: float, mastery: float) -> float:
    return severity * (1 - 0.5 * mastery)


def faded(severity: float, days_idle: int) -> float:
    return severity * DAILY_RETENTION ** max(0, days_idle)


def near(a: int, b: int) -> bool:
    return abs(a - b) <= NEAR


def rng_for(seed: int, beatmap_id: int, attempts: int) -> random.Random:
    return random.Random(f"{seed}:mindlock:{beatmap_id}:{attempts}")
