"""Simulated play: sessions of ranked maps and pre-play assessments."""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.engine import play, psychology, simulation
from app.routers.career import days_until_match, world_events
from app.routers.players import get_player_or_404
from app.routers.pp import beatmap_info
from app.schemas import (
    AssessmentOut,
    AutoSessionRequest,
    PoolPracticeRequest,
    PresetOut,
    MapLeaderboardEntryOut,
    MapLeaderboardOut,
    FirstPlaceChangeOut,
    AttemptOut,
    EventOut,
    MapDemandOut,
    PlayOut,
    ScoreOut,
    SessionOut,
    SessionRequest,
    TimelineBucketOut,
)
from app.models import Player, SessionLog, Tournament
from app.engine import commentary
from app.services import (
    autoplay,
    beatmap_index,
    condition,
    familiarity,
    mindlock,
    leaderboards,
    media,
    osu_files,
    pp,
    profile,
    sessions,
    tournaments,
    world_service,
)

router = APIRouter(prefix="/api/players/{player_id}", tags=["play"])


def _attempt_out(ar: sessions.AttemptResult, player=None, r: sessions.PlayResult | None = None,
                 k: int = 0) -> AttemptOut:
    a = ar.attempt
    lines = []
    if player is not None and r is not None:
        ctx = {"player": player.name, "title": f"{r.meta.artist} - {r.meta.title}", "mods": r.mods, "stars": r.stars,
               "passed": a.passed, "accuracy": a.accuracy, "misses": a.misses, "grade": a.grade, "choked": a.choked}
        lines = commentary.play_lines(ar.replay, ctx, player.in_game_date,
                                      f"{player.seed}:{player.in_game_date}:{r.meta.beatmap_id}:{k}")
    return AttemptOut(
        passed=a.passed,
        fail_progress=a.fail_progress,
        fail_time=a.fail_time,
        n300=a.n300,
        n100=a.n100,
        n50=a.n50,
        misses=a.misses,
        max_combo=a.max_combo,
        accuracy=a.accuracy,
        grade=a.grade,
        pp=ar.pp,
        choked=a.choked,
        miss_causes=a.miss_causes,
        key_moments=a.key_moments,
        timeline=[TimelineBucketOut(**asdict(b)) for b in a.timeline],
        replay=ar.replay,
        commentary=lines,
    )


@router.post("/sessions", response_model=SessionOut)
def play_session(player_id: int, body: SessionRequest, db: Session = Depends(get_db)) -> SessionOut:
    player = get_player_or_404(db, player_id)
    requests = [sessions.PlayRequest(p.beatmap_id, p.mods, p.attempts) for p in body.plays]
    return _run_session(db, player, requests, body.stream, mode="manual")


@router.get("/presets", response_model=list[PresetOut])
def presets(player_id: int, db: Session = Depends(get_db)) -> list[PresetOut]:
    player = get_player_or_404(db, player_id)
    return [PresetOut(key=p.key, label=p.label, description=p.description, mods=p.mods or "NM",
                      available=autoplay.available(p, player)) for p in autoplay.PRESETS.values()]


@router.post("/sessions/auto", response_model=SessionOut)
def auto_session(player_id: int, body: AutoSessionRequest, db: Session = Depends(get_db)) -> SessionOut:
    """A session from a preset: the engine picks maps around the player's level for the given hours."""
    player = get_player_or_404(db, player_id)
    preset = autoplay.PRESETS.get(body.preset)
    if preset is None:
        raise HTTPException(422, f"unknown preset '{body.preset}'")
    if not autoplay.available(preset, player):
        raise HTTPException(409, f"{preset.label} isn't a thing yet in {player.in_game_date.year}")
    requests = autoplay.plan_session(db, player, preset, body.hours)
    if not requests:
        raise HTTPException(409, "no suitable maps indexed yet for this preset; the index may still be syncing")
    return _run_session(db, player, requests, body.stream,
                        replay={"preset": body.preset, "hours": body.hours, "stream": body.stream})


@router.post("/sessions/pool", response_model=SessionOut)
def practice_pool(player_id: int, body: PoolPracticeRequest, db: Session = Depends(get_db)) -> SessionOut:
    """Grind a released tournament pool with its mods; familiarity carries straight into the match."""
    player = get_player_or_404(db, player_id)
    t = db.get(Tournament, body.tournament_id)
    if t is None or t.player_id != player.id:
        raise HTTPException(404, "tournament not found")
    slots = [s for s in tournaments.pool_for(t, body.week) if s.beatmap_id]
    if not slots:
        raise HTTPException(409, "that pool hasn't been released yet")
    rounds = max(1, round(body.hours * 3600 / (len(slots) * (180 + sessions.ATTEMPT_OVERHEAD_S))))
    requests = [sessions.PlayRequest(s.beatmap_id, s.mods, rounds) for s in slots]
    return _run_session(db, player, requests, body.stream)


def _run_session(db: Session, player: Player, requests: list[sessions.PlayRequest], stream: bool = False,
                 mode: str = "auto", replay: dict | None = None) -> SessionOut:
    date = player.in_game_date
    days_until_match(db, player, 1)
    rank_before = player.global_rank
    try:
        result = sessions.run_session(db, player, requests, stream)
    except sessions.SessionError as e:
        db.rollback()
        raise HTTPException(e.status_code, str(e)) from e
    except simulation.TrainingBlocked as e:
        db.rollback()
        raise HTTPException(409, str(e)) from e
    news = world_service.advance(db, player)
    media.after_action(db, player, rank_before, result.action.events, news)
    db.commit()
    beatmap_index.syncer.request(player.in_game_date)

    out = SessionOut(
        date=date,
        hours=result.hours,
        plays=[
            PlayOut(
                beatmap=beatmap_info(r.meta),
                mods=pp.display_mods(r.mods),
                stars=r.stars,
                attempts=[_attempt_out(a, player, r, k) for k, a in enumerate(r.attempts)],
                best_index=r.best_index,
                score=ScoreOut.model_validate(r.recorded.score) if r.recorded else None,
                is_new_top_play=bool(r.recorded and r.recorded.top_play_position is not None),
                top_play_position=r.recorded.top_play_position if r.recorded else None,
                pp_gained=r.recorded.pp_gained if r.recorded else 0.0,
                previous_best_pp=r.recorded.previous_best_pp if r.recorded else None,
                board_rank=r.recorded.board_rank if r.recorded else None,
                board_size=r.recorded.board_size if r.recorded else None,
            )
            for r in result.plays
        ],
        training=result.training,
        events=[EventOut(date=e.date, type=e.type, message=e.message, data=e.data) for e in result.action.events]
        + world_events(news),
        deltas=result.action.deltas,
        player=profile.to_player_out(player),
    )
    _log_session(db, player, out, mode, replay)
    return out


HISTORY_KEEP = 40


def _log_session(db: Session, player: Player, out: SessionOut, mode: str, replay: dict | None = None) -> None:
    payload = out.model_dump(mode="json")
    if replay:
        payload["_replay"] = replay  # how to run the same preset again
    db.add(SessionLog(player_id=player.id, mode=mode, date=out.date, payload=payload))
    db.flush()
    old = list(db.scalars(select(SessionLog.id).where(SessionLog.player_id == player.id)
                          .order_by(SessionLog.id.desc()).offset(HISTORY_KEEP)))
    if old:
        db.execute(delete(SessionLog).where(SessionLog.id.in_(old)))
    db.commit()


class SessionHistoryItem(BaseModel):
    id: int
    mode: str
    result: SessionOut
    preset: str | None = None
    hours: float | None = None
    stream: bool = False


@router.get("/sessions/history", response_model=list[SessionHistoryItem])
def session_history(player_id: int, limit: int = 20, db: Session = Depends(get_db)) -> list[SessionHistoryItem]:
    """The last play sessions (newest first), so the history survives reloads."""
    player = get_player_or_404(db, player_id)
    rows = db.scalars(select(SessionLog).where(SessionLog.player_id == player.id)
                      .order_by(SessionLog.id.desc()).limit(min(limit, HISTORY_KEEP)))
    return [SessionHistoryItem(id=r.id, mode=r.mode, result=SessionOut.model_validate(r.payload),
                               **{k: v for k, v in (r.payload.get("_replay") or {}).items() if k in ("preset", "hours", "stream")})
            for r in rows]


@router.get("/assess/{beatmap_id}", response_model=AssessmentOut)
def assess(player_id: int, beatmap_id: int, mods: str = "", db: Session = Depends(get_db)) -> AssessmentOut:
    """How would the player fare on this map today? (Monte Carlo over simulated attempts.)"""
    player = get_player_or_404(db, player_id)
    try:
        norm = pp.normalize_mods(mods)
        prof = sessions.map_profile(beatmap_id, norm)
        meta = osu_files.parse_meta(beatmap_id, osu_files.get_osu_file(beatmap_id))
    except pp.InvalidMods as e:
        raise HTTPException(422, str(e)) from e
    except osu_files.BeatmapNotFound as e:
        raise HTTPException(404, str(e)) from e
    if not prof.objects:
        raise HTTPException(422, "beatmap has no hit objects")

    seed = f"{player.seed}:{player.in_game_date.isoformat()}:assess:{beatmap_id}:{norm}"
    day = sessions.day_modifiers(player)
    day.familiarity = familiarity.level(db, player, beatmap_id)
    day.mastery = familiarity.mastery(db, player, beatmap_id)
    block = mindlock.current(db, player, beatmap_id, day.mastery)
    day.block_bucket, day.block_severity = block if block else (None, 0.0)
    fam = psychology.family(prof, norm)
    conf = psychology.confidence(player, fam, player.in_game_date)
    a = play.assess(prof, psychology.scale_skills(condition.play_skills(db, player), conf), norm, day, seed)
    return AssessmentOut(
        beatmap=beatmap_info(meta),
        mods=pp.display_mods(norm),
        map=MapDemandOut(
            stars=prof.stars, aim=prof.aim, speed=prof.speed, ar=prof.ar, od=prof.od, cs=prof.cs, hp=prof.hp,
            bpm=prof.bpm, drain_seconds=prof.drain_seconds, max_combo=prof.max_combo,
            fastest_stream_bpm=prof.fastest_stream_bpm, longest_stream=prof.longest_stream,
        ),
        pass_rate=a.pass_rate,
        fc_rate=a.fc_rate,
        median_accuracy=a.median_accuracy,
        median_misses=a.median_misses,
        peak_ratios=a.peak_ratios,
        weakest=a.weakest,
        familiarity=day.familiarity,
        mastery=day.mastery,
        block=({"at_seconds": round(mindlock.spot_seconds(block[0], prof.drain_seconds)), "severity": round(block[1], 2)}
               if block else None),
        family=fam,
        confidence=round(conf, 2),
    )


@router.get("/beatmaps/{beatmap_id}/leaderboard", response_model=MapLeaderboardOut)
def map_leaderboard(player_id: int, beatmap_id: int, limit: int = 50, db: Session = Depends(get_db)) -> MapLeaderboardOut:
    """The map's top scores as of the player's in-game date (simulated forward on first view)."""
    player = get_player_or_404(db, player_id)
    world_service.ensure_world(db, player)
    try:
        leaderboards.ensure_board(db, player, beatmap_id)
        entries = leaderboards.board_entries(db, player, beatmap_id, min(limit, 100))
    except beatmap_index.NotPlayable as e:
        raise HTTPException(e.status_code, str(e)) from e
    except osu_files.BeatmapNotFound as e:
        raise HTTPException(404, str(e)) from e
    db.commit()
    you = next((e for e in entries if e.kind == "user"), None)
    return MapLeaderboardOut(
        beatmap_id=beatmap_id, date=player.in_game_date,
        entries=[MapLeaderboardEntryOut(**vars(e)) for e in entries],
        user_rank=you.rank if you else None,
        record_history=[MapLeaderboardEntryOut(**vars(e)) for e in leaderboards.record_history(db, player, beatmap_id)],
        first_place_history=[FirstPlaceChangeOut(**c) for c in leaderboards.first_place_history(db, player, beatmap_id)],
    )
