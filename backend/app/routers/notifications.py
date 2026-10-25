from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.players import get_player_or_404
from app.services import notifications, world_service

router = APIRouter(prefix="/api/players/{player_id}", tags=["notifications"])


class NotificationOut(BaseModel):
    id: str
    kind: str
    date: str
    message: str
    tab: str
    priority: int
    action: dict | None = None


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(player_id: int, lang: str = Query(default="en", pattern="^(en|ru)$"),
                       db: Session = Depends(get_db)) -> list[NotificationOut]:
    """Things worth a toast or the bell. Ids are stable, so the client shows each one once."""
    player = get_player_or_404(db, player_id)
    world_service.ensure_world(db, player)
    items = notifications.feed(db, player, lang)
    db.commit()
    return [NotificationOut(**i) for i in items]
