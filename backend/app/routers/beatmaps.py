from dataclasses import asdict
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Beatmap, BeatmapSet
from app.schemas import BeatmapOut, BeatmapSearchOut, BeatmapSetOut, IndexStatusOut
from app.services import beatmap_index

router = APIRouter(prefix="/api/beatmaps", tags=["beatmaps"])

PREVIEW_URL = "https://b.ppy.sh/preview/{set_id}.mp3"
COVER_URL = "https://assets.ppy.sh/beatmaps/{set_id}/covers/list.jpg"


def set_out(bset: BeatmapSet, diffs: list[Beatmap]) -> BeatmapSetOut:
    return BeatmapSetOut(
        id=bset.id,
        artist=bset.artist,
        title=bset.title,
        creator=bset.creator,
        source=bset.source,
        status=bset.status,
        ranked_date=bset.ranked_date,
        play_count=bset.play_count,
        favourite_count=bset.favourite_count,
        bpm=bset.bpm,
        preview_url=PREVIEW_URL.format(set_id=bset.id),
        cover_url=COVER_URL.format(set_id=bset.id),
        beatmaps=[BeatmapOut.model_validate(b) for b in diffs],
    )


@router.get("", response_model=BeatmapSearchOut)
def search(
    before: date,
    q: str = "",
    min_stars: float | None = Query(default=None, ge=0),
    max_stars: float | None = Query(default=None, ge=0),
    sort: Literal["ranked_desc", "ranked_asc", "plays", "favourites", "stars_desc", "stars_asc"] = "ranked_desc",
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> BeatmapSearchOut:
    synced = beatmap_index.synced_until(db)
    complete = synced is not None and synced >= before
    if not complete:
        beatmap_index.syncer.request(before)

    total, results = beatmap_index.search(db, before, q, min_stars, max_stars, sort, limit, offset)
    return BeatmapSearchOut(
        before=before,
        total=total,
        complete=complete,
        index=IndexStatusOut(**asdict(beatmap_index.syncer.status(db))),
        results=[set_out(s, d) for s, d in results],
    )


@router.get("/index", response_model=IndexStatusOut)
def index_status(db: Session = Depends(get_db)) -> IndexStatusOut:
    return IndexStatusOut(**asdict(beatmap_index.syncer.status(db)))
