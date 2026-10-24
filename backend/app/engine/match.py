"""Tournament match flow: pool layout, bans, alternating picks, tiebreaker.

The flow is shared by NPC-vs-NPC matches (resolved from composites in microseconds) and the
user's matches (every map simulated note by note); only the `play` callback differs.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from app.engine import world

# Star bump per tournament week: group stage -> grand finals (plan: OWC ~6.6* -> ~7.6*+).
STAGE_DELTA = [0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 1.0]
SMALL_POOL = ["NM1", "NM2", "NM3", "NM4", "HD1", "HD2", "HR1", "HR2", "DT1", "DT2", "DT3", "TB"]
BIG_POOL = ["NM1", "NM2", "NM3", "NM4", "NM5", "HD1", "HD2", "HD3", "HR1", "HR2", "HR3",
            "DT1", "DT2", "DT3", "DT4", "TB"]
SLOT_MODS = {"NM": "", "HD": "HD", "HR": "HR", "DT": "DT", "TB": ""}

# Star ratings of tournament pools rose over the years.
_STAR_ERA = [(2008.0, 0.65), (2010.0, 0.72), (2012.0, 0.8), (2014.0, 0.88), (2016.0, 0.93), (2018.0, 0.97),
             (2020.0, 1.0), (2023.0, 1.03)]


def era_star_factor(on: date) -> float:
    return world._interp(_STAR_ERA, world._year(on))


@dataclass
class Slot:
    slot: str
    stars: float  # target (post-mod) star rating
    beatmap_id: int | None = None
    title: str = ""

    @property
    def mods(self) -> str:
        return SLOT_MODS[world.slot_family(self.slot)[:2]]


def pool_layout(week: int, base_stars: float) -> list[Slot]:
    delta = STAGE_DELTA[min(week - 1, len(STAGE_DELTA) - 1)]
    names = SMALL_POOL if week <= 2 else BIG_POOL
    slots = []
    for name in names:
        bump = 0.25 if name == "TB" else 0.0
        slots.append(Slot(name, round(base_stars + delta + bump, 2)))
    return slots


@dataclass
class MapResult:
    slot: str
    picked_by: str  # a | b | tb
    score_a: int
    score_b: int
    detail: dict = field(default_factory=dict)

    @property
    def winner(self) -> str:
        return "a" if self.score_a >= self.score_b else "b"


@dataclass
class MatchOutcome:
    score_a: int
    score_b: int
    maps: list[MapResult]
    bans: dict[str, list[str]]

    @property
    def winner(self) -> str:
        return "a" if self.score_a > self.score_b else "b"


def run_match(
    pool: list[Slot],
    first_to: int,
    advantage: Callable[[Slot], float],  # > 0 favours side a
    play: Callable[[Slot, bool], tuple[int, int, dict]],  # (slot, decisive) -> scores, detail
    rng: random.Random,
    bans_per_side: int = 1,
    prefs: dict[str, dict[str, list[str]]] | None = None,
) -> MatchOutcome:
    """`prefs` = {"a": {"bans": [...], "picks": [...]}}: a side's own priorities (slot names), tried
    in order before falling back to the AI choice."""
    prefs = prefs or {}

    def preferred(side: str, kind: str, options: list[Slot]) -> Slot | None:
        names = {s.slot: s for s in options}
        return next((names[n] for n in prefs.get(side, {}).get(kind, []) if n in names), None)

    tiebreaker = next((s for s in pool if s.slot == "TB"), None)
    open_slots = [s for s in pool if s.slot != "TB"]
    bans: dict[str, list[str]] = {"a": [], "b": []}
    for _ in range(bans_per_side):
        for side in ("a", "b"):
            if len(open_slots) <= 2 * first_to - 1:
                break
            # Ban what the opponent would love to pick (unless the side has its own plan).
            target = preferred(side, "bans", open_slots) or (
                min(open_slots, key=advantage) if side == "a" else max(open_slots, key=advantage))
            bans[side].append(target.slot)
            open_slots.remove(target)

    score_a = score_b = 0
    maps: list[MapResult] = []
    picker = rng.choice("ab")
    while score_a < first_to and score_b < first_to:
        decisive = score_a == first_to - 1 or score_b == first_to - 1
        if score_a == score_b == first_to - 1 and tiebreaker is not None:
            slot, picked_by = tiebreaker, "tb"
        else:
            if not open_slots:  # tiny pools: allow replays rather than stalling
                open_slots = [s for s in pool if s.slot != "TB"]
            slot = preferred(picker, "picks", open_slots) or (
                max(open_slots, key=advantage) if picker == "a" else min(open_slots, key=advantage))
            open_slots.remove(slot)
            picked_by = picker
            picker = "b" if picker == "a" else "a"
        a, b, detail = play(slot, decisive)
        result = MapResult(slot.slot, picked_by, a, b, detail)
        maps.append(result)
        if result.winner == "a":
            score_a += 1
        else:
            score_b += 1
    return MatchOutcome(score_a, score_b, maps, bans)


def light_match(
    comps_a: dict[str, float],
    comps_b: dict[str, float],
    form_a: float,
    form_b: float,
    pool: list[Slot],
    first_to: int,
    rng: random.Random,
) -> MatchOutcome:
    """NPC vs NPC: composites against slot stars, with noise and nerves on decisive maps."""

    def advantage(s: Slot) -> float:
        return world.slot_strength(comps_a, s.slot) - world.slot_strength(comps_b, s.slot)

    def play(s: Slot, decisive: bool) -> tuple[int, int, dict]:
        pa = world.map_performance(comps_a, s.slot, s.stars, form_a, rng)
        pb = world.map_performance(comps_b, s.slot, s.stars, form_b, rng)
        if decisive:
            pa *= 1 + (comps_a["mentality"] - 50) / 1500
            pb *= 1 + (comps_b["mentality"] - 50) / 1500
        return round(pa * 500_000), round(pb * 500_000), {}

    return run_match(pool, first_to, advantage, play, rng)
