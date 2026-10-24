"""1v1 duels: challenge any player in your world, see the pool, ban and pick, play."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Duel, Npc, Player
from app.routers.players import get_player_or_404
from app.schemas import DuelChallengeIn, DuelOut, MatchStrategyIn
from app.services import duels, world_service

router = APIRouter(prefix="/api/players/{player_id}/duels", tags=["duels"])


def _out(db: Session, d: Duel) -> DuelOut:
    npc = db.get(Npc, d.npc_id)
    return DuelOut(
        id=d.id, date=d.date, opponent=npc.name if npc else "?", opponent_country=npc.country if npc else "XX",
        opponent_rank=npc.rank if npc else None, kind=d.kind, best_of=d.best_of, bans_per_side=d.bans_per_side,
        difficulty=d.difficulty, status=d.status, pool=d.pool, maps=d.maps, score_user=d.score_user,
        score_npc=d.score_npc, won=d.won,
    )


def _player(db: Session, player_id: int) -> Player:
    player = get_player_or_404(db, player_id)
    world_service.ensure_world(db, player)
    return player


@router.post("", response_model=DuelOut)
def challenge(player_id: int, body: DuelChallengeIn, db: Session = Depends(get_db)) -> DuelOut:
    """Challenge someone. If they accept, the pool is drawn and shown; play it with POST /{id}/play."""
    player = _player(db, player_id)
    try:
        duel = duels.challenge(db, player, body.npc_id, body.best_of, body.kind, body.difficulty, body.bans_per_side)
    except duels.DuelError as e:
        db.commit()  # a declined challenge still leaves the NPC's DM
        raise HTTPException(e.status_code, str(e)) from e
    db.commit()
    return _out(db, duel)


@router.post("/{duel_id}/play", response_model=DuelOut)
def play(player_id: int, duel_id: int, body: MatchStrategyIn | None = None, db: Session = Depends(get_db)) -> DuelOut:
    player = _player(db, player_id)
    duel = db.get(Duel, duel_id)
    if duel is None or duel.player_id != player.id:
        raise HTTPException(404, "1v1 not found")
    strategy = {"bans": body.bans, "picks": body.picks} if body and (body.bans or body.picks) else None
    try:
        duels.play_duel(db, player, duel, strategy)
    except duels.DuelError as e:
        raise HTTPException(e.status_code, str(e)) from e
    db.commit()
    return _out(db, duel)


@router.get("", response_model=list[DuelOut])
def history(player_id: int, db: Session = Depends(get_db)) -> list[DuelOut]:
    player = _player(db, player_id)
    return [_out(db, d) for d in duels.history(db, player)]
