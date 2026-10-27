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
    decided: str | None = None  # set when the scores were exactly equal

    @property
    def winner(self) -> str:
        if self.decided:
            return self.decided
        return "a" if self.score_a > self.score_b else "b"


def break_tie(detail: dict, advantage: float, rng: random.Random) -> tuple[str, str]:
    """Equal scores on a map: higher accuracy wins, then fewer misses, then a sudden-death replay that
    favours the stronger side only a little. Never 'side a by default'."""
    players = detail.get("players") or []
    for key, better in (("accuracy", max), ("misses", min)):
        totals = {side: sum(p[key] for p in players if p.get("side") == side) for side in ("a", "b")}
        if players and totals["a"] != totals["b"]:
            wins_a = (totals["a"] > totals["b"]) if better is max else (totals["a"] < totals["b"])
            return ("a" if wins_a else "b"), key
    p_a = 0.5 + max(-0.2, min(0.2, advantage / 50))
    return ("a" if rng.random() < p_a else "b"), "sudden_death"


@dataclass
class MatchOutcome:
    score_a: int
    score_b: int
    maps: list[MapResult]
    bans: dict[str, list[str]]

    @property
    def winner(self) -> str:
        return "a" if self.score_a > self.score_b else "b"


PlayFn = Callable[[Slot, bool], tuple[int, int, dict]]  # (slot, decisive) -> scores, detail


def _other(side: str) -> str:
    return "b" if side == "a" else "a"


class MatchState:
    """A match as a state machine: bans, alternating picks (each pick is played at once), tiebreaker at match
    point. `run_match` drives it to the end; the interactive draft pauses it whenever a human has to choose.

    Randomness: with a shared `rng` the draw order is exactly the classic one; with `rng_for(tag)` every draw
    gets its own seeded generator, so the state can be saved between requests and still replay identically."""

    def __init__(
        self,
        pool: list[Slot],
        first_to: int,
        advantage: Callable[[Slot], float],  # > 0 favours side a
        bans_per_side: int = 1,
        rng: random.Random | None = None,
        rng_for: Callable[[str], random.Random] | None = None,
        prefs: dict[str, dict[str, list[str]]] | None = None,
        first_ban: str = "a",
        first_pick: str | None = None,
    ) -> None:
        self.pool = pool
        self.first_to = first_to
        self.advantage = advantage
        self.rng = rng
        self.rng_for = rng_for
        self.prefs = prefs or {}
        self.tiebreaker = next((s for s in pool if s.slot == "TB"), None)
        self.open_slots = [s for s in pool if s.slot != "TB"]
        self.bans: dict[str, list[str]] = {"a": [], "b": []}
        self.ban_queue = [side for _ in range(bans_per_side) for side in (first_ban, _other(first_ban))]
        self.ban_index = 0
        self.picker: str | None = first_pick
        self.picks: list[dict] = []
        self.score_a = self.score_b = 0
        self.maps: list[MapResult] = []
        self.pending: tuple[Slot, str] | None = None
        self.log: list[dict] = []

    # -- randomness ---------------------------------------------------------------------------
    def _rand(self, tag: str) -> random.Random:
        return self.rng_for(tag) if self.rng_for else self.rng  # type: ignore[return-value]

    # -- what happens next --------------------------------------------------------------------
    @property
    def done(self) -> bool:
        return self.score_a >= self.first_to or self.score_b >= self.first_to

    def _bans_over(self) -> bool:
        # A match can last 2*first_to-1 maps and the last one may be the tiebreaker, so the bans may only
        # take the pool down to 2*first_to-2 playable maps.
        return self.ban_index >= len(self.ban_queue) or len(self.open_slots) <= 2 * self.first_to - 2

    def actor(self) -> tuple[str, str | None]:
        """('ban'|'pick', side), ('tb', None), ('play', None) for a chosen map waiting to be played, or ('done', None)."""
        if self.done:
            return "done", None
        if self.pending is not None:
            return "play", None
        if not self._bans_over():
            return "ban", self.ban_queue[self.ban_index]
        self.ban_index = len(self.ban_queue)
        if self.picker is None:
            self.picker = self._rand("coin").choice("ab")
        if self.score_a == self.score_b == self.first_to - 1 and self.tiebreaker is not None:
            return "tb", None
        return "pick", self.picker

    def legal_slots(self) -> list[Slot]:
        kind, _ = self.actor()
        if kind not in ("ban", "pick"):
            return []
        if kind == "pick" and not self.open_slots:  # tiny pools: allow replays rather than stalling
            return [s for s in self.pool if s.slot != "TB"]
        return list(self.open_slots)

    def _preferred(self, side: str, kind: str, options: list[Slot]) -> Slot | None:
        names = {s.slot: s for s in options}
        return next((names[n] for n in self.prefs.get(side, {}).get(kind + "s", []) if n in names), None)

    def ai_choice(self, kind: str, side: str, options: list[Slot]) -> Slot:
        """Own priorities first, then the classic AI: ban what the opponent would love to pick, pick the slot
        where the own side's edge is largest."""
        chosen = self._preferred(side, kind, options)
        if chosen:
            return chosen
        if kind == "ban":
            return min(options, key=self.advantage) if side == "a" else max(options, key=self.advantage)
        return max(options, key=self.advantage) if side == "a" else min(options, key=self.advantage)

    # -- acting -------------------------------------------------------------------------------
    def choose(self, slot_name: str | None = None) -> None:
        """Make the current ban/pick (a given slot, or the AI/priority choice); a tiebreaker is just announced."""
        kind, side = self.actor()
        if kind == "tb":
            assert self.tiebreaker is not None
            self.pending = (self.tiebreaker, "tb")
            self.log.append({"kind": "tb", "side": None, "slot": "TB"})
            return
        if kind not in ("ban", "pick"):
            raise ValueError(f"nothing to choose right now ({kind})")
        options = self.legal_slots()
        if slot_name is None:
            slot = self.ai_choice(kind, side, options)  # type: ignore[arg-type]
        else:
            slot = next((o for o in options if o.slot == slot_name), None)  # type: ignore[assignment]
            if slot is None:
                raise ValueError(f"{slot_name} is not available")
        if kind == "pick" and slot not in self.open_slots:  # the replay fallback of tiny pools
            self.open_slots = [s for s in self.pool if s.slot != "TB"]
        self.open_slots.remove(slot)
        if kind == "ban":
            self.bans[side].append(slot.slot)  # type: ignore[index]
            self.ban_index += 1
        else:
            self.picks.append({"slot": slot.slot, "by": side})
            self.pending = (slot, side)  # type: ignore[assignment]
            self.picker = _other(side)  # type: ignore[arg-type]
        self.log.append({"kind": kind, "side": side, "slot": slot.slot})

    def play(self, play_fn: PlayFn) -> MapResult:
        assert self.pending is not None, "no map has been chosen"
        slot, picked_by = self.pending
        decisive = self.score_a == self.first_to - 1 or self.score_b == self.first_to - 1
        a, b, detail = play_fn(slot, decisive)
        decided = None
        if a == b:
            decided, how = break_tie(detail, self.advantage(slot), self._rand(f"tie{len(self.maps)}"))
            detail = {**detail, "tie": how}
        winner = decided or ("a" if a > b else "b")
        result = MapResult(slot.slot, picked_by, a, b, {**detail, "winner": winner}, decided)
        self.maps.append(result)
        if result.winner == "a":
            self.score_a += 1
        else:
            self.score_b += 1
        self.pending = None
        self.log.append({"kind": "result", "side": result.winner, "slot": slot.slot, "score_a": a, "score_b": b})
        return result

    def run(self, play_fn: PlayFn, humans: frozenset[str] | set[str] = frozenset(), stop_at_play: bool = False) -> bool:
        """Advance until the match ends (True) or a human side has to ban/pick (False). With `stop_at_play` it also
        pauses before each chosen map is played, for maps the user plays by hand in the client."""
        while True:
            kind, side = self.actor()
            if kind == "done":
                return True
            if kind in ("ban", "pick") and side in humans:
                return False
            if kind == "play" and stop_at_play:
                return False
            if kind == "play":
                self.play(play_fn)
            else:
                self.choose()

    def outcome(self) -> "MatchOutcome":
        return MatchOutcome(self.score_a, self.score_b, self.maps, self.bans)

    # -- persistence --------------------------------------------------------------------------
    def snapshot(self) -> dict:
        return {
            "open": [s.slot for s in self.open_slots], "bans": self.bans, "ban_index": self.ban_index,
            "picker": self.picker, "picks": self.picks, "score_a": self.score_a, "score_b": self.score_b,
            "maps": [{"slot": m.slot, "picked_by": m.picked_by, "score_a": m.score_a, "score_b": m.score_b,
                      "detail": m.detail, "decided": m.decided} for m in self.maps],
            "pending": [self.pending[0].slot, self.pending[1]] if self.pending else None, "log": self.log,
        }

    def restore(self, data: dict) -> "MatchState":
        by_name = {s.slot: s for s in self.pool}
        self.open_slots = [by_name[n] for n in data["open"] if n in by_name]
        self.bans = {"a": list(data["bans"]["a"]), "b": list(data["bans"]["b"])}
        self.ban_index, self.picker, self.picks = data["ban_index"], data["picker"], list(data["picks"])
        self.score_a, self.score_b = data["score_a"], data["score_b"]
        self.maps = [MapResult(m["slot"], m["picked_by"], m["score_a"], m["score_b"], m["detail"], m["decided"])
                     for m in data["maps"]]
        self.pending = (by_name[data["pending"][0]], data["pending"][1]) if data.get("pending") else None
        self.log = list(data.get("log", []))
        return self


def run_match(
    pool: list[Slot],
    first_to: int,
    advantage: Callable[[Slot], float],  # > 0 favours side a
    play: PlayFn,
    rng: random.Random,
    bans_per_side: int = 1,
    prefs: dict[str, dict[str, list[str]]] | None = None,
) -> MatchOutcome:
    """`prefs` = {"a": {"bans": [...], "picks": [...]}}: a side's own priorities (slot names), tried
    in order before falling back to the AI choice."""
    state = MatchState(pool, first_to, advantage, bans_per_side, rng=rng, prefs=prefs)
    state.run(play)
    return state.outcome()


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
