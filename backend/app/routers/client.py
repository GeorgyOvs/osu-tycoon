"""API for the tycoon client (personal osu!lazer fork). It never talks to osu.ppy.sh, only to this backend."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import HandDay
from app.routers.players import get_player_or_404
from app.routers.real import RealPlayOut
from app.services import career_assist, character_play, client_scores, hand_play, osu_files, pp, profile

router = APIRouter(prefix="/api/client", tags=["client"])
players_router = APIRouter(prefix="/api/players", tags=["client"])


class ActivePlayerIn(BaseModel):
    player_id: int


class ActivePlayerOut(BaseModel):
    player_id: int | None
    name: str | None


class AssistOut(BaseModel):
    active: bool
    player_name: str | None = None
    od_delta: float = 0.0
    cs_delta: float = 0.0
    ar_delta: float = 0.0
    hp_delta: float = 0.0
    magnet: float = 0.0
    scale: float = 1.0
    condition: float = 1.0
    timing: float = 0.0
    aim: float = 0.0
    reading: float = 0.0
    physical: float = 0.0


class ClientScoreIn(BaseModel):
    client_score_id: str = Field(min_length=8, max_length=32)
    ruleset: str = "osu"
    beatmap_id: int = 0
    beatmap_md5: str = Field(default="", max_length=32)
    artist: str = ""
    title: str = ""
    version: str = ""
    mods: list[str] = []
    great: int = Field(ge=0)
    ok: int = Field(ge=0)
    meh: int = Field(ge=0)
    miss: int = Field(ge=0)
    max_combo: int = Field(ge=0)
    accuracy: float = Field(ge=0, le=1)  # lazer reports 0..1
    total_score: int = Field(ge=0)
    status: Literal["passed", "failed", "quit"]
    progress: float = 1.0
    played_at: datetime
    assist: dict[str, float] = {}  # the career modifiers the client actually applied


@router.get("/active-player", response_model=ActivePlayerOut)
def get_active(db: Session = Depends(get_db)) -> ActivePlayerOut:
    player = client_scores.active_player(db)
    return ActivePlayerOut(player_id=player.id if player else None, name=player.name if player else None)


@router.put("/active-player", response_model=ActivePlayerOut)
def set_active(body: ActivePlayerIn, db: Session = Depends(get_db)) -> ActivePlayerOut:
    player = get_player_or_404(db, body.player_id)
    client_scores.set_active_player(db, player)
    db.commit()
    return ActivePlayerOut(player_id=player.id, name=player.name)


@router.get("/assist", response_model=AssistOut)
def assist(db: Session = Depends(get_db)) -> AssistOut:
    """Difficulty adjustments for the next attempt, from the active career's stats and condition."""
    player = client_scores.active_player(db)
    if player is None:
        return AssistOut(active=False)
    out = AssistOut(active=True, player_name=player.name, **career_assist.as_dict(career_assist.for_career(db, player)))
    db.commit()  # default settings may have just been created
    return out


class AssistSettingsIn(BaseModel):
    scale: float = Field(ge=career_assist.MIN_SCALE, le=career_assist.MAX_SCALE)
    magnet: bool


class AssistSettingsOut(AssistSettingsIn):
    assist: AssistOut  # what the client will apply with these settings


def _settings_out(db: Session, player) -> AssistSettingsOut:
    settings = career_assist.settings_for(db, player)
    assist = career_assist.for_player(player, settings.scale, settings.magnet, hand_play.session_hours(db, player))
    return AssistSettingsOut(scale=settings.scale, magnet=settings.magnet,
                             assist=AssistOut(active=True, player_name=player.name, **career_assist.as_dict(assist)))


@players_router.get("/{player_id}/assist", response_model=AssistSettingsOut)
def get_settings(player_id: int, db: Session = Depends(get_db)) -> AssistSettingsOut:
    out = _settings_out(db, get_player_or_404(db, player_id))
    db.commit()
    return out


@players_router.put("/{player_id}/assist", response_model=AssistSettingsOut)
def put_settings(player_id: int, body: AssistSettingsIn, db: Session = Depends(get_db)) -> AssistSettingsOut:
    player = get_player_or_404(db, player_id)
    settings = career_assist.settings_for(db, player)
    settings.scale, settings.magnet = round(body.scale, 2), body.magnet
    out = _settings_out(db, player)
    db.commit()
    return out


class HandDayOut(BaseModel):
    hours: float
    attempts: int
    limit_hours: float  # the day closes by itself at this point
    blocked: str | None  # why hand plays can't count today, if they can't


class FinishedDayOut(BaseModel):
    start_date: datetime
    end_date: datetime
    events: list[dict]
    news: list[str]
    player: dict


def _hand_day_out(db: Session, player) -> HandDayOut:
    day = db.get(HandDay, player.id)
    return HandDayOut(hours=round(day.seconds / 3600, 3) if day else 0.0, attempts=day.attempts if day else 0,
                      limit_hours=round(hand_play.day_limit_hours(player), 2), blocked=hand_play.blocked(player))


def _finished_out(player, finished: hand_play.FinishedDay) -> FinishedDayOut:
    a = finished.action
    return FinishedDayOut(
        start_date=datetime.combine(a.start_date, datetime.min.time()),
        end_date=datetime.combine(a.end_date, datetime.min.time()),
        events=[{"date": e.date.isoformat(), "type": e.type, "message": e.message} for e in a.events],
        news=[getattr(n, "message", str(n)) for n in finished.news],
        player=profile.to_player_out(player).model_dump(mode="json"),
    )


@players_router.get("/{player_id}/hand-day", response_model=HandDayOut)
def hand_day(player_id: int, db: Session = Depends(get_db)) -> HandDayOut:
    return _hand_day_out(db, get_player_or_404(db, player_id))


@players_router.post("/{player_id}/hand-day/finish", response_model=FinishedDayOut)
def finish_hand_day(player_id: int, db: Session = Depends(get_db)) -> FinishedDayOut:
    player = get_player_or_404(db, player_id)
    finished = hand_play.finish(db, player)
    if finished is None:
        raise HTTPException(409, "nothing played by hand today")
    db.commit()
    return _finished_out(player, finished)


def _character_play(db: Session, beatmap_id: int, mods: str, seed: int | None, commit: bool) -> dict:
    player = client_scores.active_player(db)
    if player is None:
        raise HTTPException(409, "log in to a career first; the character of that career plays")
    try:
        result = character_play.simulate(db, player, beatmap_id, client_scores.known_mods(mods.split(",")), seed,
                                         commit=commit)
    except osu_files.BeatmapNotFound as e:
        raise HTTPException(404, str(e)) from e
    except pp.InvalidMods as e:
        raise HTTPException(422, str(e)) from e
    if commit:
        db.commit()
    else:
        db.rollback()  # watching never changes the career
    return result


@router.get("/character-play")
def watch_character_play(beatmap_id: int, mods: str = "", seed: int | None = None, db: Session = Depends(get_db)):
    """Watch one simulated attempt by the active career's character, object by object. Changes nothing."""
    return _character_play(db, beatmap_id, mods, seed, commit=False)


@router.post("/character-play")
def career_character_play(beatmap_id: int, mods: str = "", seed: int | None = None, attempts: int = 1,
                          db: Session = Depends(get_db)):
    """The character really plays: each attempt counts for the career (time, training, a score when it passes).
    With `attempts` > 1 it plays the map that many times in a row; the best attempt comes back for the replay."""
    if attempts <= 1:
        return _character_play(db, beatmap_id, mods, seed, commit=True)
    player = client_scores.active_player(db)
    if player is None:
        raise HTTPException(409, "log in to a career first; the character of that career plays")
    try:
        result = character_play.series(db, player, beatmap_id, client_scores.known_mods(mods.split(",")), attempts)
    except osu_files.BeatmapNotFound as e:
        raise HTTPException(404, str(e)) from e
    except pp.InvalidMods as e:
        raise HTTPException(422, str(e)) from e
    db.commit()
    return result



@router.post("/scores", response_model=RealPlayOut)
def submit(body: ClientScoreIn, db: Session = Depends(get_db)) -> RealPlayOut:
    if body.ruleset != "osu":
        raise HTTPException(422, "only osu!standard plays count for the career")
    try:
        row = client_scores.record(
            db, client_score_id=body.client_score_id, beatmap_id=body.beatmap_id, beatmap_md5=body.beatmap_md5,
            artist=body.artist, title=body.title, version=body.version, mods=body.mods, n300=body.great,
            n100=body.ok, n50=body.meh, misses=body.miss, max_combo=body.max_combo,
            accuracy=body.accuracy * 100, total_score=body.total_score, status=body.status,
            progress=body.progress, played_at=body.played_at, assist=body.assist,
        )
    except client_scores.NoActivePlayer as e:
        raise HTTPException(409, str(e)) from e
    db.commit()
    return RealPlayOut.model_validate(row)
