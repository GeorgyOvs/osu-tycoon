"""The interactive ban/pick draft of the user's tournament matches.

The match is a `match.MatchState` saved in `MatchDraft.state` between requests. The opponent decides at their
own turn and the user sees it before choosing, so nobody ever picks what is already taken. Every random draw is
seeded by (match id, step), so a saved draft replays identically after a reload.

Order: the better seed bans first, the other side picks first; two bans per side while the pool allows
(2*first_to-2 playable maps must remain); each pick is played at once; the tiebreaker is automatic.

Hand mode: the user plays the chosen maps for real in the tycoon client. The draft then pauses before each map,
the client plays it (slot mods, NoFail allowed), and `on_hand_play` resolves the map with that real result while
the other side is simulated as usual. Any single map can still be left to the simulation.
"""

import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import match
from app.models import Match, MatchDraft, Player, Tournament
from app.services import tournaments
from app.services.tournaments import News, TournamentError

BANS_PER_SIDE = 2
WARMUP_FATIGUE = 3.0
WARMUP_FORM = 0.35
WARMUP_NERVES = 1.04


def _rng_for(player: Player, m: Match):
    return lambda tag: random.Random(f"{player.seed}:draft:{m.id}:{tag}")


def _draft_row(db: Session, m: Match) -> MatchDraft | None:
    return db.scalar(select(MatchDraft).where(MatchDraft.match_id == m.id))


class _Ctx:
    """Rebuilt on every request from the database; only the MatchState snapshot is stored."""

    def __init__(self, db: Session, player: Player, t: Tournament, m: Match, state: dict | None) -> None:
        self.hand = bool(state and state.get("hand"))
        self.hand_results: dict[str, dict] = dict((state or {}).get("hand_results") or {})
        pool, a, b, side_a, side_b, advantage, play_map = tournaments.user_match_context(db, player, t, m,
                                                                                          self.hand_results)
        self.a, self.b, self.side_a, self.side_b, self.pool = a, b, side_a, side_b, pool
        self.user_side = "a" if a.includes_user else "b"
        self.opponent = b if self.user_side == "a" else a
        self.me = a if self.user_side == "a" else b
        self.warmup = bool(state and state.get("warmup"))
        if self.warmup:  # a warmed-up user: a little extra form and nerve for this match only
            for c in (side_a if self.user_side == "a" else side_b):
                if c.kind == "user":
                    c.day.form += WARMUP_FORM
                    for key in ("nerve_resistance", "clutch"):
                        c.skills[key] = min(115.0, c.skills[key] * WARMUP_NERVES)
            advantage, play_map = tournaments.map_simulator(db, player, side_a, side_b, seed_key=f"{m.id}",
                                                            opponent_country=self.opponent.country,
                                                            hand_results=self.hand_results)
        self.advantage, self.play_map = advantage, play_map
        lower = self.a if self.a.seed < self.b.seed else self.b if self.b.seed < self.a.seed else None
        coin = random.Random(f"{player.seed}:draft:{m.id}:first").choice("ab")
        self.first_ban = ("a" if lower is self.a else "b") if lower is not None else coin
        self.first_pick = "b" if self.first_ban == "a" else "a"
        self.prefs = (state or {}).get("prefs") or {}
        self.machine = match.MatchState(
            pool, m.first_to, advantage, BANS_PER_SIDE, rng_for=_rng_for(player, m), prefs=self.prefs or None,
            first_ban=self.first_ban, first_pick=self.first_pick)
        if state and state.get("machine"):
            self.machine.restore(state["machine"])


def _save(db: Session, player: Player, m: Match, ctx: _Ctx, extra: dict) -> MatchDraft:
    row = _draft_row(db, m)
    state = {"machine": ctx.machine.snapshot(), "warmup": ctx.warmup, "prefs": ctx.prefs, "hand": ctx.hand,
             "hand_results": ctx.hand_results, **extra}
    if row is None:
        row = MatchDraft(player_id=player.id, match_id=m.id, state=state)
        db.add(row)
    else:
        row.state = state
    db.flush()
    return row


def _advance(db: Session, player: Player, t: Tournament, m: Match, ctx: _Ctx, row_extra: dict,
             humans: set[str]) -> tuple[bool, list[News]]:
    """Run opponent turns and map plays until the user has to decide or the match is over."""
    finished = ctx.machine.run(ctx.play_map, humans, stop_at_play=ctx.hand and bool(humans))
    news: list[News] = []
    if finished:
        news = tournaments.finish_user_match(db, player, t, m, ctx.machine.outcome(), ctx.a, ctx.b,
                                             ctx.side_a, ctx.side_b)
    row = _save(db, player, m, ctx, row_extra)
    row.finished = finished
    return finished, news


def _load(db: Session, player: Player, t: Tournament, m: Match) -> tuple[_Ctx, dict, MatchDraft | None]:
    row = _draft_row(db, m)
    if row is None or not row.finished:
        tournaments.assert_playable(db, player, t, m)
    return _Ctx(db, player, t, m, row.state if row else None), (row.state if row else {}), row


def start_or_get(db: Session, player: Player, t: Tournament, m: Match) -> tuple[dict, list[News]]:
    ctx, state, row = _load(db, player, t, m)
    news: list[News] = []
    if row is None:
        row = _save(db, player, m, ctx, {})
    if not row.finished:
        _, news = _advance(db, player, t, m, ctx, {}, {ctx.user_side})
    return view(db, player, t, m, ctx), news


def act(db: Session, player: Player, t: Tournament, m: Match, slot: str) -> tuple[dict, list[News]]:
    ctx, state, row = _load(db, player, t, m)
    if row is None or row.finished:
        raise TournamentError(409, "open the draft first" if row is None else "this draft is already finished")
    kind, side = ctx.machine.actor()
    if kind not in ("ban", "pick") or side != ctx.user_side:
        raise TournamentError(409, "it is not your turn")
    try:
        ctx.machine.choose(slot)
    except ValueError as e:
        raise TournamentError(422, str(e)) from e
    _, news = _advance(db, player, t, m, ctx, {}, {ctx.user_side})
    return view(db, player, t, m, ctx), news


def auto_finish(db: Session, player: Player, t: Tournament, m: Match,
                strategy: dict[str, list[str]] | None = None) -> tuple[match.MatchOutcome, list[News]]:
    """Let the AI decide the rest of the user's side, using the user's own priority lists first."""
    row = _draft_row(db, m)
    state = dict(row.state) if row else {}
    if strategy:
        user_side = "a" if tournaments._entry(t, m.entry_a).includes_user else "b"
        state["prefs"] = {user_side: {"bans": list(strategy.get("bans", [])), "picks": list(strategy.get("picks", []))}}
    if row is None or not row.finished:
        tournaments.assert_playable(db, player, t, m)
    ctx = _Ctx(db, player, t, m, state)
    if row is not None and row.finished:
        raise TournamentError(409, "this match has already been played")
    _, news = _advance(db, player, t, m, ctx, {}, set())
    return ctx.machine.outcome(), news


def auto(db: Session, player: Player, t: Tournament, m: Match, strategy: dict | None = None) -> tuple[dict, list[News]]:
    outcome, news = auto_finish(db, player, t, m, strategy)
    ctx = _Ctx(db, player, t, m, _draft_row(db, m).state)
    return view(db, player, t, m, ctx), news


def set_hand(db: Session, player: Player, t: Tournament, m: Match, on: bool) -> tuple[dict, list[News]]:
    """Switch hand mode: play the chosen maps yourself in the client, or let the simulation play them."""
    ctx, state, row = _load(db, player, t, m)
    if row is None:
        row = _save(db, player, m, ctx, {})
    if row.finished:
        raise TournamentError(409, "the match is over")
    ctx.hand = on
    _, news = _advance(db, player, t, m, ctx, {}, {ctx.user_side})
    return view(db, player, t, m, ctx), news


def simulate_pending(db: Session, player: Player, t: Tournament, m: Match) -> tuple[dict, list[News]]:
    """Leave the map waiting to be played by hand to the simulation, then carry on."""
    ctx, state, row = _load(db, player, t, m)
    if row is None or row.finished or ctx.machine.actor()[0] != "play":
        raise TournamentError(409, "no map is waiting to be played")
    ctx.machine.play(ctx.play_map)
    _, news = _advance(db, player, t, m, ctx, {}, {ctx.user_side})
    return view(db, player, t, m, ctx), news


def _mod_pairs(mods: str) -> set[str]:
    pairs = {mods[i:i + 2] for i in range(0, len(mods), 2)}
    if "NC" in pairs:
        pairs = (pairs - {"NC"}) | {"DT"}
    return pairs - {"NF"}


def awaiting_map(db: Session, player: Player) -> tuple[Tournament, Match, match.Slot] | None:
    """The map of the user's match that is waiting to be played by hand, if any."""
    pending = tournaments.pending_user_match(db, player)
    if pending is None:
        return None
    t, m = pending
    row = _draft_row(db, m)
    if row is None or row.finished or not (row.state or {}).get("hand"):
        return None
    machine_state = (row.state or {}).get("machine") or {}
    if not machine_state.get("pending"):
        return None
    slot_name = machine_state["pending"][0]
    slot = next((s for s in tournaments.pool_for(t, m.week) if s.slot == slot_name), None)
    return (t, m, slot) if slot is not None else None


def on_hand_play(db: Session, player: Player, *, beatmap_id: int, mods: str, accuracy: float, max_combo: int,
                 misses: int, status: str, completion: float) -> tuple[str | None, list[News]]:
    """A play arrived from the client: if it is the match map being waited for, it decides that map.
    Returns a note for the play (or None when it has nothing to do with a match) and any news."""
    waiting = awaiting_map(db, player)
    if waiting is None or status == "quit":
        return None, []
    t, m, slot = waiting
    if slot.beatmap_id != beatmap_id:
        return None, []
    if _mod_pairs(mods) != _mod_pairs(slot.mods):
        return f"match map not counted: play it with {slot.mods or 'no mods'} (NoFail allowed)", []
    ctx, state, row = _load(db, player, t, m)
    ctx.hand_results[slot.slot] = {"accuracy": accuracy, "max_combo": max_combo, "misses": misses,
                                   "passed": status == "passed", "completion": completion}
    ctx = _Ctx(db, player, t, m, {**(row.state or {}), "hand_results": ctx.hand_results})  # re-wire the play callback
    result = ctx.machine.play(ctx.play_map)
    _, news = _advance(db, player, t, m, ctx, {}, {ctx.user_side})
    side = ctx.user_side
    won = result.winner == side
    mine, theirs = (result.score_a, result.score_b) if side == "a" else (result.score_b, result.score_a)
    return f"match map {slot.slot}: {'won' if won else 'lost'} {mine:,} to {theirs:,}", news


def warmup(db: Session, player: Player, t: Tournament, m: Match) -> dict:
    ctx, state, row = _load(db, player, t, m)
    if row is None:
        row = _save(db, player, m, ctx, {})
    if row.finished:
        raise TournamentError(409, "the match is over")
    if ctx.warmup:
        raise TournamentError(409, "you have already warmed up for this match")
    if ctx.machine.maps:
        raise TournamentError(409, "the warm-up is before the first map")
    row.state = {**row.state, "warmup": True}
    player.fatigue = min(100.0, player.fatigue + WARMUP_FATIGUE)
    db.flush()
    return view(db, player, t, m, _Ctx(db, player, t, m, row.state))


def view(db: Session, player: Player, t: Tournament, m: Match, ctx: _Ctx) -> dict:
    row = _draft_row(db, m)
    mach = ctx.machine
    kind, side = mach.actor() if not mach.done else ("done", None)
    mine = kind in ("ban", "pick") and side == ctx.user_side
    banned_by = {s: side_ for side_, slots in mach.bans.items() for s in slots}
    picked = {p["slot"]: p["by"] for p in mach.picks}
    played = {r.slot: r for r in mach.maps}
    legal = [s.slot for s in mach.legal_slots()] if mine else []
    slots = []
    for s in ctx.pool:
        if s.slot in played:
            r = played[s.slot]
            state_name, by, extra = "played", r.picked_by, {"score_a": r.score_a, "score_b": r.score_b, "winner": r.winner}
        elif s.slot in banned_by:
            state_name, by, extra = "banned", banned_by[s.slot], {}
        elif s.slot in picked:
            state_name, by, extra = "picked", picked[s.slot], {}
        else:
            state_name, by, extra = "open", None, {}
        slots.append({"slot": s.slot, "family": s.slot[:2], "mods": s.mods or "NM",
                      "stars": s.stars, "title": s.title, "beatmap_id": s.beatmap_id, "state": state_name, "by": by,
                      "legal": s.slot in legal, **extra})
    names = {"a": ctx.a.name, "b": ctx.b.name}
    finished = bool(row and row.finished) or mach.done
    return {
        "match_id": m.id, "tournament_id": t.id, "stage": m.stage, "first_to": m.first_to, "finished": finished,
        "user_side": ctx.user_side, "names": names, "seeds": {"a": ctx.a.seed, "b": ctx.b.seed},
        "score": {"a": mach.score_a, "b": mach.score_b},
        "turn": {"kind": kind, "side": side, "mine": mine},
        "legal": legal, "slots": slots, "bans": mach.bans,
        "first_ban": ctx.first_ban, "first_pick": ctx.first_pick, "bans_per_side": BANS_PER_SIDE,
        "log": _log_lines(mach, names, ctx.user_side),
        "maps": [{"slot": r.slot, "picked_by": r.picked_by, "score_a": r.score_a, "score_b": r.score_b, **r.detail}
                 for r in mach.maps],
        "warmup": {"used": ctx.warmup, "available": not ctx.warmup and not mach.maps and not finished},
        "hand": ctx.hand,
        "awaiting": _awaiting(mach) if ctx.hand and not finished else None,
    }


def _awaiting(mach: match.MatchState) -> dict | None:
    if mach.actor()[0] != "play" or mach.pending is None:
        return None
    slot, picked_by = mach.pending
    return {"slot": slot.slot, "beatmap_id": slot.beatmap_id, "title": slot.title, "mods": slot.mods,
            "stars": slot.stars, "picked_by": picked_by}


def _log_lines(mach: match.MatchState, names: dict[str, str], user_side: str) -> list[dict]:
    out = []
    for e in mach.log:
        who = names.get(e["side"], "") if e.get("side") in ("a", "b") else ""
        out.append({**e, "who": who, "mine": e.get("side") == user_side})
    return out
