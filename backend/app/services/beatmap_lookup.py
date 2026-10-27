"""Identify the client's beatmaps (lazer asks by the md5 of the .osu file) so it knows their online id and status.

Without an answer lazer wipes a map's online info and stops showing its leaderboard, so every map it asks about
gets one: from the index when the md5 is known, otherwise from the mirror (and the md5 is remembered). Maps the
mirror doesn't know (unsubmitted, edited files) are remembered for a day so client startups don't hammer it.
The status is the real one; whether a map exists yet on the career's date is the leaderboard's business.
"""
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Beatmap, BeatmapSet
from app.services import beatmap_index, mirror

UNKNOWN_RETRY_SECONDS = 24 * 3600

_unknown: dict[str, float] = {}
_outside_index: dict[str, dict] = {}  # md5 -> answer for maps the index doesn't keep (graveyard, other modes)


def _when(day) -> str | None:
    return f"{day.isoformat()}T00:00:00+00:00" if day else None


def _from_index(b: Beatmap, checksum: str | None) -> dict:
    bset: BeatmapSet = b.beatmapset
    return {
        "id": b.id, "beatmapset_id": bset.id, "checksum": checksum or b.checksum, "status": bset.status,
        "version": b.version, "difficulty_rating": b.stars, "mode_int": 0, "user_id": 0,
        "last_updated": _when(bset.ranked_date),
        "beatmapset": {"id": bset.id, "status": bset.status, "artist": bset.artist, "title": bset.title,
                       "creator": bset.creator, "ranked_date": _when(bset.ranked_date),
                       "submitted_date": _when(bset.ranked_date), "covers": {}},
    }


def _from_mirror(raw: dict, set_data: mirror.BeatmapSetData | None) -> dict:
    status = raw.get("status") or (set_data.status if set_data else "graveyard")
    ranked = _when(set_data.ranked_date) if set_data and set_data.ranked_date else raw.get("ranked")
    return {
        "id": raw["id"], "beatmapset_id": raw["beatmapset_id"], "checksum": raw.get("checksum"), "status": status,
        "version": raw.get("version") or "", "difficulty_rating": raw.get("difficulty_rating") or 0,
        "mode_int": raw.get("mode_int", 0), "user_id": raw.get("user_id") or 0,
        "last_updated": raw.get("last_updated"),
        "beatmapset": {"id": raw["beatmapset_id"], "status": status,
                       "artist": set_data.artist if set_data else "", "title": set_data.title if set_data else "",
                       "creator": set_data.creator if set_data else "",
                       "ranked_date": ranked if isinstance(ranked, str) else None,
                       "submitted_date": ranked if isinstance(ranked, str) else None, "covers": {}},
    }


def lookup(db: Session, checksum: str | None = None, beatmap_id: int | None = None,
           client: mirror.MirrorClient | None = None) -> dict | None:
    checksum = (checksum or "").lower() or None
    if checksum:
        b = db.scalar(select(Beatmap).where(Beatmap.checksum == checksum))
        if b is not None:
            return _from_index(b, checksum)
    elif beatmap_id:
        b = db.get(Beatmap, beatmap_id)
        return _from_index(b, None) if b is not None else None
    else:
        return None

    if checksum in _outside_index:
        return _outside_index[checksum]
    if time.time() - _unknown.get(checksum, 0) < UNKNOWN_RETRY_SECONDS:
        return None
    client = client or beatmap_index.default_client()
    try:
        raw = client.get_beatmap_by_md5(checksum)
        if raw is None:
            _unknown[checksum] = time.time()
            return None
        b = db.get(Beatmap, raw["id"])
        set_data = None
        if b is None:
            set_data = client.get_set(raw["beatmapset_id"])
            if set_data is not None:
                beatmap_index.upsert_set(db, set_data)  # stores ranked/approved/loved sets only
                b = db.get(Beatmap, raw["id"])
    except mirror.MirrorError:
        return None  # the mirror is down: no answer this time, lazer keeps what it had
    if b is not None:
        b.checksum = checksum
        db.commit()
        return _from_index(b, checksum)
    answer = _outside_index[checksum] = _from_mirror(raw, set_data)
    return answer
