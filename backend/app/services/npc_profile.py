"""osu!-website-style pages for other players, global search and head-to-head comparison.

An NPC's rank/pp history is not stored: it is recomputed from the same career curve the weekly
world tick follows (curve -> overall -> pp -> rank), so it costs nothing and never drifts from
the model. The last point is the NPC's actual current pp and rank.
"""

from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import simulation, world
from app.models import Beatmap, ChatMessage, MapScore, Npc, Player, WorldEvent
from app.services import beatmap_index, leaderboards, profile_stats, rivals, teams
from app.services.ranking import estimate_global_rank

MAX_POINTS = 120
SEARCH_LIMIT = 8
TOP_PLAYS = 10


# --- history --------------------------------------------------------------------------------


def _start(npc: Npc) -> date | None:
    if npc.kind == "legend":
        legend = world.LEGENDS_BY_NAME.get(npc.name)
        if legend is None:
            return None
        y, m = legend.curve[0][0].split("-")
        return date(int(y), int(m), 1)
    return npc.join_date


def _overall_at(npc: Npc, on: date) -> float | None:
    """The curve's rating on a date, or None when the player is not ranked then (not started, away, retired)."""
    if npc.kind == "legend":
        legend = world.LEGENDS_BY_NAME.get(npc.name)
        if legend is None or world.legend_status(legend, on) != "active":
            return None
        return world.legend_curve(legend, on, npc.curve_shift_weeks)
    value = world.procedural_curve(npc, on)
    if value is None:
        return None
    past_prime = (on - npc.join_date).days / 365 - npc.ramp_years - npc.prime_years
    if npc.kind == "procedural" and past_prime > 1.5:
        return None
    return value


def history(npc: Npc, on: date, since: date | None = None) -> list[dict]:
    """Rank and pp from the career curve, sampled evenly up to `on` (the last point is the live value)."""
    start = _start(npc)
    if start is None or start >= on:
        return [{"date": on.isoformat(), "rank": npc.rank, "pp": round(npc.pp, 1)}] if npc.rank else []
    if since is not None:
        start = max(start, since)
    span = max(1, (on - start).days)
    step = max(7, span // MAX_POINTS)
    out = []
    d = start
    while d < on:
        overall = _overall_at(npc, d)
        if overall is not None:
            pp = world.pp_for_overall(world.pp_overall(world.composites(overall, npc.style), d), d)
            out.append({"date": d.isoformat(), "rank": estimate_global_rank(pp, d), "pp": round(pp, 1)})
        else:
            out.append({"date": d.isoformat(), "rank": None, "pp": 0.0})
        d += timedelta(days=step)
    out.append({"date": on.isoformat(), "rank": npc.rank, "pp": round(npc.pp, 1)})
    return out


# --- pieces of the page ---------------------------------------------------------------------


def _country_rank(db: Session, player: Player, npc: Npc) -> int | None:
    if not npc.rank:
        return None
    ahead = db.scalar(select(func.count()).select_from(Npc).where(
        Npc.player_id == player.id, Npc.country == npc.country, Npc.rank.is_not(None), Npc.pp > npc.pp)) or 0
    if player.country == npc.country and player.global_rank and player.total_pp > npc.pp:
        ahead += 1
    return ahead + 1


def top_plays(db: Session, player: Player, npc: Npc, limit: int = TOP_PLAYS) -> list[dict]:
    rows = list(db.scalars(select(MapScore).where(MapScore.player_id == player.id, MapScore.npc_id == npc.id,
                                                  MapScore.set_on <= player.in_game_date)))
    best: dict[int, MapScore] = {}
    for s in rows:
        if s.beatmap_id not in best or s.score > best[s.beatmap_id].score:
            best[s.beatmap_id] = s
    out = []
    for s in best.values():
        pp = s.pp
        if not pp:
            try:
                pp = leaderboards.era_pp(s.beatmap_id, s.mods, s.accuracy, s.misses, s.max_combo, player.in_game_date)
            except Exception:  # noqa: BLE001 - a map that can't be analysed just shows without pp
                pp = 0.0
        b = db.get(Beatmap, s.beatmap_id)
        out.append({
            "beatmap_id": s.beatmap_id, "beatmapset_id": b.beatmapset_id if b else None,
            "artist": b.beatmapset.artist if b else "", "title": b.beatmapset.title if b else f"beatmap {s.beatmap_id}",
            "version": b.version if b else "", "stars": round(b.stars, 2) if b else 0.0, "mods": s.mods or "",
            "accuracy": s.accuracy, "max_combo": s.max_combo, "misses": s.misses, "score": s.score,
            "pp": round(pp, 1), "set_on": s.set_on.isoformat(),
        })
    out.sort(key=lambda r: -r["pp"])
    return out[:limit]


def news(db: Session, player: Player, npc: Npc, limit: int = 8) -> list[dict]:
    rows = db.scalars(select(WorldEvent).where(
        WorldEvent.player_id == player.id, WorldEvent.date <= player.in_game_date,
        or_(func.json_extract(WorldEvent.data, "$.npc_id") == npc.id, WorldEvent.message.contains(npc.name)),
    ).order_by(WorldEvent.date.desc(), WorldEvent.id.desc()).limit(limit))
    return [{"date": e.date.isoformat(), "type": e.type, "message": e.message} for e in rows]


def relationship(db: Session, player: Player, npc: Npc) -> dict:
    rival = rivals.rival_for(db, player, npc.id)
    team = teams.active_team(db, player)
    teammate = bool(team and any(m.npc_id == npc.id for m in teams.live_members(team)))
    mentor = (player.story_state or {}).get("mentor")
    dms = db.scalar(select(func.count()).select_from(ChatMessage).where(
        ChatMessage.player_id == player.id, ChatMessage.channel == f"DM:{npc.name}")) or 0
    return {
        "rival": {"heat": round(rival.heat, 1), "record": rival.record, "since": rival.since.isoformat()} if rival else None,
        "teammate": teammate, "team": team.name if teammate and team else None,
        "mentor": bool(mentor and mentor.get("npc_id") == npc.id), "messages": dms,
    }


def _comps(npc: Npc) -> dict[str, float]:
    return {k: round(v, 1) for k, v in world.composites(npc.overall, npc.style).items()}


def profile(db: Session, player: Player, npc: Npc) -> dict:
    legend = world.LEGENDS_BY_NAME.get(npc.name) if npc.kind == "legend" else None
    hist = history(npc, player.in_game_date)
    ranks = [h for h in hist if h["rank"]]
    peak = min(ranks, key=lambda h: h["rank"]) if ranks else None
    if npc.best_rank and (peak is None or npc.best_rank < peak["rank"]):
        peak = {"rank": npc.best_rank, "date": None}
    comps = _comps(npc)
    ordered = sorted(comps, key=comps.get, reverse=True)
    return {
        "id": npc.id, "name": npc.name, "country": npc.country, "kind": npc.kind, "status": npc.status,
        "away_until": npc.away_until.isoformat() if npc.away_until else None,
        "joined": (_start(npc) or player.in_game_date).isoformat(),
        "note": legend.note if legend else "", "aliases": list(legend.aliases) if legend else [],
        "archetype": world.archetype(npc.style), "overall": round(world.display_overall(npc.overall), 1), "composites": comps,
        "strengths": ordered[:2], "weaknesses": list(reversed(ordered[-2:])),
        "pp": round(npc.pp, 1), "global_rank": npc.rank, "country_rank": _country_rank(db, player, npc),
        "peak_rank": peak["rank"] if peak else None, "peak_date": peak.get("date") if peak else None,
        "titles": npc.titles, "form": round(npc.form, 2), "motivation": round(npc.motivation),
        "history": hist, "top_plays": top_plays(db, player, npc), "news": news(db, player, npc),
        "relationship": relationship(db, player, npc),
    }


# --- search -------------------------------------------------------------------------------


def search(db: Session, player: Player, q: str) -> dict:
    q = q.strip()
    if len(q) < 2:
        return {"players": [], "maps": []}
    lowered = q.lower()
    alias_hits = {name for name, legend in world.LEGENDS_BY_NAME.items()
                  if any(lowered in a.lower() for a in legend.aliases)}
    rows = list(db.scalars(select(Npc).where(
        Npc.player_id == player.id, Npc.status != "not_started",
        or_(Npc.name.ilike(f"%{q}%"), Npc.name.in_(alias_hits) if alias_hits else False),
    ).limit(200)))
    rows.sort(key=lambda n: (n.name.lower() != lowered, not n.name.lower().startswith(lowered), -(n.pp or 0)))
    players = [{"id": n.id, "name": n.name, "country": n.country, "kind": n.kind, "status": n.status,
                "rank": n.rank, "pp": round(n.pp, 1)} for n in rows[:SEARCH_LIMIT]]
    _, sets = beatmap_index.search(db, player.in_game_date, q, sort="plays", limit=SEARCH_LIMIT)
    maps = []
    for bset, diffs in sets:
        maps.append({
            "beatmapset_id": bset.id, "artist": bset.artist, "title": bset.title, "creator": bset.creator,
            "ranked_date": bset.ranked_date.isoformat(), "play_count": bset.play_count,
            "diffs": [{"beatmap_id": b.id, "version": b.version, "stars": round(b.stars, 2)}
                      for b in sorted(diffs, key=lambda b: -b.stars)[:5]],
        })
    return {"players": players, "maps": maps}


# --- compare ------------------------------------------------------------------------------


def compare(db: Session, player: Player, npc: Npc) -> dict:
    mine = profile_stats.history(db, player)
    since = date.fromisoformat(mine[0]["date"]) if mine else player.in_game_date
    theirs = history(npc, player.in_game_date, since=since)
    my_comps = {k: round(v, 1) for k, v in A.composites(simulation.effective_values(player)).items()}
    rival = rivals.rival_for(db, player, npc.id)
    peak_mine = min((h["rank"] for h in mine if h["rank"]), default=None)
    peak_theirs = min((h["rank"] for h in history(npc, player.in_game_date) if h["rank"]), default=npc.best_rank)
    return {
        "you": {"name": player.name, "country": player.country, "rank": player.global_rank, "pp": round(player.total_pp, 1),
                "accuracy": round(player.accuracy, 2), "peak_rank": peak_mine, "composites": my_comps, "history": mine},
        "them": {"id": npc.id, "name": npc.name, "country": npc.country, "rank": npc.rank, "pp": round(npc.pp, 1),
                 "accuracy": None, "peak_rank": peak_theirs, "composites": _comps(npc), "history": theirs},
        "head_to_head": rival.record if rival else {},
    }
