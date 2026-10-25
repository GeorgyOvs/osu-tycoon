from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.players import get_player_or_404
from app.services import profile_stats

router = APIRouter(prefix="/api/players/{player_id}", tags=["profile"])


class HistoryPoint(BaseModel):
    date: str
    rank: int | None
    pp: float


class OsuProfileOut(BaseModel):
    joined: str
    global_rank: int | None
    country_rank: int | None
    peak_rank: int | None
    peak_date: str | None
    pp: float
    accuracy: float
    play_count: int
    ranked_score: int
    total_score: int
    level: int
    level_progress: float
    total_hits: int
    max_combo: int
    play_time_seconds: int
    grades: dict[str, int]
    followers: int
    me: str
    input_device: str
    tap_style: str
    history: list[HistoryPoint]


class MeIn(BaseModel):
    text: str = Field(default="", max_length=profile_stats.ME_MAX)


@router.get("/osu-profile", response_model=OsuProfileOut)
def osu_profile(player_id: int, db: Session = Depends(get_db)) -> OsuProfileOut:
    player = get_player_or_404(db, player_id)
    out = profile_stats.overview(db, player)
    db.commit()
    return OsuProfileOut(**out)


@router.put("/me", response_model=OsuProfileOut)
def set_me(player_id: int, body: MeIn, db: Session = Depends(get_db)) -> OsuProfileOut:
    player = get_player_or_404(db, player_id)
    profile_stats.set_me(player, body.text)
    out = profile_stats.overview(db, player)
    db.commit()
    return OsuProfileOut(**out)
