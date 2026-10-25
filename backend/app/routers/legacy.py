from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.players import get_player_or_404
from app.services import economy, legacy

router = APIRouter(prefix="/api/players/{player_id}", tags=["legacy"])
hall = APIRouter(prefix="/api", tags=["legacy"])
LANG = Query(default="en", pattern="^(en|ru)$")


class MoneyIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)


class RetireIn(BaseModel):
    reason: str = "manual"


@router.get("/legacy")
def get_legacy(player_id: int, lang: str = LANG, db: Session = Depends(get_db)) -> dict:
    player = get_player_or_404(db, player_id)
    out = legacy.overview(db, player, lang)
    db.commit()
    return out


@router.post("/retire")
def retire(player_id: int, body: RetireIn | None = None, lang: str = LANG, db: Session = Depends(get_db)) -> dict:
    player = get_player_or_404(db, player_id)
    try:
        legacy.retire(db, player, "manual")
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    db.commit()
    return legacy.overview(db, player, lang)


@router.post("/economy/loan")
def loan(player_id: int, body: MoneyIn, db: Session = Depends(get_db)) -> dict:
    player = get_player_or_404(db, player_id)
    if not economy.realistic(player):
        raise HTTPException(409, "loans exist only with the realistic economy")
    try:
        economy.take_loan(player, body.amount, player.in_game_date)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    db.commit()
    return legacy.budget(player)


@router.post("/economy/repay")
def repay(player_id: int, body: MoneyIn, db: Session = Depends(get_db)) -> dict:
    player = get_player_or_404(db, player_id)
    try:
        economy.repay(player, body.amount, player.in_game_date)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    db.commit()
    return legacy.budget(player)


@hall.get("/hall-of-fame")
def hall_of_fame(db: Session = Depends(get_db)) -> list[dict]:
    return legacy.hall_of_fame(db)
