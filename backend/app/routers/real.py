"""Plays made by hand in the local osu!stable client."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import RealPlay
from app.routers.players import get_player_or_404
from app.services import real_plays, stable_files

router = APIRouter(prefix="/api/players/{player_id}/real", tags=["real"])


class RealPlayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    beatmap_id: int
    beatmapset_id: int
    artist: str
    title: str
    difficulty_name: str
    mods: str
    accuracy: float
    max_combo: int
    misses: int
    stars: float
    pp: float
    played_at: datetime
    baseline: bool


class SyncOut(BaseModel):
    baseline: bool
    imported: int
    plays: list[RealPlayOut]


@router.post("/sync", response_model=SyncOut)
def sync(player_id: int, db: Session = Depends(get_db)) -> SyncOut:
    player = get_player_or_404(db, player_id)
    try:
        added = real_plays.sync(db, player)
    except stable_files.StableFileError as e:
        raise HTTPException(422, str(e)) from e
    db.commit()
    return SyncOut(baseline=bool(added) and added[0].baseline, imported=len(added),
                   plays=[RealPlayOut.model_validate(p) for p in added[-50:]])


@router.get("", response_model=list[RealPlayOut])
def list_plays(player_id: int, limit: int = 50, db: Session = Depends(get_db)) -> list[RealPlayOut]:
    get_player_or_404(db, player_id)
    rows = db.scalars(select(RealPlay).where(RealPlay.player_id == player_id)
                      .order_by(RealPlay.played_at.desc()).limit(min(limit, 200)))
    return [RealPlayOut.model_validate(r) for r in rows]
