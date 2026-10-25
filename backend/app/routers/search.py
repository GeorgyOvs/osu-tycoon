from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Npc
from app.routers.players import get_player_or_404
from app.services import npc_profile, world_service

router = APIRouter(prefix="/api/players/{player_id}", tags=["search"])


def _npc(db: Session, player_id: int, npc_id: int):
    player = get_player_or_404(db, player_id)
    world_service.ensure_world(db, player)
    npc = db.get(Npc, npc_id)
    if npc is None or npc.player_id != player.id:
        raise HTTPException(404, "player not found in this world")
    return player, npc


@router.get("/search")
def search(player_id: int, q: str = Query(default="", max_length=64), db: Session = Depends(get_db)) -> dict:
    """Maps (ranked by the in-game date) and players of this world, for the Ctrl+K palette."""
    player = get_player_or_404(db, player_id)
    world_service.ensure_world(db, player)
    return npc_profile.search(db, player, q)


@router.get("/npcs/{npc_id}/osu-profile")
def osu_profile(player_id: int, npc_id: int, db: Session = Depends(get_db)) -> dict:
    player, npc = _npc(db, player_id, npc_id)
    out = npc_profile.profile(db, player, npc)
    db.commit()
    return out


@router.get("/npcs/{npc_id}/compare")
def compare(player_id: int, npc_id: int, db: Session = Depends(get_db)) -> dict:
    player, npc = _npc(db, player_id, npc_id)
    out = npc_profile.compare(db, player, npc)
    db.commit()
    return out


@router.get("/npc-by-name/{name}")
def by_name(player_id: int, name: str, db: Session = Depends(get_db)) -> dict:
    """Resolve a name seen in chat or on a leaderboard to an NPC id."""
    from sqlalchemy import select

    player = get_player_or_404(db, player_id)
    npc = db.scalar(select(Npc).where(Npc.player_id == player.id, Npc.name == name))
    if npc is None:
        raise HTTPException(404, f"no player called {name} in this world")
    return {"id": npc.id, "name": npc.name}
