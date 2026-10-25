from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.players import get_player_or_404
from app.services import map_hints, osu_files, pp

router = APIRouter(prefix="/api/players/{player_id}/maps", tags=["hints"])


class SkillOut(BaseModel):
    key: str
    label: str
    detail: str


class DimOut(BaseModel):
    key: str
    label: str
    need_comfort: list[int]
    need_pass: list[int]
    yours: int
    verdict: str
    verdict_label: str


class HintOut(BaseModel):
    beatmap_id: int
    mods: str
    stars: float
    bpm: float
    length: int
    main_skills: list[SkillOut]
    dims: list[DimOut]
    notes: list[str]
    precision: str
    precision_label: str
    experience: float


def slot_mods(mods: str) -> str:
    """Tournament slots and UI labels (NM, FM, TB) mean no forced mods."""
    cleaned = "".join(ch for ch in (mods or "").upper() if ch.isalpha())
    for token in ("NM", "FM", "TB"):
        cleaned = cleaned.replace(token, "")
    return pp.normalize_mods(cleaned)


@router.get("/{beatmap_id}/hint", response_model=HintOut)
def map_hint(player_id: int, beatmap_id: int, mods: str = "", lang: str = Query(default="en", pattern="^(en|ru)$"),
             db: Session = Depends(get_db)) -> HintOut:
    player = get_player_or_404(db, player_id)
    try:
        norm = slot_mods(mods)
        out = map_hints.hint(db, player, beatmap_id, norm, lang)
    except pp.InvalidMods as e:
        raise HTTPException(422, str(e)) from e
    except osu_files.BeatmapNotFound as e:
        raise HTTPException(404, str(e)) from e
    return HintOut(**out)
