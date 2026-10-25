from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.players import get_player_or_404
from app.schemas import ActionResultOut
from app.services import mentors

router = APIRouter(prefix="/api/players/{player_id}", tags=["mentors"])


class AskIn(BaseModel):
    npc_id: int


class SessionIn(BaseModel):
    hours: float = Field(default=2.0, ge=0.5, le=6)


class MentorSessionOut(BaseModel):
    action: ActionResultOut
    advice: str | None
    mentor: dict | None


@router.get("/mentor")
def get_mentor(player_id: int, db: Session = Depends(get_db)) -> dict:
    return mentors.overview(db, get_player_or_404(db, player_id))


@router.get("/mind")
def get_mind(player_id: int, db: Session = Depends(get_db)) -> dict:
    return mentors.mind(db, get_player_or_404(db, player_id))


@router.post("/mentor/ask")
def ask(player_id: int, body: AskIn, db: Session = Depends(get_db)) -> dict:
    player = get_player_or_404(db, player_id)
    try:
        result = mentors.ask(db, player, body.npc_id)
    except mentors.MentorError as e:
        raise HTTPException(e.status_code, str(e)) from e
    db.commit()
    return {**result, **mentors.overview(db, player)}


@router.post("/mentor/session", response_model=MentorSessionOut)
def session(player_id: int, body: SessionIn, db: Session = Depends(get_db)) -> MentorSessionOut:
    player = get_player_or_404(db, player_id)
    try:
        action, advice = mentors.session(db, player, body.hours)
    except mentors.MentorError as e:
        raise HTTPException(e.status_code, str(e)) from e
    return MentorSessionOut(action=action, advice=advice, mentor=mentors.state(player))


@router.post("/mentor/end")
def end(player_id: int, db: Session = Depends(get_db)) -> dict:
    player = get_player_or_404(db, player_id)
    try:
        mentors.end(db, player, "ended")
    except mentors.MentorError as e:
        raise HTTPException(e.status_code, str(e)) from e
    db.commit()
    return mentors.overview(db, player)
