"""Per-beatmap historical leaderboards.

A board is simulated month by month from the map's ranked date up to the player's in-game
date: each month some NPCs whose careers overlap that month (re)play the map and keep their
best score. Retired players keep their scores, popular maps draw more players, and the era's
mod meta applies. Boards are stored, so the same date always shows the same names, and they
only grow forward. Curated real scores (data/anchor_scores.json) appear once their date passes.
"""

import json
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import rosu_pp_py as rosu
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import PP_LAZER
from app.engine import leaderboard as lb
from app.engine import scoring, world, pp_history
from app.models import Beatmap, BeatmapSet, MapBoard, MapScore, Npc, Player, Score
from app.services import beatmap_index, osu_files, rivals, sessions, pp

ANCHOR_FILE = Path(__file__).resolve().parent.parent / "data" / "anchor_scores.json"
ANCHOR_FIELDS = {"beatmap_id", "player", "country", "mods", "score", "accuracy", "max_combo", "misses", "date", "source"}
FIRST_MONTH_PLAY_CHANCE = 0.3  # new maps get hammered
MONTHLY_PLAY_CHANCE = 0.06


@lru_cache(maxsize=1)
def anchors() -> dict[int, list[dict]]:
    """Curated real historical scores. Every entry must cite its source."""
    if not ANCHOR_FILE.exists():
        return {}
    out: dict[int, list[dict]] = {}
    for row in json.loads(ANCHOR_FILE.read_text(encoding="utf-8")):
        missing = ANCHOR_FIELDS - row.keys()
        if missing or not str(row.get("source", "")).strip():
            raise ValueError(f"anchor score {row} is missing {sorted(missing) or ['source']}")
        out.setdefault(int(row["beatmap_id"]), []).append(row)
    return out


@lru_cache(maxsize=256)
def map_facts(beatmap_id: int) -> lb.MapFacts:
    content = osu_files.get_osu_file(beatmap_id)
    beatmap = rosu.Beatmap(bytes=content)
    profile = sessions.map_profile(beatmap_id, "")
    stars, ar, od, difficulty = {}, {}, {}, {}
    base_diff = scoring.difficulty_multiplier(beatmap.hp, beatmap.cs, beatmap.od, len(profile.objects),
                                              profile.drain_seconds)
    aim = speed = 0.0
    for mods in lb.MOD_OPTIONS:
        attrs = rosu.Difficulty(mods=mods, lazer=PP_LAZER).calculate(beatmap)
        stars[mods] = attrs.stars
        built = rosu.BeatmapAttributesBuilder(map=beatmap, mods=mods).build()
        ar[mods], od[mods] = built.ar, built.od
        difficulty[mods] = base_diff
        if mods == "":
            aim, speed = attrs.aim or 0.0, attrs.speed or 0.0
    return lb.MapFacts(
        n_objects=len(profile.objects), max_combo=profile.max_combo,
        aim_share=aim / (aim + speed) if aim + speed else 0.5, stars=stars, ar=ar, od=od, difficulty=difficulty,
    )


def user_score_value(score: Score, facts: lb.MapFacts) -> int:
    """ScoreV1 for a user score (older rows saved before score_value existed are estimated)."""
    if score.score_value:
        return score.score_value
    n300, n100, n50 = scoring.counts_from_accuracy(facts.n_objects, score.accuracy, score.misses)
    return scoring.score_v1(n300, n100, n50, score.misses, score.max_combo, facts.max_combo,
                            facts.difficulty.get("", 4), score.mods)


def _overall_at(npc: Npc, on: date) -> float | None:
    """An NPC's rating on a past or present date, from their career curve."""
    if npc.kind == "legend":
        legend = world.LEGENDS_BY_NAME[npc.name]
        if world.legend_status(legend, on) != "active":
            return None
        return world.legend_curve(legend, on, npc.curve_shift_weeks)
    value = world.procedural_curve(npc, on)
    if value is None:
        return None
    past_prime = (on - npc.join_date).days / 365 - npc.ramp_years - npc.prime_years
    return None if past_prime > 2 and npc.kind == "procedural" else value


def _months(start: date, end: date):
    """`start`, then the 1st of every following month up to `end`."""
    d = start
    while d <= end:
        yield d
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)


@dataclass
class SnipeOfUser:
    npc: Npc
    score: MapScore


def _ranked_set(db: Session, beatmap_id: int) -> BeatmapSet:
    beatmap = db.get(Beatmap, beatmap_id)
    if beatmap is not None:
        return beatmap.beatmapset
    bset, status = beatmap_index.lookup_set_for_beatmap(db, beatmap_index.default_client(), beatmap_id)
    if bset is None:
        raise beatmap_index.NotPlayable(422 if status else 404, f"beatmap {beatmap_id} has no ranked leaderboard")
    return bset


def ensure_board(db: Session, player: Player, beatmap_id: int) -> tuple[MapBoard, list[SnipeOfUser]]:
    """Simulate the board forward to the player's date. Returns any snipes of the user's #1."""
    bset = _ranked_set(db, beatmap_id)
    board = db.get(MapBoard, (player.id, beatmap_id))
    if board is None:
        board = MapBoard(player_id=player.id, beatmap_id=beatmap_id,
                         generated_through=bset.ranked_date - timedelta(days=1), user_first=False)
        db.add(board)
    target = player.in_game_date
    if board.generated_through >= target or bset.ranked_date > target:
        return board, []

    facts = map_facts(beatmap_id)
    existing = {}
    for s in db.scalars(select(MapScore).where(
            MapScore.player_id == player.id, MapScore.beatmap_id == beatmap_id, MapScore.kind == "npc")):
        if s.npc_id not in existing or s.score > existing[s.npc_id].score:
            existing[s.npc_id] = s
    user_best = _user_best_value(db, player, beatmap_id, facts)
    popularity = min(1.0, max(0.15, math.log10(bset.play_count + 10) / 7.5))
    easiest = min(facts.stars.values())
    npcs = [n for n in db.scalars(select(Npc).where(Npc.player_id == player.id))
            if _could_ever_pass(n, easiest)]

    snipes: list[SnipeOfUser] = []
    hunters = rivals.rival_npc_ids(db, player) if board.user_first else set()  # rivals go after your #1s
    start = board.generated_through + timedelta(days=1)
    for month in _months(start, target):
        first = (month - bset.ranked_date).days < 31
        for npc in npcs:
            rng = random.Random(f"{player.seed}:lb:{beatmap_id}:{npc.id}:{month.isoformat()}")
            chance = (FIRST_MONTH_PLAY_CHANCE if first else MONTHLY_PLAY_CHANCE) * popularity
            if rng.random() > chance * (3 if npc.id in hunters else 1):
                continue
            overall = _overall_at(npc, month)
            if overall is None:
                continue
            est = lb.estimate_best(world.composites(overall, npc.style), facts, month, rng.randint(2, 8), rng)
            if est is None:
                continue
            current = existing.get(npc.id)
            if current is not None and current.score >= est.score:
                continue
            if current is None or current.record:
                current = MapScore(player_id=player.id, beatmap_id=beatmap_id, kind="npc", npc_id=npc.id,
                                   name=npc.name, country=npc.country, pp=0.0)
                db.add(current)
                existing[npc.id] = current
            set_on = min(target, month + timedelta(days=rng.randint(0, 27)))
            current.mods, current.score, current.accuracy = est.mods, est.score, round(est.accuracy, 2)
            current.max_combo, current.misses, current.set_on, current.pp = est.max_combo, est.misses, set_on, 0.0
            if board.user_first and user_best and est.score > user_best:
                board.user_first = False
                snipes.append(SnipeOfUser(npc, current))
    board.generated_through = target
    db.flush()
    return board, snipes


def _could_ever_pass(npc: Npc, easiest_stars: float) -> bool:
    """Cheap pre-filter: skip NPCs whose whole career never reaches the map's easiest mod combo."""
    peak = (max(npc.peak, npc.overall) if npc.kind != "legend"
            else max(v for _, v in world.LEGENDS_BY_NAME[npc.name].curve))
    best_skill = peak * (1 + world.STYLE_SPREAD)
    return easiest_stars / (2 * (0.6 + 0.04 * best_skill)) <= 1.25


def _user_best(db: Session, player: Player, beatmap_id: int) -> list[Score]:
    return list(db.scalars(select(Score).where(Score.player_id == player.id, Score.beatmap_id == beatmap_id)))


def _user_best_value(db: Session, player: Player, beatmap_id: int, facts: lb.MapFacts) -> int:
    return max((user_score_value(s, facts) for s in _user_best(db, player, beatmap_id)), default=0)


@dataclass
class Entry:
    rank: int
    kind: str  # user | legend | npc | anchor
    name: str
    country: str
    mods: str
    score: int
    accuracy: float
    max_combo: int
    misses: int
    pp: float
    set_on: date
    npc_id: int | None = None
    source: str | None = None


@lru_cache(maxsize=64)
def _parsed(beatmap_id: int) -> rosu.Beatmap:
    return rosu.Beatmap(bytes=osu_files.get_osu_file(beatmap_id))


def _pp(beatmap_id: int, mods: str, accuracy: float, misses: int, combo: int) -> float:
    return rosu.Performance(mods=mods, accuracy=accuracy, misses=misses, combo=combo, lazer=PP_LAZER).calculate(
        _parsed(beatmap_id)).pp


def era_pp(beatmap_id: int, mods: str, accuracy: float, misses: int, combo: int,
           on: date, set_on: date | None = None) -> float:
    result = pp.calculate(osu_files.get_osu_file(beatmap_id), mods, accuracy=accuracy,
                          misses=misses, combo=combo)
    return pp_history.adjust(result.pp, result.pp_aim, result.pp_speed, result.pp_accuracy,
                             combo, result.max_combo, pp_history.era_for(on),
                             max(0, (on - (set_on or on)).days))


def board_entries(db: Session, player: Player, beatmap_id: int, limit: int = 50) -> list[Entry]:
    facts = map_facts(beatmap_id)
    on = player.in_game_date
    npc_kinds = {n.id: n.kind for n in db.scalars(select(Npc).where(Npc.player_id == player.id))}
    rows: list[Entry] = []
    stored = sorted(db.scalars(select(MapScore).where(MapScore.player_id == player.id, MapScore.beatmap_id == beatmap_id,
                                                      MapScore.set_on <= on)), key=lambda s: -s.score)
    seen = set()
    record_ids = set()
    for i, s in enumerate(stored):
        identity = (s.kind, s.npc_id if s.npc_id else s.name)
        if identity in seen:
            continue
        seen.add(identity)
        if i < limit or s.record:
            s.pp = era_pp(beatmap_id, s.mods, s.accuracy, s.misses, s.max_combo, on, s.set_on)
        if s.record:
            record_ids.add(s.npc_id)
        kind = "legend" if npc_kinds.get(s.npc_id) == "legend" else "npc"
        rows.append(Entry(0, kind, s.name, s.country, s.mods, s.score, s.accuracy, s.max_combo, s.misses, s.pp,
                          s.set_on, s.npc_id))
    for a in anchors().get(beatmap_id, []):
        when = date.fromisoformat(a["date"])
        if when <= on:
            rows.append(Entry(0, "anchor", a["player"], a["country"], a["mods"], int(a["score"]), float(a["accuracy"]),
                              int(a["max_combo"]), int(a["misses"]), float(a.get("pp", 0.0)), when,
                              source=a["source"]))
    user_scores = _user_best(db, player, beatmap_id)
    if user_scores:
        best = max(user_scores, key=lambda s: user_score_value(s, facts))
        rows.append(Entry(0, "user", player.name, player.country, best.mods, user_score_value(best, facts),
                          best.accuracy, best.max_combo, best.misses, best.pp, best.played_on))
    rows.sort(key=lambda r: (-r.score, r.set_on))
    for i, r in enumerate(rows, start=1):
        r.rank = i
    top = rows[:limit]
    top.extend(r for r in rows[limit:] if r.npc_id in record_ids)
    you = next((r for r in rows if r.kind == "user"), None)
    if you and you not in top:
        top.append(you)
    return top


def record_history(db: Session, player: Player, beatmap_id: int) -> list[Entry]:
    """Announced plays remain inspectable even after a higher ScoreV1 replaces a player's best."""
    from app.models import WorldEvent
    rows = []
    events = db.scalars(select(WorldEvent).where(
        WorldEvent.player_id == player.id, WorldEvent.date <= player.in_game_date,
        WorldEvent.type.in_(("FIRST_1000PP", "NPC_SCORE_RECORD")),
    ).order_by(WorldEvent.date.desc(), WorldEvent.id.desc()))
    for event in events:
        data = event.data
        if data.get("beatmap_id") != beatmap_id or data.get("retracted"):
            continue
        npc_score = data.get("score_kind") == "npc"
        score = db.get(MapScore if npc_score else Score, data.get("score_id"))
        if score is None or score.player_id != player.id or score.beatmap_id != beatmap_id:
            continue
        rows.append(Entry(0, "npc" if npc_score else "user", score.name if npc_score else player.name,
                          score.country if npc_score else player.country, score.mods,
                          score.score if npc_score else user_score_value(score, map_facts(beatmap_id)),
                          score.accuracy, score.max_combo, score.misses, data["score_pp"], event.date,
                          score.npc_id if npc_score else None))
        if len(rows) >= 20:
            break
    return rows


@dataclass
class SnipeByUser:
    sniped: Entry
    user_entry: Entry


SNIPE_CHECK_SIGNIFICANCE = 0.25  # a play below 25% of the era's best can't realistically be a #1


def on_user_score(db: Session, player: Player, score: Score) -> SnipeByUser | None:
    """After a user score: did it take #1 from someone?

    Boards are only simulated for plays that could plausibly top them (or boards already open),
    which keeps a beginner's sessions fast."""
    from app.services import media

    worth_checking = score.pp >= SNIPE_CHECK_SIGNIFICANCE * media.era_top_play_pp(player.in_game_date)
    if not worth_checking and db.get(MapBoard, (player.id, score.beatmap_id)) is None:
        return None
    try:
        board, _ = ensure_board(db, player, score.beatmap_id)
    except beatmap_index.NotPlayable:
        return None
    facts = map_facts(score.beatmap_id)
    entries = board_entries(db, player, score.beatmap_id, limit=2)
    others = [e for e in entries if e.kind != "user"]
    user_entry = next((e for e in entries if e.kind == "user"), None)
    if user_entry is None or user_entry.rank != 1 or user_score_value(score, facts) != user_entry.score:
        return None
    was_first = board.user_first
    board.user_first = True
    if was_first or not others:
        return None
    return SnipeByUser(others[0], user_entry)


def map_play_count(db: Session, beatmap_id: int) -> int:
    beatmap = db.get(Beatmap, beatmap_id)
    return beatmap.beatmapset.play_count if beatmap else 0


def watched_boards(db: Session, player: Player) -> list[MapBoard]:
    return list(db.scalars(select(MapBoard).where(MapBoard.player_id == player.id, MapBoard.user_first.is_(True))))
