"""osu!stable ScoreV1, approximated from hit counts and combo.

Per hit: hit_value + hit_value * (combo_before * difficulty_multiplier * mod_multiplier / 25).
Slider ticks and spinner bonus are ignored; the combo term dominates anyway, which is why
full combos rule stable leaderboards.
"""

import math

MOD_MULTIPLIERS = {"HD": 1.06, "HR": 1.06, "DT": 1.12, "NC": 1.12, "FL": 1.12, "EZ": 0.5, "NF": 0.5, "HT": 0.3,
                   "SO": 0.9}


def mod_multiplier(mods: str) -> float:
    mult = 1.0
    for i in range(0, len(mods), 2):
        mult *= MOD_MULTIPLIERS.get(mods[i : i + 2], 1.0)
    return mult


def difficulty_multiplier(hp: float, cs: float, od: float, n_objects: int, drain_seconds: float) -> int:
    """stable's 'difficulty points': base map settings plus note density, scaled to roughly 2-6."""
    density = min(16.0, max(0.0, n_objects / max(drain_seconds, 1.0) * 8))
    return round((hp + cs + od + density) / 38 * 5)


def _combo_sum(segments: list[int]) -> float:
    # Sum of combo_before over a run of L hits is 0 + 1 + ... + (L-1).
    return sum(length * (length - 1) / 2 for length in segments)


def score_v1(
    n300: int,
    n100: int,
    n50: int,
    misses: int,
    max_combo: int,
    map_max_combo: int,
    difficulty: int,
    mods: str,
) -> int:
    hits = n300 + n100 + n50
    if hits == 0:
        return 0
    objects = hits + misses
    base = 300 * n300 + 100 * n100 + 50 * n50
    avg_hit = base / hits
    # max_combo counts slider ticks; convert to object combo before splitting into runs.
    longest = min(hits, round(max_combo * objects / max(map_max_combo, 1)))
    segments = [longest]
    rest = hits - longest
    if rest > 0:
        # No other run can be longer than the max combo.
        pieces = max(1, misses, math.ceil(rest / max(longest, 1)))
        segments += [rest // pieces + (1 if i < rest % pieces else 0) for i in range(pieces)]
    bonus = avg_hit * _combo_sum(segments) * difficulty * mod_multiplier(mods) / 25
    return round(base + bonus)


def counts_from_accuracy(n_objects: int, accuracy: float, misses: int) -> tuple[int, int, int]:
    """Plausible (n300, n100, n50) for an accuracy, when only accuracy and misses are known."""
    hits = max(0, n_objects - misses)
    lost = max(0.0, (100 - accuracy) / 100 * 300 * n_objects - 300 * misses)
    n100 = max(0, min(hits, round(lost * 0.85 / 200)))
    n50 = max(0, min(hits - n100, round(lost * 0.15 / 250)))
    return hits - n100 - n50, n100, n50


def stable_grade(accuracy: float, misses: int, mods: str, n_objects: int) -> str:
    """osu!stable grades (XH/X/SH/S/A/B/C/D) from accuracy and misses; hit counts are reconstructed."""
    n300, n100, n50 = counts_from_accuracy(max(1, n_objects), accuracy, misses)
    total = max(1, n300 + n100 + n50 + misses)
    r300, r50 = n300 / total, n50 / total
    silver = any(m in (mods or "") for m in ("HD", "FL"))
    if misses == 0 and n100 == 0 and n50 == 0:
        return "XH" if silver else "X"
    if r300 > 0.9 and r50 < 0.01 and misses == 0:
        return "SH" if silver else "S"
    if (r300 > 0.8 and misses == 0) or r300 > 0.9:
        return "A"
    if (r300 > 0.7 and misses == 0) or r300 > 0.8:
        return "B"
    return "C" if r300 > 0.6 else "D"
