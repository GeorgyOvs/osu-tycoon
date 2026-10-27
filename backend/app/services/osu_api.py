"""osu! API v2 shapes for the tycoon client (lazer fork): the career, its NPCs and their scores as lazer expects them.

Only what lazer's own screens read is filled in. User ids: careers keep their id, NPCs are offset so both can be
looked up through the same /users endpoint.
"""
from datetime import date, datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from urllib.parse import quote

from app.config import PUBLIC_URL
from app.engine import scoring, world
from app.models import Beatmap, MapScore, Npc, Player, ProfileSnapshot, Score
from app.services import leaderboards, profile, ranking, world_service

NPC_ID_OFFSET = 1_000_000
SCORE_ID_OFFSETS = {"user": 10_000_000, "npc": 20_000_000}
BOARD_SCORE_ID_BASE = {"user": 10**12, "npc": 2 * 10**12, "anchor": 3 * 10**12}  # + beatmap_id * 1000 + position
PROFILE_ORDER = ["me", "recent_activity", "top_ranks", "historical", "medals", "beatmaps", "kudosu"]


def avatar_url(name: str, legend: bool = False) -> str:
    """Every player has an avatar of the world's own (never a stranger's from a.ppy.sh, which lazer would
    otherwise fetch by user id); see services/avatars."""
    return f"{PUBLIC_URL}/api/avatars/{quote(name, safe='')}.png" + ("?legend=1" if legend else "")


def npc_user_id(npc_id: int) -> int:
    return NPC_ID_OFFSET + npc_id


def _when(day: date | datetime | None) -> str | None:
    if day is None:
        return None
    if isinstance(day, datetime):
        return day.astimezone(timezone.utc).isoformat()
    return datetime.combine(day, time(12), tzinfo=timezone.utc).isoformat()


def _level(play_count: int) -> dict:
    raw = (max(0, play_count) / 4) ** 0.5  # grows quickly at first, then slowly, like the real thing
    return {"current": int(raw) + 1, "progress": int((raw % 1) * 100)}


def _user(*, user_id: int, username: str, country: str, pp: float, global_rank: int | None,
          country_rank: int | None, accuracy: float, play_count: int, max_combo: int, joined: date | None,
          rank_history: list[int], grades: dict[str, int], best_count: int, title: str | None = None,
          followers: int = 0, best_rank: int | None = None, online: bool = False, legend: bool = False) -> dict:
    return {
        "id": user_id,
        "username": username,
        "country_code": country,
        "avatar_url": avatar_url(username, legend),
        "cover_url": None,
        "is_supporter": False,
        "is_online": online,
        "is_active": True,
        "is_bot": False,
        "join_date": _when(joined),
        "title": title,
        "playmode": "osu",
        "profile_order": PROFILE_ORDER,
        "follower_count": followers,
        "kudosu": {"total": 0, "available": 0},
        "previous_usernames": [],
        "badges": [],
        "groups": [],
        "user_achievements": [],
        "monthly_playcounts": [],
        "replays_watched_counts": [],
        "scores_best_count": best_count,
        "scores_first_count": 0,
        "scores_recent_count": 0,
        "scores_pinned_count": 0,
        "beatmap_playcounts_count": 0,
        "rank_highest": {"rank": best_rank, "updated_at": _when(joined)} if best_rank else None,
        "rank_history": {"mode": "osu", "data": rank_history} if rank_history else None,
        "statistics": {
            "level": _level(play_count),
            "is_ranked": global_rank is not None,
            "global_rank": global_rank,
            "country_rank": country_rank,
            "pp": round(pp, 2),
            "ranked_score": 0,
            "hit_accuracy": round(accuracy, 2),
            "play_count": play_count,
            "play_time": play_count * 150,
            "total_score": 0,
            "total_hits": 0,
            "maximum_combo": max_combo,
            "replays_watched_by_others": 0,
            "grade_counts": {"ss": grades.get("X", 0), "ssh": grades.get("XH", 0), "s": grades.get("S", 0),
                             "sh": grades.get("SH", 0), "a": grades.get("A", 0)},
        },
    }


def _country_rank(db: Session, player: Player, country: str, pp: float) -> int | None:
    if pp <= 0:
        return None
    above = db.scalar(select(func.count()).select_from(Npc).where(
        Npc.player_id == player.id, Npc.country == country, Npc.rank.is_not(None), Npc.pp > pp))
    user_above = player.country == country and player.total_pp > pp
    return (above or 0) + int(user_above) + 1


def career_user(db: Session, player: Player) -> dict:
    scores = profile.player_scores(db, player)
    top = ranking.top_plays(scores)
    grades: dict[str, int] = {}
    for s in top:
        g = scoring.stable_grade(s.accuracy, s.misses, s.mods, s.map_max_combo or s.max_combo)
        grades[g] = grades.get(g, 0) + 1
    history = [r for (r,) in db.execute(select(ProfileSnapshot.rank).where(ProfileSnapshot.player_id == player.id)
                                        .order_by(ProfileSnapshot.date.desc()).limit(90)) if r]
    joined = min((s.played_on for s in scores), default=player.in_game_date)
    return _user(
        user_id=player.id, username=player.name, country=player.country, pp=player.total_pp,
        global_rank=player.global_rank,
        country_rank=_country_rank(db, player, player.country, player.total_pp) if player.global_rank else None,
        accuracy=player.accuracy, play_count=player.play_count,
        max_combo=max((s.max_combo for s in scores), default=0), joined=joined,
        rank_history=list(reversed(history)), grades=grades, best_count=len(top),
        followers=player.followers, online=True,
    )


def npc_user(db: Session, player: Player, npc: Npc) -> dict:
    rows = list(db.scalars(select(MapScore).where(MapScore.player_id == player.id, MapScore.npc_id == npc.id,
                                                  MapScore.set_on <= player.in_game_date)))
    measured = (sum(r.accuracy for r in rows) / len(rows), len(rows), 0) if rows else None
    accuracy, play_count = _npc_stats(npc, player.in_game_date, measured)
    return _user(
        user_id=npc_user_id(npc.id), username=npc.name, country=npc.country, pp=npc.pp, global_rank=npc.rank,
        country_rank=_country_rank(db, player, npc.country, npc.pp) if npc.rank else None,
        accuracy=accuracy, play_count=play_count,
        max_combo=max((r.max_combo for r in rows), default=0), joined=npc.join_date, rank_history=[],
        grades={}, best_count=len(rows), followers=0, best_rank=npc.best_rank,
        title="Legend" if npc.kind == "legend" else None, online=npc.status == "active", legend=npc.kind == "legend",
    )


MEASURED_MIN_SCORES = 5  # below this, an NPC's stats are estimated from its profile instead


def npc_estimates(npc: Npc, on: date) -> tuple[float, int]:
    """Plausible (accuracy, play count) for an NPC with too few map scores to measure: accuracy from its
    technical/tapping skill with a personal offset, play count from its years in the game and level."""
    comps = world.composites(npc.overall, npc.style or {})
    skill = (comps["technical"] + comps["tapping"]) / 2
    personal = ((npc.seed % 1000) / 1000 - 0.5) * 1.2
    accuracy = max(85.0, min(99.4, 91.5 + 0.075 * skill + personal))
    days = max(0, (on - npc.join_date).days) if npc.join_date else 3 * 365  # legends carry no join date
    play_count = int(days * (3 + skill / 12))
    return round(accuracy, 2), play_count


def _npc_stats(npc: Npc, on: date, measured: tuple[float, int, int] | None) -> tuple[float, int]:
    estimated_acc, estimated_plays = npc_estimates(npc, on)
    if measured and measured[1] >= MEASURED_MIN_SCORES:
        return measured[0], max(measured[1], estimated_plays)
    return estimated_acc, estimated_plays


def find_user(db: Session, player: Player, lookup: str, by_name: bool) -> dict | None:
    """Resolve a /users lookup inside the career's world: the career itself or one of its NPCs."""
    name = lookup.removeprefix("@")
    if by_name or not name.isdigit():
        if name.lower() == player.name.lower():
            return career_user(db, player)
        npc = db.scalar(select(Npc).where(Npc.player_id == player.id, func.lower(Npc.name) == name.lower()))
        return npc_user(db, player, npc) if npc else None
    user_id = int(name)
    if user_id == player.id:
        return career_user(db, player)
    npc = db.get(Npc, user_id - NPC_ID_OFFSET) if user_id > NPC_ID_OFFSET else None
    return npc_user(db, player, npc) if npc and npc.player_id == player.id else None


def _n_objects(db: Session, beatmap_id: int, fallback: int) -> int:
    beatmap = db.get(Beatmap, beatmap_id)
    counted = (beatmap.count_circles + beatmap.count_sliders) if beatmap else 0
    return counted or fallback


def _beatmap_json(db: Session, beatmap_id: int, fallback: tuple[str, str, str] = ("", "", "")) -> tuple[dict, dict]:
    beatmap = db.get(Beatmap, beatmap_id)
    artist, title, version = fallback
    if beatmap is not None:
        bset = beatmap.beatmapset
        return ({"id": beatmap.id, "beatmapset_id": bset.id, "version": beatmap.version, "mode_int": 0,
                 "difficulty_rating": beatmap.stars, "status": "ranked", "total_length": beatmap.total_length,
                 "hit_length": beatmap.hit_length, "max_combo": beatmap.max_combo, "cs": beatmap.cs, "ar": beatmap.ar,
                 "accuracy": beatmap.od, "drain": beatmap.hp, "bpm": beatmap.bpm},
                {"id": bset.id, "artist": bset.artist, "title": bset.title, "creator": bset.creator,
                 "status": "ranked", "covers": {}, "ranked_date": _when(bset.ranked_date)})
    return ({"id": beatmap_id, "beatmapset_id": 0, "version": version, "mode_int": 0, "status": "ranked"},
            {"id": 0, "artist": artist, "title": title, "creator": "", "status": "ranked", "covers": {}})


def _mods(mods: str) -> list[dict]:
    return [{"acronym": mods[i:i + 2]} for i in range(0, len(mods or ""), 2)]


def _grade(accuracy: float, misses: int, mods: str, n_objects: int) -> str:
    return scoring.stable_grade(accuracy, misses, mods, max(1, n_objects))


def score_json(*, score_id: int, user: dict, beatmap_id: int, mods: str, total: int, accuracy: float,
               max_combo: int, misses: int, pp: float, when: date, n_objects: int,
               beatmap: dict | None = None, beatmapset: dict | None = None) -> dict:
    n300, n100, n50 = scoring.counts_from_accuracy(max(1, n_objects), accuracy, misses)
    return {
        "id": score_id,
        "user_id": user["id"],
        "user": user,
        "beatmap_id": beatmap_id,
        "ruleset_id": 0,
        "passed": True,
        "ranked": True,
        "has_replay": False,
        "total_score": total,
        "legacy_total_score": total,
        "accuracy": round(accuracy / 100, 4),
        "max_combo": max_combo,
        "rank": _grade(accuracy, misses, mods, n_objects),
        "mods": _mods(mods),
        "statistics": {"great": n300, "ok": n100, "meh": n50, "miss": misses},
        "maximum_statistics": {"great": max(1, n_objects)},
        "pp": round(pp, 2),
        "ended_at": _when(when),
        # lazer sets the beatmapset onto the beatmap, so it must come after it and neither may be null.
        **({"beatmap": beatmap, "beatmapset": beatmapset} if beatmap and beatmapset else {}),
    }


def _small_user(user_id: int, name: str, country: str, legend: bool = False) -> dict:
    return {"id": user_id, "username": name, "country_code": country, "avatar_url": avatar_url(name, legend)}


def board_scores(db: Session, player: Player, beatmap_id: int, scope: str, mods: set[str] | None,
                 limit: int) -> tuple[list[dict], dict | None]:
    """The tycoon map leaderboard as lazer scores, plus the career's own position."""
    leaderboards.ensure_board(db, player, beatmap_id)
    facts = leaderboards.map_facts(beatmap_id)
    entries = leaderboards.board_entries(db, player, beatmap_id, 100)
    if scope == "country":
        entries = [e for e in entries if e.country == player.country]
    elif scope in ("friend", "team"):
        entries = [e for e in entries if e.kind == "user"]
    if mods is not None:
        entries = [e for e in entries if {e.mods[i:i + 2] for i in range(0, len(e.mods), 2)} == mods]

    out, mine = [], None
    for position, e in enumerate(entries, start=1):
        if e.kind == "user":
            user, kind = _small_user(player.id, e.name, e.country), "user"
        elif e.npc_id:
            user, kind = _small_user(npc_user_id(e.npc_id), e.name, e.country, e.kind == "legend"), "npc"
        else:  # historical anchor without an NPC behind it: shown, but has no profile
            user, kind = _small_user(0, e.name, e.country), "anchor"
        js = score_json(score_id=BOARD_SCORE_ID_BASE[kind] + beatmap_id * 1000 + position,
                        user=user, beatmap_id=beatmap_id, mods=e.mods, total=e.score, accuracy=e.accuracy,
                        max_combo=e.max_combo, misses=e.misses, pp=e.pp, when=e.set_on, n_objects=facts.n_objects)
        if e.kind == "user":
            # The real place on the board: the user's best is appended at the end when it isn't in the top.
            mine = {"position": e.rank if scope == "global" and e.rank else position, "score": js}
        if position <= limit:
            out.append(js)
    return out, mine


def user_scores(db: Session, player: Player, user_id: int, kind: str, limit: int, offset: int) -> list[dict] | None:
    """Profile score lists (best / recent / firsts / pinned) for the career or an NPC. None when unknown."""
    if kind in ("firsts", "pinned"):
        return []
    if user_id == player.id:
        user = _small_user(player.id, player.name, player.country)
        scores = profile.player_scores(db, player)
        rows = (ranking.top_plays(scores) if kind == "best"
                else sorted(scores, key=lambda s: (s.played_on, s.id), reverse=True))
        out = []
        for s in rows[offset:offset + limit]:
            beatmap, bset = _beatmap_json(db, s.beatmap_id, (s.artist, s.title, s.difficulty_name))
            out.append(score_json(score_id=SCORE_ID_OFFSETS["user"] + s.id, user=user, beatmap_id=s.beatmap_id,
                                  mods=s.mods, total=s.score_value, accuracy=s.accuracy, max_combo=s.max_combo,
                                  misses=s.misses, pp=s.pp, when=s.played_on,
                                  n_objects=_n_objects(db, s.beatmap_id, s.map_max_combo or s.max_combo),
                                  beatmap=beatmap, beatmapset=bset))
        return out
    npc = db.get(Npc, user_id - NPC_ID_OFFSET) if user_id > NPC_ID_OFFSET else None
    if npc is None or npc.player_id != player.id:
        return None
    user = _small_user(user_id, npc.name, npc.country, npc.kind == "legend")
    rows = list(db.scalars(select(MapScore).where(MapScore.player_id == player.id, MapScore.npc_id == npc.id,
                                                  MapScore.set_on <= player.in_game_date)))
    rows.sort(key=(lambda r: (r.pp, r.score)) if kind == "best" else (lambda r: (r.set_on, r.id)), reverse=True)
    out = []
    for r in rows[offset:offset + limit]:
        beatmap, bset = _beatmap_json(db, r.beatmap_id)
        out.append(score_json(score_id=SCORE_ID_OFFSETS["npc"] + r.id, user=user, beatmap_id=r.beatmap_id,
                              mods=r.mods, total=r.score, accuracy=r.accuracy, max_combo=r.max_combo,
                              misses=r.misses, pp=r.pp, when=r.set_on, n_objects=_n_objects(db, r.beatmap_id, r.max_combo),
                              beatmap=beatmap, beatmapset=bset))
    return out


PAGE_SIZE = 50


def _npc_totals(db: Session, player: Player, npc_ids: list[int]) -> dict[int, tuple[float, int, int]]:
    """npc_id -> (average accuracy, play count, ranked score) from their map scores up to today, in one query."""
    if not npc_ids:
        return {}
    rows = db.execute(select(MapScore.npc_id, func.avg(MapScore.accuracy), func.sum(func.max(MapScore.attempts, 1)),
                             func.sum(MapScore.score))
                      .where(MapScore.player_id == player.id, MapScore.npc_id.in_(npc_ids),
                             MapScore.set_on <= player.in_game_date)
                      .group_by(MapScore.npc_id))
    return {npc_id: (acc or 0.0, plays or 0, score or 0) for npc_id, acc, plays, score in rows}


def _ranking_entry(user: dict, *, pp: float, rank: int | None, accuracy: float, play_count: int,
                   ranked_score: int) -> dict:
    return {
        "user": user,
        "is_ranked": rank is not None,
        "global_rank": rank,
        "pp": round(pp, 2),
        "hit_accuracy": round(accuracy, 2),
        "play_count": play_count,
        "ranked_score": ranked_score,
        "total_score": ranked_score,
        "level": _level(play_count),
        "grade_counts": {"ss": 0, "ssh": 0, "s": 0, "sh": 0, "a": 0},
    }


def rankings(db: Session, player: Player, country: str | None, page: int) -> tuple[list[dict], int]:
    """The world's performance ranking (NPCs and the career), one page of lazer's rankings table."""
    rows = world_service.leaderboard(db, player, country, limit=page * PAGE_SIZE)
    page_rows = rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    npc_ids = [r.npc_id for r in page_rows if r.npc_id]
    totals = _npc_totals(db, player, npc_ids)
    npcs = {n.id: n for n in db.scalars(select(Npc).where(Npc.id.in_(npc_ids)))} if npc_ids else {}
    out = []
    for r in page_rows:
        if r.kind == "user":
            out.append(_ranking_entry(_small_user(player.id, player.name, player.country), pp=player.total_pp,
                                      rank=player.global_rank, accuracy=player.accuracy,
                                      play_count=player.play_count,
                                      ranked_score=sum(s.score_value for s in ranking.top_plays(
                                          profile.player_scores(db, player)))))
        else:
            measured = totals.get(r.npc_id)
            acc, plays = _npc_stats(npcs[r.npc_id], player.in_game_date, measured)
            score = measured[2] if measured else 0
            out.append(_ranking_entry(_small_user(npc_user_id(r.npc_id), r.name, r.country, r.kind == "legend"), pp=r.pp, rank=r.rank,
                                      accuracy=acc, play_count=plays, ranked_score=score))
    q = select(func.count()).select_from(Npc).where(Npc.player_id == player.id, Npc.rank.is_not(None))
    if country:
        q = q.where(Npc.country == country.upper())
    total = (db.scalar(q) or 0) + int(player.total_pp > 0 and (not country or country.upper() == player.country))
    return out, total


def country_rankings(db: Session, player: Player, page: int) -> tuple[list[dict], int]:
    """Countries by the summed pp of their ranked players in this world (the career counts for its country)."""
    rows = db.execute(select(Npc.country, func.count(), func.sum(Npc.pp))
                      .where(Npc.player_id == player.id, Npc.rank.is_not(None)).group_by(Npc.country)).all()
    countries = {code: [count, pp or 0.0] for code, count, pp in rows}
    if player.total_pp > 0:
        entry = countries.setdefault(player.country, [0, 0.0])
        entry[0] += 1
        entry[1] += player.total_pp
    ordered = sorted(countries.items(), key=lambda kv: kv[1][1], reverse=True)
    out = [{"code": code, "active_users": count, "play_count": count * 1000, "ranked_score": 0,
            "performance": round(pp)} for code, (count, pp) in ordered[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]]
    return out, len(ordered)
