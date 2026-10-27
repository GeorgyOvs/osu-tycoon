"""Watch a played match map in the tycoon client, everyone at once like lazer's multiplayer spectator.

Tournament matches and 1v1 duels keep, per map, every object's time and each player's result and timing error
(tournaments.trace_json), so the client can rebuild everyone's play exactly as the simulation decided it. Maps
played by hand only have the totals; those are reconstructed with the same counts and max combo.
"""
import random
import zlib
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import playstyle, scoring
from app.models import Duel, Match, Npc, Player, Tournament
from app.services import osu_api

RESULTS = {"3": "great", "1": "ok", "5": "meh", "0": "miss"}
SLIDER_RESULTS = {"b": "sliderbreak", "e": "sliderend"}


class WatchError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _source(db: Session, player: Player, kind: str, source_id: int) -> dict:
    if kind == "match":
        m = db.get(Match, source_id)
        t = db.get(Tournament, m.tournament_id) if m else None
        if m is None or t is None or t.player_id != player.id or m.winner is None:
            raise WatchError(404, "match not found or not played yet")
        entries = {e.id: e for e in t.entries}
        a, b = entries.get(m.entry_a), entries.get(m.entry_b)
        if not any("forfeit" in x for x in (m.maps or [])) and not any("slot" in x for x in (m.maps or [])):
            m.maps = _rebuild_light_maps(t, m)  # an NPC match from before maps were kept
        return {"title": t.name, "stage": m.stage, "date": m.played_on, "first_to": m.first_to,
                "names": {"a": a.name if a else "?", "b": b.name if b else "?"},
                "countries": {"a": a.country if a else "XX", "b": b.country if b else "XX"},
                "maps": [x for x in (m.maps or []) if "slot" in x],
                "row": m, "tournament": t, "entries": (a, b),
                "has_user": bool((a and a.includes_user) or (b and b.includes_user))}
    if kind == "duel":
        d = db.get(Duel, source_id)
        if d is None or d.player_id != player.id or d.status != "played":
            raise WatchError(404, "duel not found or not played yet")
        npc = db.get(Npc, d.npc_id)
        return {"title": "1v1", "stage": "1v1", "date": d.date, "first_to": (d.best_of + 1) // 2,
                "names": {"a": player.name, "b": npc.name if npc else "?"},
                "countries": {"a": player.country, "b": npc.country if npc else "XX"},
                "maps": [x for x in (d.maps or []) if "slot" in x]}
    raise WatchError(404, f"unknown kind {kind}")


MAX_RESEEDS = 40


def _rebuild_light_maps(t: Tournament, m: Match) -> list[dict]:
    """Only the final score is known: lay out a plausible sequence of maps that ends exactly like that
    (alternating picks through the week's pool, the tiebreaker when it went the distance)."""
    from app.services import tournaments

    pool = tournaments.pool_for(t, m.week)
    winner = "a" if m.winner == m.entry_a else "b"
    loser = "b" if winner == "a" else "a"
    wins = {winner: max(m.score_a, m.score_b), loser: min(m.score_a, m.score_b)}
    order: list[str] = []
    ww, lw = wins[winner], wins[loser]
    while ww > 1 or lw > 0:  # alternate while the loser still has maps to take; the winner closes it out
        if lw > 0 and (len(order) % 2 == 1 or ww <= 1):
            order.append(loser)
            lw -= 1
        else:
            order.append(winner)
            ww -= 1
    order.append(winner)
    playable = [s for s in pool if s.slot != "TB"]
    tiebreaker = next((s for s in pool if s.slot == "TB"), None)
    maps = []
    for i, side in enumerate(order):
        last_and_tied = i == len(order) - 1 and wins[loser] == m.first_to - 1 and tiebreaker is not None
        s = tiebreaker if last_and_tied else playable[i % max(1, len(playable))]
        maps.append({"slot": s.slot, "picked_by": "b" if i % 2 else "a", "winner": side, "beatmap_id": s.beatmap_id,
                     "title": s.title, "mods": s.mods or "NM", "stars": s.stars, "light": True})
    return maps + [{"bans": {"a": [], "b": []}}]


def _simulate_light_map(db: Session, player: Player, src: dict, index: int) -> dict:
    """A map of an NPC match was only decided in summary; play it note by note now, re-rolling until the result
    is the recorded one, and keep it so it replays the same every time."""
    from app.engine import match
    from app.services import tournaments

    m: Match = src["row"]
    stored = src["maps"][index]
    a, b = src["entries"]
    side_a, side_b = tournaments._competitors(db, player, a), tournaments._competitors(db, player, b)
    before = {"a": sum(1 for x in src["maps"][:index] if x.get("winner") == "a"),
              "b": sum(1 for x in src["maps"][:index] if x.get("winner") == "b")}
    decisive = max(before.values()) == m.first_to - 1
    slot = match.Slot(stored["slot"], stored.get("stars", 0), stored.get("beatmap_id"), stored.get("title", ""))
    best = None
    for k in range(MAX_RESEEDS):
        _, play_map = tournaments.map_simulator(db, player, side_a, side_b, seed_key=f"watch:{m.id}:{index}:{k}")
        score_a, score_b, detail = play_map(slot, decisive)
        best = (score_a, score_b, detail)
        if ("a" if score_a > score_b else "b") == stored["winner"]:
            break
    score_a, score_b, detail = best
    full = {**stored, **detail, "score_a": score_a, "score_b": score_b, "winner": stored["winner"], "light": False}
    all_maps = list(m.maps or [])
    slot_maps = [i for i, x in enumerate(all_maps) if "slot" in x]
    all_maps[slot_maps[index]] = full
    m.maps = all_maps
    db.flush()
    return full


def _with_style(db: Session, player: Player, p: dict) -> dict:
    """Knobs of maps played before playstyles were kept get the player's style now (with average skills for the
    flow, the only part that depends on them)."""
    knobs = dict(p.get("knobs") or {})
    if "flow" in knobs:
        return knobs
    average = {k: 50.0 for k in A.SUBSTATS}
    if p.get("kind") == "user":
        return playstyle.of_player(player, average) | knobs
    npc = db.get(Npc, p["npc_id"]) if p.get("npc_id") else None
    seed = npc.seed if npc else zlib.crc32(str(p.get("name", "?")).encode())
    return playstyle.describe(seed, average, year=player.in_game_date.year) | knobs


def listing(db: Session, player: Player, limit: int = 12) -> list[dict]:
    """The career's played matches and duels, newest first, with whether their maps can be watched."""
    out = []
    matches = db.execute(select(Match, Tournament).join(Tournament, Tournament.id == Match.tournament_id)
                         .where(Tournament.player_id == player.id, Match.winner.is_not(None))
                         .order_by(Match.played_on.desc(), Match.id.desc()).limit(200))
    for m, t in matches:
        entries = {e.id: e for e in t.entries}
        a, b = entries.get(m.entry_a), entries.get(m.entry_b)
        if not ((a and a.includes_user) or (b and b.includes_user)):
            continue
        mine, theirs = (a, b) if a and a.includes_user else (b, a)
        my_score, their_score = (m.score_a, m.score_b) if mine is a else (m.score_b, m.score_a)
        maps = [x for x in (m.maps or []) if "slot" in x]
        out.append({"kind": "match", "id": m.id, "title": t.name, "stage": m.stage,
                    "opponent": theirs.name if theirs else "?", "my_score": my_score, "their_score": their_score,
                    "date": m.played_on.isoformat() if m.played_on else None, "maps": len(maps),
                    "watchable": any("times" in x for x in maps)})
        if len(out) >= limit:
            break
    for d in db.scalars(select(Duel).where(Duel.player_id == player.id, Duel.status == "played")
                        .order_by(Duel.date.desc(), Duel.id.desc()).limit(limit)):
        npc = db.get(Npc, d.npc_id)
        maps = [x for x in (d.maps or []) if "slot" in x]
        out.append({"kind": "duel", "id": d.id, "title": "1v1", "stage": "1v1", "opponent": npc.name if npc else "?",
                    "my_score": d.score_user, "their_score": d.score_npc, "date": d.date.isoformat(),
                    "maps": len(maps), "watchable": any("times" in x for x in maps)})
    out.sort(key=lambda x: x["date"] or "", reverse=True)
    return out[:limit]


def _reconstruct(p: dict, times: list[int], seed: str) -> list[dict]:
    """A play made by hand left only its totals: lay out results with the same counts and longest combo."""
    n = len(times)
    misses = min(n, int(p.get("misses", 0)))
    n300, n100, n50 = scoring.counts_from_accuracy(max(1, n), float(p.get("accuracy", 100)), misses)
    rng = random.Random(seed)
    results = ["great"] * n
    # Misses split the map into runs; keep one run as long as the best combo, spread the rest.
    combo_share = int(p.get("combo", 0)) / max(1, int(p.get("max_combo", 0)) or 1)
    best = max(1, min(n - misses, round(combo_share * n)))
    free = [i for i in range(n) if i >= best]
    for i in sorted(rng.sample(free, min(misses, len(free)))):
        results[i] = "miss"
    hits = [i for i in range(n) if results[i] == "great"]
    rng.shuffle(hits)
    for i in hits[:n100]:
        results[i] = "ok"
    for i in hits[n100:n100 + n50]:
        results[i] = "meh"
    return [{"time": times[i], "result": r, "error": 0} for i, r in enumerate(results)]


def _user_of(db: Session, player: Player, p: dict, countries: dict) -> dict:
    if p.get("kind") == "user":
        return {"user_id": player.id, "country": player.country, "legend": False}
    npc = db.get(Npc, p["npc_id"]) if p.get("npc_id") else db.scalar(
        select(Npc).where(Npc.player_id == player.id, Npc.name == p.get("name")))
    if npc is None:
        return {"user_id": 0, "country": countries.get(p.get("side"), "XX"), "legend": False}
    return {"user_id": osu_api.npc_user_id(npc.id), "country": npc.country, "legend": npc.kind == "legend"}


def map_view(db: Session, player: Player, kind: str, source_id: int, index: int) -> dict:
    src = _source(db, player, kind, source_id)
    maps = src["maps"]
    if not 0 <= index < len(maps):
        raise WatchError(404, "no such map in this match")
    m = maps[index]
    times = m.get("times")
    if not times and kind == "match" and not src["has_user"] and m.get("beatmap_id"):
        m = _simulate_light_map(db, player, src, index)
        times = m.get("times")
    if not times:
        raise WatchError(409, "this match was played before maps could be replayed")
    before = {"a": sum(1 for x in maps[:index] if x.get("winner") == "a"),
              "b": sum(1 for x in maps[:index] if x.get("winner") == "b")}
    after = {s: before[s] + (1 if m.get("winner") == s else 0) for s in ("a", "b")}
    players = []
    for i, p in enumerate(m.get("players", [])):
        who = _user_of(db, player, p, src["countries"])
        if p.get("trace"):
            points, errors = p["trace"]["points"], p["trace"]["errors"]
            sliders = p["trace"].get("sliders", {})
            objects = [{"time": times[k], "result": SLIDER_RESULTS.get(sliders.get(str(k), "")) or RESULTS[c],
                        "error": errors[k] if k < len(errors) else 0}
                       for k, c in enumerate(points) if k < len(times)]
            reconstructed = False
        else:
            objects = _reconstruct(p, times, f"{source_id}:{index}:{i}")
            reconstructed = True
        players.append({
            "name": p.get("name"), "side": p.get("side"), "user_id": who["user_id"], "country": who["country"],
            "avatar_url": osu_api.avatar_url(p.get("name", "?"), who["legend"]),
            "score": p.get("score", 0), "accuracy": p.get("accuracy", 0), "misses": p.get("misses", 0),
            "combo": p.get("combo", 0), "passed": p.get("passed", True), "hand": bool(p.get("hand")),
            "reconstructed": reconstructed, "knobs": _with_style(db, player, p), "objects": objects,
        })
    return {
        "kind": kind, "id": source_id, "index": index, "maps": len(maps), "title": src["title"], "stage": src["stage"],
        "first_to": src["first_to"], "names": src["names"], "slot": m.get("slot"), "picked_by": m.get("picked_by"),
        "beatmap_id": m.get("beatmap_id"), "map_title": m.get("title"), "mods": "" if m.get("mods") in (None, "NM") else m["mods"],
        "stars": m.get("stars"), "score_a": m.get("score_a"), "score_b": m.get("score_b"), "winner": m.get("winner"),
        "before": before, "after": after, "players": players,
        "date": src["date"].isoformat() if isinstance(src["date"], date) else None,
    }
