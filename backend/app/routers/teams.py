"""Teams and clans: the player's squad, invites, recruiting and scrims."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.players import get_player_or_404
from app.services import media, teams, world_service

router = APIRouter(prefix="/api/players/{player_id}/team", tags=["teams"])


class MemberOut(BaseModel):
    npc_id: int
    name: str
    country: str
    role: str
    bond: float
    rank: int | None
    pp: int
    overall: float
    status: str
    joined_on: date


class LogOut(BaseModel):
    date: str
    text: str


class PerksOut(BaseModel):
    learning_bonus_pct: float
    nerve_bonus_pct: float
    sponsor_monthly: int
    followers_weekly: int


class TeamOut(BaseModel):
    id: int
    name: str
    tag: str
    status: str
    founded_on: date
    chemistry: float
    reputation: float
    user_role: str
    channel: str
    size: int
    members: list[MemberOut]
    log: list[LogOut]
    ready_for_cup: bool
    scrim_today: bool
    last_scrim: date | None
    cups_won: int
    expires_on: str | None
    perks: PerksOut
    invited_by: str | None = None


class HistoryOut(BaseModel):
    name: str
    tag: str
    status: str
    founded_on: date
    left_on: str | None


class CupOut(BaseModel):
    id: int
    name: str
    start_date: date
    registration_opens: date
    registered: bool
    status: str
    size: int
    can_register: bool


class LimitsOut(BaseModel):
    max_size: int
    cup_size: int
    max_scrim_hours: float


class TeamStateOut(BaseModel):
    date: date
    team: TeamOut | None
    invite: TeamOut | None
    history: list[HistoryOut]
    cups: list[CupOut]
    can_found: bool
    found_blocker: str | None
    found_cost: float
    limits: LimitsOut


class FoundIn(BaseModel):
    name: str = Field(min_length=1, max_length=48)
    tag: str = Field(min_length=1, max_length=8)


class RecruitIn(BaseModel):
    npc_id: int


class ScrimIn(BaseModel):
    hours: float = Field(default=2.0, ge=0.5, le=4.0)


class RecruitOut(BaseModel):
    accepted: bool
    message: str
    state: TeamStateOut


class ScrimOut(BaseModel):
    hours: float
    chemistry_before: float
    chemistry: float
    message: str
    state: TeamStateOut


class CandidateOut(BaseModel):
    npc_id: int
    name: str
    country: str
    rank: int | None
    pp: int
    overall: float
    odds: float
    rival: bool
    strength: str
    refused_until: date | None


def _player(db: Session, player_id: int):
    player = get_player_or_404(db, player_id)
    world_service.ensure_world(db, player)
    return player


def _state(db: Session, player) -> TeamStateOut:
    return TeamStateOut(**teams.state(db, player))


def _guard(db: Session, fn, *args):
    try:
        return fn(*args)
    except teams.TeamError as e:
        db.rollback()
        raise HTTPException(e.status_code, str(e)) from e


@router.get("", response_model=TeamStateOut)
def get_team(player_id: int, db: Session = Depends(get_db)) -> TeamStateOut:
    return _state(db, _player(db, player_id))


@router.get("/candidates", response_model=list[CandidateOut])
def get_candidates(player_id: int, limit: int = Query(default=20, ge=1, le=60),
                   db: Session = Depends(get_db)) -> list[CandidateOut]:
    player = _player(db, player_id)
    return [CandidateOut(**c) for c in _guard(db, teams.candidates, db, player, limit)]


@router.post("/found", response_model=TeamStateOut)
def found(player_id: int, body: FoundIn, db: Session = Depends(get_db)) -> TeamStateOut:
    player = _player(db, player_id)
    rank_before = player.global_rank
    _guard(db, teams.found, db, player, body.name, body.tag)
    media.after_action(db, player, rank_before)
    db.commit()
    return _state(db, player)


@router.post("/invites/{team_id}/accept", response_model=TeamStateOut)
def accept(player_id: int, team_id: int, db: Session = Depends(get_db)) -> TeamStateOut:
    player = _player(db, player_id)
    _guard(db, teams.accept_invite, db, player, team_id)
    db.commit()
    return _state(db, player)


@router.post("/invites/{team_id}/decline", response_model=TeamStateOut)
def decline(player_id: int, team_id: int, db: Session = Depends(get_db)) -> TeamStateOut:
    player = _player(db, player_id)
    _guard(db, teams.decline_invite, db, player, team_id)
    db.commit()
    return _state(db, player)


@router.post("/recruit", response_model=RecruitOut)
def recruit(player_id: int, body: RecruitIn, db: Session = Depends(get_db)) -> RecruitOut:
    player = _player(db, player_id)
    accepted, message, _ = _guard(db, teams.recruit, db, player, body.npc_id)
    db.commit()
    return RecruitOut(accepted=accepted, message=message, state=_state(db, player))


@router.post("/kick", response_model=TeamStateOut)
def kick(player_id: int, body: RecruitIn, db: Session = Depends(get_db)) -> TeamStateOut:
    player = _player(db, player_id)
    _guard(db, teams.kick, db, player, body.npc_id)
    db.commit()
    return _state(db, player)


@router.post("/leave", response_model=TeamStateOut)
def leave(player_id: int, db: Session = Depends(get_db)) -> TeamStateOut:
    player = _player(db, player_id)
    _guard(db, teams.leave, db, player)
    db.commit()
    return _state(db, player)


@router.post("/scrim", response_model=ScrimOut)
def scrim(player_id: int, body: ScrimIn, db: Session = Depends(get_db)) -> ScrimOut:
    player = _player(db, player_id)
    result = _guard(db, teams.scrim, db, player, body.hours)
    db.commit()
    return ScrimOut(hours=result["hours"], chemistry_before=result["chemistry_before"], chemistry=result["chemistry"],
                    message=result["message"], state=_state(db, player))
