"""The osu!-website side of a career: rank/pp history, ranked score, level, grades, play time, hits, the me! page."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine import scoring
from app.models import Npc, Player, ProfileSnapshot, Score
from app.services import ranking, story

MAX_POINTS = 160
ME_MAX = 2000


def snapshot(db: Session, player: Player) -> None:
    today = player.in_game_date
    row = db.scalar(select(ProfileSnapshot).where(ProfileSnapshot.player_id == player.id, ProfileSnapshot.date == today))
    if row is None:
        row = ProfileSnapshot(player_id=player.id, date=today)
        db.add(row)
    row.rank, row.pp, row.accuracy, row.play_count = player.global_rank, round(player.total_pp, 2), player.accuracy, player.play_count
    if story.get(player, "started_on") is None:
        story.put(player, "started_on", today.isoformat())
    db.flush()


def add_play(player: Player, seconds: float, hits: int = 0, combo: int = 0) -> None:
    story.put(player, "play_seconds", float(story.get(player, "play_seconds", 0.0)) + max(0.0, seconds))
    if hits:
        story.put(player, "total_hits", int(story.get(player, "total_hits", 0)) + hits)
    if combo > int(story.get(player, "max_combo", 0)):
        story.put(player, "max_combo", combo)


def score_for_level(n: int) -> float:
    """Total score needed to reach level n (osu!'s own curve)."""
    if n <= 100:
        return 5000 / 3 * (4 * n**3 - 3 * n**2 - n) + 1.25 * 1.8 ** (n - 60)
    return 26_931_190_827 + 99_999_999_999 * (n - 100)


def level(total_score: int) -> tuple[int, float]:
    n = 1
    while score_for_level(n + 1) <= total_score:
        n += 1
    lo, hi = score_for_level(n), score_for_level(n + 1)
    return n, max(0.0, min(1.0, (total_score - lo) / (hi - lo))) if hi > lo else 0.0


def grade(score: Score) -> str:
    return scoring.stable_grade(score.accuracy, score.misses, score.mods, score.map_max_combo or score.max_combo)


def history(db: Session, player: Player) -> list[dict]:
    rows = list(db.scalars(select(ProfileSnapshot).where(ProfileSnapshot.player_id == player.id).order_by(ProfileSnapshot.date)))
    if len(rows) > MAX_POINTS:
        step = len(rows) / MAX_POINTS
        rows = [rows[int(i * step)] for i in range(MAX_POINTS - 1)] + [rows[-1]]
    return [{"date": r.date.isoformat(), "rank": r.rank, "pp": round(r.pp, 1)} for r in rows]


def overview(db: Session, player: Player) -> dict:
    snapshot(db, player)
    scores = list(db.scalars(select(Score).where(Score.player_id == player.id)))
    best = ranking.top_plays(scores, limit=10**9)
    grades = {"XH": 0, "X": 0, "SH": 0, "S": 0, "A": 0}
    for s in best:
        g = grade(s)
        if g in grades:
            grades[g] += 1
    ranked_score = sum(s.score_value for s in best)
    total_score = sum(s.score_value for s in scores)
    lvl, progress = level(total_score)
    country_rank = None
    if player.global_rank:
        country_rank = 1 + (db.scalar(select(func.count()).select_from(Npc).where(
            Npc.player_id == player.id, Npc.country == player.country, Npc.rank.is_not(None), Npc.pp > player.total_pp)) or 0)
    peak = db.execute(select(ProfileSnapshot.rank, ProfileSnapshot.date).where(
        ProfileSnapshot.player_id == player.id, ProfileSnapshot.rank.is_not(None)).order_by(ProfileSnapshot.rank, ProfileSnapshot.date)
        .limit(1)).first()
    first_day = db.scalar(select(func.min(ProfileSnapshot.date)).where(ProfileSnapshot.player_id == player.id))
    started = story.get(player, "started_on")
    joined = min(filter(None, [date.fromisoformat(started) if started else None, first_day,
                               min((s.played_on for s in scores), default=None)]))
    max_combo = max([int(story.get(player, "max_combo", 0))] + [s.max_combo for s in scores])
    return {
        "joined": joined.isoformat(), "global_rank": player.global_rank, "country_rank": country_rank,
        "peak_rank": peak[0] if peak else None, "peak_date": peak[1].isoformat() if peak else None,
        "pp": round(player.total_pp, 2), "accuracy": round(player.accuracy, 2), "play_count": player.play_count,
        "ranked_score": ranked_score, "total_score": total_score, "level": lvl, "level_progress": round(progress, 3),
        "total_hits": int(story.get(player, "total_hits", 0)), "max_combo": max_combo,
        "play_time_seconds": int(story.get(player, "play_seconds", 0)), "grades": grades,
        "followers": player.followers, "me": story.get(player, "me", ""), "input_device": player.input_device,
        "tap_style": player.tap_style, "history": history(db, player),
    }


def set_me(player: Player, text: str) -> None:
    story.put(player, "me", text[:ME_MAX])
