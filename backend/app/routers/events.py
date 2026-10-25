from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import LifeEvent
from app.routers.players import get_player_or_404
from app.services import events

router = APIRouter(prefix="/api/players/{player_id}/events", tags=["events"])


class OptionOut(BaseModel):
    key: str
    label: str
    hint: str = ""


class LifeEventOut(BaseModel):
    id: int
    key: str
    category: str
    title: str
    body: str
    created_on: str
    expires_on: str | None
    status: str
    options: list[OptionOut]
    choice: str | None
    outcome: str
    applied: dict
    auto: bool
    default: str = ""


class EffectOut(BaseModel):
    label: str
    until: str
    days_left: int
    free_hours: float
    learning: float
    play: float


class EventsOut(BaseModel):
    pending: list[LifeEventOut]
    history: list[LifeEventOut]
    effects: list[EffectOut]


class ChooseIn(BaseModel):
    choice: str


def _out(event: LifeEvent, lang: str) -> LifeEventOut:
    d = events.present(event, lang)
    d["created_on"] = d["created_on"].isoformat()
    d["expires_on"] = d["expires_on"].isoformat() if d["expires_on"] else None
    return LifeEventOut(**d)


@router.get("", response_model=EventsOut)
def list_events(player_id: int, lang: str = Query(default="en", pattern="^(en|ru)$"),
                limit: int = Query(default=30, le=100), db: Session = Depends(get_db)) -> EventsOut:
    player = get_player_or_404(db, player_id)
    rows = events.history(db, player, limit + 10)
    return EventsOut(
        pending=[_out(e, lang) for e in reversed([e for e in rows if e.status == "pending"])],
        history=[_out(e, lang) for e in rows if e.status != "pending"][:limit],
        effects=[EffectOut(**e) for e in events.active_effects(player, lang)],
    )


@router.post("/{event_id}/choose", response_model=LifeEventOut)
def choose(player_id: int, event_id: int, body: ChooseIn, lang: str = Query(default="en", pattern="^(en|ru)$"),
          db: Session = Depends(get_db)) -> LifeEventOut:
    player = get_player_or_404(db, player_id)
    event = db.scalar(select(LifeEvent).where(LifeEvent.id == event_id, LifeEvent.player_id == player.id))
    if event is None:
        raise HTTPException(404, f"event {event_id} not found")
    try:
        events.resolve(db, player, event, body.choice)
    except events.EventError as e:
        raise HTTPException(e.status_code, str(e)) from e
    db.commit()
    return _out(event, lang)


@router.get("/count")
def count(player_id: int, db: Session = Depends(get_db)) -> dict[str, int]:
    return {"pending": events.pending_count(db, get_player_or_404(db, player_id))}
