from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.players import get_player_or_404
from app.services import spending

router = APIRouter(prefix="/api/players/{player_id}/spending", tags=["spending"])


class ChoiceOut(BaseModel):
    key: str
    label: str


class ItemOut(BaseModel):
    key: str
    icon: str
    kind: str
    name: str
    description: str
    perk: str
    price: int
    affordable: bool
    status: str
    reason: str
    cooldown_left: int
    days: int
    choices: list[ChoiceOut]


class CategoryOut(BaseModel):
    key: str
    name: str
    icon: str
    items: list[ItemOut]


class SubOut(BaseModel):
    key: str
    name: str
    price: int
    since: str
    months: int


class EffectOut(BaseModel):
    label: str
    days_left: int
    source: str


class SpendingOut(BaseModel):
    money: int
    categories: list[CategoryOut]
    subscriptions: list[SubOut]
    monthly_total: int
    effects: list[EffectOut]
    owned: list[str]


class BuyIn(BaseModel):
    choice: str | None = None


class BuyOut(BaseModel):
    key: str
    price: int
    choice: str | None
    applied: dict
    message: str
    message_ru: str
    extra: dict


class CancelOut(BaseModel):
    key: str
    message: str
    message_ru: str


@router.get("", response_model=SpendingOut)
def get_spending(player_id: int, lang: str = Query(default="en", pattern="^(en|ru)$"),
                 db: Session = Depends(get_db)) -> SpendingOut:
    return SpendingOut(**spending.overview(db, get_player_or_404(db, player_id), lang))


@router.post("/{key}/buy", response_model=BuyOut)
def buy(player_id: int, key: str, body: BuyIn | None = None, db: Session = Depends(get_db)) -> BuyOut:
    player = get_player_or_404(db, player_id)
    try:
        out = spending.buy(db, player, key, body.choice if body else None)
    except spending.SpendingError as e:
        db.rollback()
        raise HTTPException(e.status_code, str(e)) from e
    db.commit()
    return BuyOut(**out)


@router.post("/{key}/cancel", response_model=CancelOut)
def cancel(player_id: int, key: str, db: Session = Depends(get_db)) -> CancelOut:
    player = get_player_or_404(db, player_id)
    try:
        out = spending.cancel(db, player, key)
    except spending.SpendingError as e:
        raise HTTPException(e.status_code, str(e)) from e
    db.commit()
    return CancelOut(**out)
