"""Persisted living world: creation, weekly ticks, news and the leaderboard."""

import json
import random
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import pp_history, simulation, world, world_data
from app.engine.world_data import LEGENDS
from app.models import Beatmap, MapScore, Npc, Player, WorldEvent, WorldState
from app.services import leaderboards, media, profile, rivals, story, tournaments, score_records
from app.services.tournaments import News

NOTABLE_RANK = 1000
RISING_STAR_RANK = 100


def _initial_status(npc: Npc, on: date) -> None:
    """Place an NPC on its career curve at world creation, without simulating history."""
    if npc.kind == "legend":
        legend = world.LEGENDS_BY_NAME[npc.name]
        npc.status = world.legend_status(legend, on)
        npc.overall = world.legend_curve(legend, on)
    else:
        base = world.procedural_curve(npc, on)
        if base is None:
            npc.status = "not_started"
        else:
            past_prime = (on - npc.join_date).days / 365 - npc.ramp_years - npc.prime_years
            npc.status = "retired" if past_prime > 1.5 and npc.kind == "procedural" else "active"
            npc.overall = base
    world.refresh_pp(npc, on, smooth=False)


def prune_removed_legends(db: Session) -> int:
    """Legends removed from world_data (e.g. merged as aliases) leave orphan rows in old worlds."""
    orphans = [n for n in db.scalars(select(Npc).where(Npc.kind == "legend")) if n.name not in world.LEGENDS_BY_NAME]
    ids = [n.id for n in orphans]
    if ids:
        db.execute(delete(MapScore).where(MapScore.npc_id.in_(ids)))
        db.execute(delete(Npc).where(Npc.id.in_(ids)))
    return len(ids)


REAL_PLAYERS_FILE = Path(__file__).resolve().parent.parent / "data" / "real_players.json"


@lru_cache(maxsize=1)
def _real_player_records() -> tuple[date | None, tuple[dict, ...]]:
    if not REAL_PLAYERS_FILE.exists():
        return None, ()
    data = json.loads(REAL_PLAYERS_FILE.read_text(encoding="utf-8"))
    return date.fromisoformat(data["fetched"]), tuple(data.get("players", []))


def real_players(world_seed: int) -> list[world.ProceduralCareer]:
    """Imported real players (see app/tools/import_real_players.py), minus anyone who is a legend."""
    fetched, records = _real_player_records()
    reserved = {n.lower() for n in world.RESERVED_NAMES}
    out = []
    for rec in records:
        names = {rec.get("name", "").lower(), *(n.lower() for n in rec.get("previous_names", []))}
        if names & reserved:
            continue  # one person = one entry: legends keep their hand-written careers
        career = world.real_career(rec, fetched, world_seed)
        if career:
            out.append(career)
    return out


def ensure_world(db: Session, player: Player) -> WorldState:
    state = db.get(WorldState, player.id)
    if state is not None:
        if story.get(player, "tournament_templates") != len(world_data.TOURNAMENTS):
            tournaments.backfill_templates(db, player, state)
            story.put(player, "tournament_templates", len(world_data.TOURNAMENTS))
        if not state.population_version:
            existing = list(db.scalars(select(Npc).where(Npc.player_id == player.id)))
            taken = {n.name.lower() for n in existing}
            count = world.PROCEDURAL_WITH_REAL if any(n.kind == "real" for n in existing) else world.PROCEDURAL_COUNT
            for c in world.generate_procedural(player.seed, count):
                if c.name.lower() in taken:
                    continue
                n = Npc(player_id=player.id, kind="procedural", name=c.name, country=c.country,
                        style=c.style, seed=c.seed, join_date=c.join_date, peak=c.peak,
                        ramp_years=c.ramp_years, prime_years=c.prime_years, decline_per_year=c.decline_per_year)
                n.deviation, n.form, n.motivation, n.curve_shift_weeks, n.titles = 0.0, 0.0, 70.0, 0, 0
                world.initialize_development(n)
                _initial_status(n, state.last_tick)
                db.add(n)
                taken.add(n.name.lower())
            state.population_version = 1
            db.flush()
        return state

    on = player.in_game_date
    npcs = []
    for i, legend in enumerate(LEGENDS):
        npcs.append(Npc(player_id=player.id, kind="legend", name=legend.name, country=legend.country,
                        style=legend.style, seed=player.seed * 31 + i))
    reals = real_players(player.seed)
    careers = [("real", c) for c in reals]
    careers += [("procedural", c) for c in world.generate_procedural(
        player.seed, world.PROCEDURAL_WITH_REAL if reals else world.PROCEDURAL_COUNT)]
    taken = {c.name.lower() for _, c in careers if _ == "real"}
    for kind, c in careers:
        if kind == "procedural" and c.name.lower() in taken:
            continue
        npcs.append(Npc(player_id=player.id, kind=kind, name=c.name, country=c.country, style=c.style,
                        seed=c.seed, join_date=c.join_date, peak=c.peak, ramp_years=c.ramp_years,
                        prime_years=c.prime_years, decline_per_year=c.decline_per_year))
    for npc in npcs:
        npc.deviation, npc.form, npc.motivation, npc.curve_shift_weeks, npc.titles = 0.0, 0.0, 70.0, 0, 0
        if npc.kind == "procedural":
            world.initialize_development(npc)
        _initial_status(npc, on)
    db.add_all(npcs)

    state = WorldState(player_id=player.id, last_tick=on, generated_through=on.year - 1, number_one_id=None)
    db.add(state)
    db.flush()
    leader = _number_one(db, player)
    state.number_one_id = leader.id if leader else None
    fictional = [n for n in npcs if n.kind == "procedural" and n.status == "active"]
    state.fictional_pp_record = max((n.pp for n in fictional), default=0.0)
    state.fictional_score_record = 0.0  # only stored map scores may establish a single-play record

    tournaments.generate_through(db, player, state, on.year + 1)
    return state


def _number_one(db: Session, player: Player) -> Npc | None:
    return db.scalars(
        select(Npc).where(Npc.player_id == player.id, Npc.rank.is_not(None)).order_by(Npc.pp.desc()).limit(1)
    ).first()


def _log(db: Session, player: Player, on: date, n: world.WorldNews, out: list[News]) -> None:
    tournaments._news(db, player, on, n.type, n.message, n.importance, n.data, out)


def advance(db: Session, player: Player) -> list[News]:
    """Bring the world up to the player's current date: weekly NPC ticks and tournaments."""
    state = ensure_world(db, player)
    out: list[News] = []
    target = player.in_game_date
    era_before = pp_history.era_for(state.last_tick)
    rank_before = player.global_rank
    npcs = list(db.scalars(select(Npc).where(Npc.player_id == player.id)))
    cached_maps = score_records.cached_map_ids()

    while state.last_tick + world.WEEK <= target:
        on = state.last_tick + world.WEEK
        for npc in npcs:
            if npc.status == "retired" and npc.kind == "procedural":
                continue
            if npc.kind != "legend" and npc.join_date and on < npc.join_date:
                continue  # hasn't discovered osu! yet
            was_best = npc.best_rank
            notable = npc.kind == "legend" or (npc.rank is not None and npc.rank <= NOTABLE_RANK)
            for n in world.weekly_step(npc, on, notable):
                n.data = {**(n.data or {}), "npc_id": npc.id}
                _log(db, player, on, n, out)
            world.refresh_pp(npc, on)
            if npc.kind == "procedural" and npc.status == "active":
                _fictional_records(db, player, state, npc, on, out)
            if npc.rank and npc.rank <= RISING_STAR_RANK and (was_best is None or was_best > RISING_STAR_RANK):
                _log(db, player, on, world.WorldNews(
                    "RISING_STAR", f"{npc.name} [{npc.country}] breaks into the global top {RISING_STAR_RANK}!", 2,
                    {"npc_id": npc.id, "rank": npc.rank}), out)

        _advance_npc_rivalries(db, player, npcs, on, out)
        for event in score_records.weekly(db, player, npcs, on, cached_maps):
            _log(db, player, on, event, out)

        leader = max((n for n in npcs if n.rank), key=lambda n: n.pp, default=None)
        current = next((n for n in npcs if n.id == state.number_one_id), None)
        # Hysteresis: neighbours swapping places by a hair isn't news.
        overtaken = current is None or current.rank is None or (leader and leader.pp > current.pp * 1.02)
        if leader and leader.id != state.number_one_id and overtaken:
            state.number_one_id = leader.id
            _log(db, player, on, world.WorldNews(
                "NEW_NUMBER_ONE", f"{leader.name} [{leader.country}] is the new global #1!", 3,
                {"npc_id": leader.id}), out)

        if state.generated_through < on.year + 1:
            tournaments.generate_through(db, player, state, on.year + 1)
        state.last_tick = on
        db.flush()
        out.extend(tournaments.process(db, player, on))

    out.extend(_defend_first_places(db, player))
    leaderboards.advance_stale(db, player)
    era_now = pp_history.era_for(target)
    if era_now.key != era_before.key or era_now.decay:
        pp_before = player.total_pp
        profile.reprice_scores(db, player)
        profile.recompute_aggregates(db, player)
        if era_now.decay and era_now.key == era_before.key and pp_before > 0 and player.total_pp < pp_before * 0.99:
            week = target.isocalendar()[:2]
            if story.get(player, "decay_note") != list(week):
                story.put(player, "decay_note", list(week))
                tournaments._news(db, player, target, "PP_DECAY",
                                  f"Inactivity: your pp is decaying under ppv1 ({pp_before:,.0f}pp -> "
                                  f"{player.total_pp:,.0f}pp). Playing again stops it.", 1,
                                  {"pp_before": pp_before, "pp_after": player.total_pp}, out)
        if era_now.key != era_before.key:
            msg = (f"pp system change: {era_now.name}. {era_now.summary} "
                   f"Your total went from {pp_before:,.0f}pp to {player.total_pp:,.0f}pp.")
            tournaments._news(db, player, era_now.start, "PP_SYSTEM_CHANGE", msg, 3,
                              {"from": era_before.key, "to": era_now.key, "pp_before": pp_before,
                               "pp_after": player.total_pp}, out)
            media.pp_rework(db, player, era_before, era_now, pp_before)
    # The curve itself moves with time, so the user's rank does too.
    profile.recompute_aggregates(db, player)
    rivals.weekly(db, player, rank_before)
    out.extend(tournaments.process(db, player, target))
    story.tick(db, player, out)
    return out


def _fictional_records(db: Session, player: Player, state: WorldState, npc: Npc, on: date,
                       out: list[News]) -> None:
    """Record stories belong only to generated players, never imported real players or legends."""
    previous_pp = state.fictional_pp_record
    if pp_history.era_for(on).ranking != "pp":
        return
    # Total-pp records are announced at meaningful 500pp boundaries, avoiding weekly spam.
    if npc.pp > previous_pp:
        state.fictional_pp_record = npc.pp
        if int(npc.pp // 500) > int(previous_pp // 500):
            _log(db, player, on, world.WorldNews(
                "PP_RECORD", f"{npc.name} reaches a fictional-world total account pp record: {npc.pp:,.0f}pp.", 3,
                {"npc_id": npc.id, "pp": round(npc.pp)}), out)

def _advance_npc_rivalries(db: Session, player: Player, npcs: list[Npc], on: date,
                           out: list[News]) -> None:
    """Pair similarly matched fictional players and keep the rivalry alive across seasons."""
    active = [n for n in npcs if n.kind == "procedural" and n.status == "active" and n.rank and n.rank <= 2000]
    by_id = {n.id: n for n in active}
    handled: set[int] = set()
    for npc in active:
        rival_id = (npc.story or {}).get("rival_id")
        rival = by_id.get(rival_id)
        if not rival or npc.id in handled or rival.id in handled:
            continue
        handled.update((npc.id, rival.id))
        ahead = npc.pp >= rival.pp
        previous = (npc.story or {}).get("rival_ahead")
        if previous is not None and bool(previous) != ahead and max(npc.rank, rival.rank) <= NOTABLE_RANK:
            leader, other = (npc, rival) if ahead else (rival, npc)
            _log(db, player, on, world.WorldNews(
                "RIVALRY", f"{leader.name} takes the lead over {other.name} in their season-long rivalry.", 2,
                {"npc_id": leader.id, "rival_id": other.id}), out)
        for member, member_ahead in ((npc, ahead), (rival, not ahead)):
            story = dict(member.story or {})
            story["rival_ahead"] = member_ahead
            member.story = story

    # At most one new pairing per week. Seeded chance makes replays deterministic.
    free = [n for n in active if not (n.story or {}).get("rival_id")]
    free.sort(key=lambda n: n.pp, reverse=True)
    rng = random.Random(f"npc-rivalries:{player.seed}:{on.isoformat()}")
    if len(free) >= 2 and rng.random() < 0.035:
        pairs = [(a, b) for a, b in zip(free, free[1:]) if 0.82 <= a.pp / max(b.pp, 1) <= 1.22]
        if pairs:
            a, b = rng.choice(pairs)
            for member, rival, ahead in ((a, b, a.pp >= b.pp), (b, a, b.pp >= a.pp)):
                story = dict(member.story or {})
                story.update({"rival_id": rival.id, "rival_ahead": ahead})
                member.story = story
            _log(db, player, on, world.WorldNews(
                "RIVALRY_BEGINS", f"A rivalry is taking shape between {a.name} and {b.name}.", 2,
                {"npc_id": a.id, "rival_id": b.id}), out)


def _defend_first_places(db: Session, player: Player) -> list[News]:
    """Boards where the user holds #1 keep moving: NPCs may take it back."""
    out: list[News] = []
    for board in leaderboards.watched_boards(db, player):
        try:
            _, snipes = leaderboards.ensure_board(db, player, board.beatmap_id)
        except Exception:  # a map that can't be analysed shouldn't stop the world
            continue
        for snipe in snipes:
            beatmap = db.get(Beatmap, board.beatmap_id)
            title = (f"{beatmap.beatmapset.artist} - {beatmap.beatmapset.title} [{beatmap.version}]"
                     if beatmap else f"beatmap {board.beatmap_id}")
            media.sniped_by_npc(db, player, snipe.npc, title, snipe.score)
            rivals.on_snipe(db, player, snipe.npc.id, user_sniped=False)
            tournaments._news(db, player, snipe.score.set_on, "SNIPED",
                              f"{snipe.npc.name} sniped your #1 on {title}.", 2,
                              {"npc_id": snipe.npc.id, "beatmap_id": board.beatmap_id}, out)
    return out


def recent_news(db: Session, player: Player, limit: int = 50, min_importance: int = 1) -> list[WorldEvent]:
    return list(db.scalars(
        select(WorldEvent)
        .where(WorldEvent.player_id == player.id, WorldEvent.importance >= min_importance)
        .order_by(WorldEvent.date.desc(), WorldEvent.id.desc())
        .limit(limit)
    ))


@dataclass
class LeaderboardRow:
    rank: int | None
    name: str
    country: str
    pp: float
    overall: float | None
    kind: str  # user | legend | procedural
    npc_id: int | None
    status: str


def leaderboard(db: Session, player: Player, country: str | None = None, limit: int = 50) -> list[LeaderboardRow]:
    q = select(Npc).where(Npc.player_id == player.id, Npc.rank.is_not(None))
    if country:
        q = q.where(Npc.country == country.upper())
    rows = [
        LeaderboardRow(n.rank, n.name, n.country, n.pp, world.display_overall(n.overall), n.kind, n.id, n.status)
        for n in db.scalars(q.order_by(Npc.pp.desc()).limit(limit * 3))
    ]
    if player.total_pp > 0 and (not country or country.upper() == player.country):
        rows.append(user_row(player))
    rows.sort(key=lambda r: r.pp, reverse=True)
    rows = rows[:limit]
    # The curve can give neighbours the same rank; keep the table strictly ordered.
    last = 0
    for r in rows:
        if r.rank is not None and not country:
            r.rank = max(r.rank, last + 1)
            last = r.rank
    return rows


def user_row(player: Player) -> LeaderboardRow:
    return LeaderboardRow(player.global_rank, player.name, player.country, player.total_pp,
                          A.overall(simulation.effective_values(player)), "user", None, "active")
