"""The career around the game: gear shop, playstyle, life situation, rivals."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.engine import gear, world
from app.models import Player
from app.routers.players import get_player_or_404
from app.models import Npc
from app.schemas import OccupationIn, PlayerOut, PlaystyleIn, RivalOut, ShopItemOut, ShopOut
from app.services import condition, life, profile, rivals, world_service

router = APIRouter(prefix="/api/players/{player_id}", tags=["life"])


def _shop(db: Session, player: Player) -> ShopOut:
    owned = {i.item_key: i for i in condition.inventory(db, player)}
    fx = condition.gear_effects(db, player)
    items = [
        ShopItemOut(
            key=i.key, name=i.name, category=i.category, year=i.year, month=i.month, until=i.until,
            price=i.price_on(player.in_game_date), launch_price=i.price, is_new=i.is_new(player.in_game_date),
            aim=i.aim, tapping=i.tapping,
            ar_cap=i.ar_cap, ergonomics=i.ergonomics, notes=i.notes, available=i.available(player.in_game_date),
            owned=i.key in owned, equipped=bool(owned.get(i.key) and owned[i.key].equipped),
        )
        for i in gear.CATALOG.values()
    ]
    return ShopOut(
        money=round(player.money, 2), input_device=player.input_device, ergonomics=player.ergonomics,
        effects={"aim": fx.aim, "tapping": fx.tapping, "ar_cap": fx.ar_cap, "missing": fx.missing},
        items=items,
    )


@router.get("/shop", response_model=ShopOut)
def shop(player_id: int, db: Session = Depends(get_db)) -> ShopOut:
    player = get_player_or_404(db, player_id)
    out = _shop(db, player)
    db.commit()
    return out


@router.post("/shop/{item_key}/buy", response_model=ShopOut)
def buy(player_id: int, item_key: str, db: Session = Depends(get_db)) -> ShopOut:
    player = get_player_or_404(db, player_id)
    try:
        condition.buy(db, player, item_key)
    except condition.ShopError as e:
        raise HTTPException(e.status_code, str(e)) from e
    db.commit()
    return _shop(db, player)


@router.post("/shop/{item_key}/equip", response_model=ShopOut)
def equip(player_id: int, item_key: str, db: Session = Depends(get_db)) -> ShopOut:
    player = get_player_or_404(db, player_id)
    try:
        condition.equip(db, player, item_key)
    except condition.ShopError as e:
        raise HTTPException(e.status_code, str(e)) from e
    db.commit()
    return _shop(db, player)


@router.post("/occupation", response_model=PlayerOut)
def set_occupation(player_id: int, body: OccupationIn, db: Session = Depends(get_db)) -> PlayerOut:
    player = get_player_or_404(db, player_id)
    try:
        life.set_occupation(player, body.occupation)
    except life.LifeError as e:
        raise HTTPException(e.status_code, str(e)) from e
    db.commit()
    return profile.to_player_out(player)


@router.post("/playstyle", response_model=PlayerOut)
def set_playstyle(player_id: int, body: PlaystyleIn, db: Session = Depends(get_db)) -> PlayerOut:
    """Switching device or tap style starts a long adaptation; the payoff comes later."""
    player = get_player_or_404(db, player_id)
    try:
        condition.set_playstyle(db, player, body.input_device, body.tap_style)
    except condition.ShopError as e:
        raise HTTPException(e.status_code, str(e)) from e
    db.commit()
    return profile.to_player_out(player)


@router.get("/rivals", response_model=list[RivalOut])
def list_rivals(player_id: int, db: Session = Depends(get_db)) -> list[RivalOut]:
    player = get_player_or_404(db, player_id)
    world_service.ensure_world(db, player)
    out = []
    for r in rivals.ensure_rivals(db, player):
        npc = db.get(Npc, r.npc_id)
        out.append(RivalOut(npc_id=npc.id, name=npc.name, country=npc.country, kind=npc.kind, rank=npc.rank,
                            overall=world.display_overall(npc.overall), heat=round(r.heat, 1), since=r.since, record=r.record))
    db.commit()
    return out
