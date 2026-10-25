"""Mindlock bookkeeping: read the current block of a map, update it after every attempt."""

from sqlalchemy.orm import Session

from app.engine import mindlock as M
from app.models import MapBlock, Player


def current(db: Session, player: Player, beatmap_id: int, mastery: float = 0.0) -> tuple[int, float] | None:
    """(slice, effective severity) of an active block, or None."""
    row = db.get(MapBlock, (player.id, beatmap_id))
    if row is None or row.severity <= 0:
        return None
    severity = M.effective(M.faded(row.severity, (player.in_game_date - row.last_on).days), mastery)
    return (row.bucket, severity) if severity >= M.FORGET_BELOW else None


def spot_seconds(bucket: int, drain_seconds: float) -> float:
    return (bucket + 0.5) / M.BUCKETS * drain_seconds


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def record(db: Session, player: Player, beatmap_id: int, attempt, n_objects: int, drain_seconds: float,
           nerve: float, tilt_resilience: float) -> str | None:
    """Update after an attempt. Returns a key-moment note when something changed."""
    today = player.in_game_date
    row = db.get(MapBlock, (player.id, beatmap_id))
    if row is None:
        row = MapBlock(player_id=player.id, beatmap_id=beatmap_id, bucket=0, streak=0, severity=0.0, last_on=today, attempts=0)
        db.add(row)
        db.flush()
    row.severity = M.faded(row.severity, (today - row.last_on).days)
    row.last_on = today
    row.attempts += 1
    bucket = M.trouble_bucket(attempt, n_objects)
    when = _clock(spot_seconds(row.bucket if bucket is None else bucket, drain_seconds))
    rng = M.rng_for(player.seed, beatmap_id, row.attempts)
    note = None

    if row.severity > 0:  # an active block
        if bucket is not None and M.near(bucket, row.bucket):
            row.severity = min(1.0, row.severity + M.GROW)
            row.streak += 1
            note = f"Tensed up at {when} again."
        else:
            row.severity = max(0.0, row.severity - M.RELIEF * (1.5 if attempt.passed else 1.0))
            if rng.random() < M.CLICK_CHANCE:
                row.severity = 0.0
                note = f"Something clicked: the {_clock(spot_seconds(row.bucket, drain_seconds))} section no longer scares you."
            elif row.severity < M.FORGET_BELOW:
                row.severity, row.streak = 0.0, 0
                note = "You got past the spot you kept tensing up at."
    elif bucket is not None:
        row.streak = row.streak + 1 if (row.streak and M.near(bucket, row.bucket)) else 1
        row.bucket = bucket
        if rng.random() < M.onset_chance(row.streak, nerve, tilt_resilience):
            row.severity = M.INITIAL
            note = f"You start to tense up around {when}: that spot is in your head now."
    else:
        row.streak = 0
    if row.severity <= 0 and row.streak == 0:
        db.delete(row)
    db.flush()
    return note
