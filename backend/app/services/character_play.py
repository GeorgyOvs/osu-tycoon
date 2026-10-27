"""The character plays a map in the tycoon client: one simulated attempt, object by object, turned into a replay.

The attempt runs exactly like a career session (stats, gear, confidence, familiarity, mind blocks, today's
condition). With `commit` it IS a career attempt: it costs time in the day played in the client, trains, moves
confidence and map knowledge, and a pass becomes a career score (pp, top plays, the map's board). Without it, it
is only watched and nothing changes. The client gets each object's outcome and timing error and builds cursor
movement and key presses that reproduce them under its own hit windows.
"""
import random
import secrets
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import play, playstyle, psychology
from app.models import Player
from app.services import condition, familiarity, hand_play, mindlock, osu_files, pp, sessions

POINTS_TO_RESULT = {300: "great", 100: "ok", 50: "meh", 0: "miss"}
SLIDER_RESULT = {"b": "sliderbreak", "e": "sliderend"}  # the head was hit; a tick or the end was not


@dataclass(frozen=True)
class ObjectPlay:
    time: float  # beatmap ms (the client's clock), not real ms
    kind: str
    result: str  # great | ok | meh | miss | sliderbreak | sliderend
    error: float  # signed beatmap ms; 0 when untimed
    cause: str  # why it was missed (aim, tapping, reading, accuracy, nerves, stamina) or ''


def simulate(db: Session, player: Player, beatmap_id: int, mods: str, seed: int | None = None,
             commit: bool = False, restart: bool = False) -> dict:
    mods = pp.normalize_mods(mods)
    blocked = hand_play.blocked(player) if commit else None
    prof = sessions.map_profile(beatmap_id, mods)  # raises osu_files.BeatmapNotFound
    if not prof.objects:
        raise osu_files.BeatmapNotFound(f"beatmap {beatmap_id} has no hit objects")
    skills = condition.play_skills(db, player)
    skills = psychology.scale_skills(skills, psychology.confidence(player, psychology.family(prof, mods),
                                                                   player.in_game_date))
    day = sessions.day_modifiers(player)
    day.familiarity = familiarity.level(db, player, beatmap_id)
    day.mastery = familiarity.mastery(db, player, beatmap_id)
    day.session_hours = hand_play.session_hours(db, player)
    day.warmup = play.warmup(day.session_hours)  # the first attempts of the day are stiff
    counted = commit and blocked is None
    if counted:  # a real attempt also carries the map's mind block, like in a session
        block = mindlock.current(db, player, beatmap_id, day.mastery)
        day.block_bucket, day.block_severity = block if block else (None, 0.0)
    seed = seed if seed is not None else secrets.randbelow(2**31)
    rng = random.Random(f"watch:{player.seed}:{beatmap_id}:{seed}")
    attempt = play.simulate(prof, skills, mods, day, rng)
    if restart:
        attempt = play.restart_early(attempt, prof, rng)
    career = _commit(db, player, beatmap_id, mods, prof, skills, attempt) if counted else None

    rate = prof.clock_rate
    trace = attempt.trace
    objects = [
        ObjectPlay(time=round(o.time * rate, 1), kind=o.kind,
                   result=SLIDER_RESULT.get(trace.slider[i]) or POINTS_TO_RESULT[trace.points[i]],
                   error=round(trace.error[i] * rate, 1), cause=trace.cause[i])
        for i, o in enumerate(prof.objects[:len(trace.points)])
    ]
    values = {k: v for k, v in skills.items()}
    return {
        "player_name": player.name,
        "beatmap_id": beatmap_id,
        "mods": mods,
        "seed": seed,
        "passed": attempt.passed,
        "fail_index": attempt.fail_index,
        "accuracy": round(attempt.accuracy, 2),
        "grade": attempt.grade,
        "max_combo": attempt.max_combo,
        "misses": attempt.misses,
        "sliderbreaks": attempt.sliderbreaks,
        "restarted": attempt.restarted,
        "objects_total": len(prof.objects),
        "key_moments": attempt.key_moments,
        # 0..1 knobs for the cursor model; condition already folds in form, fatigue and tilt.
        "aim": round(min(1.0, A.composite(values, A.GROUPS_BY_KEY["aim"]) / 100), 3),
        "precision": round(min(1.0, values["precision"] / 100), 3),
        "stamina": round(min(1.0, values["hand_stamina"] / 100), 3),
        "nerves": round(min(1.0, values["nerve_resistance"] / 100), 3),
        "condition": round(day.capability(values["tilt_resilience"]), 3),
        "fatigue": round(player.fatigue / 100, 3),
        "style": playstyle.of_player(player, values),
        "objects": [vars(o) for o in objects],
        "counted": career is not None,
        "career_score_id": career.recorded.score.id if career and career.recorded else None,
        "pp": round(career.recorded.score.pp, 2) if career and career.recorded else None,
        "note": blocked or (career.reason if career else None),
    }


MAX_ATTEMPTS = 20


def _summary(result: dict) -> dict:
    keys = ("passed", "accuracy", "grade", "misses", "sliderbreaks", "restarted", "max_combo", "counted", "pp", "note")
    return {k: result[k] for k in keys} | {
        "progress": 1.0 if result["passed"] else round((result["fail_index"] or 0) / max(1, result["objects_total"]), 3),
        "key_moments": result["key_moments"][:2],
        # every pass comes with its plays, so the client can keep each one as a local score with its replay
        "objects": result["objects"] if result["passed"] else []}


def series(db: Session, player: Player, beatmap_id: int, mods: str, attempts: int) -> dict:
    """The character plays the map `attempts` times for the career, one real attempt after another (time,
    fatigue and the day's end apply as they go). Returns the best attempt in full, for the replay, and every
    attempt's summary. Stops early when the character can't play any more (a forced rest, for instance).
    Once the map is passed, the character plays for a better score and restarts attempts that break early."""
    results = []
    for _ in range(max(1, min(MAX_ATTEMPTS, attempts))):
        result = simulate(db, player, beatmap_id, mods, commit=True, restart=any(r["passed"] for r in results))
        db.flush()
        results.append(result)
        if not result["counted"]:
            break
    best = max(results, key=lambda r: (r["passed"], r["accuracy"] if r["passed"] else len(r["objects"])))
    return best | {"attempts": [_summary(r) for r in results], "best_index": results.index(best)}


def _commit(db: Session, player: Player, beatmap_id: int, mods: str, prof, skills: dict, attempt) -> hand_play.AttemptOutcome:
    """Make the simulated attempt part of the career, through the same path as a play made by hand."""
    note = mindlock.record(db, player, beatmap_id, attempt, len(prof.objects), prof.drain_seconds,
                           skills["nerve_resistance"], skills["tilt_resilience"])
    if note:
        attempt.key_moments.append(note)
    psychology.record_attempt(player, psychology.family(prof, mods), attempt.passed, attempt.choked, attempt.misses,
                              player.in_game_date)
    return hand_play.on_attempt(
        db, player, beatmap_id=beatmap_id, mods=mods, n300=attempt.n300, n100=attempt.n100, n50=attempt.n50,
        misses=attempt.misses, max_combo=attempt.max_combo, accuracy=attempt.accuracy,
        status="passed" if attempt.passed else "failed", progress=attempt.fail_progress or 0.0)
