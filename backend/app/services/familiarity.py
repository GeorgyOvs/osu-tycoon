"""Map knowledge: replaying a map builds muscle memory for it; time away fades it.

Real players farm by repetition, so the same map plays noticeably better on the 20th attempt
than on the first. Effects live in play.DayModifiers.familiarity.
"""

import math
from datetime import date

from sqlalchemy.orm import Session

from app.models import MapFamiliarity, Player

GAIN_PER_ATTEMPT = 0.15  # share of the remaining gap closed by one full attempt
DAILY_RETENTION = 0.985  # roughly halves after ~6-7 weeks without playing the map


def _decayed(row: MapFamiliarity, on: date) -> float:
    days = max(0, (on - row.last_played).days)
    return row.level * DAILY_RETENTION**days


MASTERY_ATTEMPTS = 70  # attempts for a map to be ~63% mastered; a couple of hundred make it "yours"
MASTERY_RETENTION = 0.9985  # long-term memory: halves after ~15 months away


def mastery_from(attempts: int, days_idle: int) -> float:
    """0..1: how deeply the map is learned. Slow to build and slow to fade, unlike day-to-day familiarity."""
    return (1 - math.exp(-attempts / MASTERY_ATTEMPTS)) * MASTERY_RETENTION ** max(0, days_idle)


def mastery(db: Session, player: Player, beatmap_id: int) -> float:
    row = db.get(MapFamiliarity, (player.id, beatmap_id))
    return mastery_from(row.attempts, (player.in_game_date - row.last_played).days) if row else 0.0


def level(db: Session, player: Player, beatmap_id: int) -> float:
    row = db.get(MapFamiliarity, (player.id, beatmap_id))
    return _decayed(row, player.in_game_date) if row else 0.0


def record_attempt(db: Session, player: Player, beatmap_id: int, completion: float) -> float:
    """Update after an attempt that got through `completion` (0..1) of the map. Returns the new level."""
    row = db.get(MapFamiliarity, (player.id, beatmap_id))
    if row is None:
        row = MapFamiliarity(player_id=player.id, beatmap_id=beatmap_id, level=0.0, attempts=0,
                             last_played=player.in_game_date)
        db.add(row)
        db.flush()  # sessions don't autoflush; make the row findable for the next attempt
    current = _decayed(row, player.in_game_date)
    row.level = current + (1 - current) * GAIN_PER_ATTEMPT * max(0.0, min(1.0, completion))
    row.attempts += 1
    row.last_played = player.in_game_date
    return row.level
