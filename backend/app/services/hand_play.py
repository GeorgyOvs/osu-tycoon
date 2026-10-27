"""Plays made by hand in the tycoon client, as part of the career.

Every attempt (passed, failed or quit) costs in-game time and trains what the map demanded, like a session.
The time adds up into a "hand day": inside it the character tires through session hours (DayModifiers), and when
the day is finished (by the player, or automatically once it is long enough) the calendar moves on exactly as
after a simulated session. Passed plays on maps that exist on the career's date become career scores: pp, top
plays, the map's leaderboard, snipes and score posts. Relax and Autopilot count too; pp follows the real map, not
the career-adjusted (CR) one.
"""
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.engine import play, simulation
from app.models import HandDay, Player
from app.services import (
    beatmap_index,
    familiarity,
    integrity,
    life,
    media,
    osu_files,
    pp,
    profile,
    profile_stats,
    sessions,
    world_service,
)

AUTO_FINISH_HOURS = 4.0  # a long evening; after that the day closes by itself


@dataclass
class AttemptOutcome:
    counted: bool  # did the attempt touch the career at all
    reason: str | None = None  # why not, or why the score didn't count
    recorded: profile.Recorded | None = None
    day_finished: "FinishedDay | None" = None


@dataclass
class FinishedDay:
    action: simulation.ActionResult
    news: list = field(default_factory=list)  # what the rest of the world did that day


def state(db: Session, player: Player) -> HandDay:
    day = db.get(HandDay, player.id)
    if day is None:
        day = HandDay(player_id=player.id, seconds=0.0, play_seconds=0.0, attempts=0, targets={},
                      challenge_time=0.0, strain_time=0.0)
        db.add(day)
        db.flush()
    return day


def session_hours(db: Session, player: Player) -> float:
    day = db.get(HandDay, player.id)
    return day.seconds / 3600 if day else 0.0


def blocked(player: Player) -> str | None:
    """Why the character can't play at all today (injury, restriction, forced rest), if anything."""
    try:
        sessions.check_can_play(player)
        life.check_hours(player, 0.01)
    except (sessions.SessionError, life.LifeError) as e:
        return str(e)
    return None


def day_limit_hours(player: Player) -> float:
    return min(AUTO_FINISH_HOURS, life.free_hours(player, player.in_game_date) + life.MAX_SLEEP_TRADE)


def on_attempt(db: Session, player: Player, *, beatmap_id: int, mods: str, n300: int, n100: int, n50: int,
               misses: int, max_combo: int, accuracy: float, status: str, progress: float) -> AttemptOutcome:
    reason = blocked(player)
    if reason:
        return AttemptOutcome(False, reason)
    if beatmap_id <= 0:
        return AttemptOutcome(False, "this map isn't on the osu! website, the career can't know it")
    try:
        prof = sessions.map_profile(beatmap_id, mods)
        content = osu_files.get_osu_file(beatmap_id)
    except (osu_files.BeatmapNotFound, pp.InvalidMods, ValueError) as e:
        return AttemptOutcome(False, f"map unavailable: {e}")
    if not prof.objects:
        return AttemptOutcome(False, "map has no hit objects")

    passed = status == "passed"
    completion = 1.0 if passed else max(0.0, min(1.0, progress))
    seconds = prof.drain_seconds * completion

    day = state(db, player)
    day.seconds += seconds + sessions.ATTEMPT_OVERHEAD_S
    day.play_seconds += seconds
    day.attempts += 1
    played_objects = max(1, round(len(prof.objects) * completion))
    targets = dict(day.targets or {})
    for key, share in play.training_targets(prof, mods, played_objects).items():
        targets[key] = targets.get(key, 0.0) + share * seconds
    day.targets = targets
    day.challenge_time += seconds
    fast_streams = sum(1 for o in prof.objects if (o.stream_bpm or 0) > 200) / len(prof.objects)
    day.strain_time += (1 + 0.8 * fast_streams) * seconds

    profile_stats.add_play(player, seconds, n300 + n100 + n50, max_combo)
    familiarity.record_attempt(db, player, beatmap_id, completion)

    outcome = AttemptOutcome(True)
    rank_before = player.global_rank
    if passed:
        try:
            integrity.check_unrestricted(player)
            beatmap_index.check_playable(db, player.in_game_date, beatmap_id)
            perf = pp.calculate(content, mods, misses=misses, combo=max_combo, n100=n100, n50=n50)
            outcome.recorded = sessions.record_pass(
                db, player, beatmap_id, osu_files.parse_meta(beatmap_id, content), mods, prof, accuracy=accuracy,
                n300=n300, n100=n100, n50=n50, misses=misses, max_combo=max_combo, perf=perf, placements=[1])
        except (integrity.IntegrityError, beatmap_index.NotPlayable, pp.InvalidBeatmap) as e:
            outcome.reason = f"not a career score: {e}"
        if outcome.recorded is not None:
            media.after_action(db, player, rank_before)

    if day.seconds / 3600 >= day_limit_hours(player):
        outcome.day_finished = finish(db, player)
    return outcome


def finish(db: Session, player: Player) -> FinishedDay | None:
    """Close the hand day: training, fatigue and life, the calendar moves on one day and the world with it."""
    day = db.get(HandDay, player.id)
    if day is None or day.attempts == 0:
        return None
    rank_before = player.global_rank
    played = sessions.Played([], [], day.seconds, day.play_seconds, dict(day.targets or {}), day.challenge_time,
                             day.strain_time)
    action, _drill = sessions.finish_day(db, player, played)
    db.delete(day)
    db.flush()
    news = world_service.advance(db, player)
    media.after_action(db, player, rank_before, action.events, news)
    beatmap_index.syncer.request(player.in_game_date)
    return FinishedDay(action, news)
