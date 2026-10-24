"""Client for the osu.direct beatmap mirror (search sorted by ranked date, single lookups)."""

from dataclasses import dataclass
from datetime import date, datetime

import httpx

from app.config import MIRROR_API_URL, USER_AGENT

PAGE_SIZE = 100  # mirror maximum
STATUS_RANKED = 1
STATUS_APPROVED = 2
PP_STATUSES = {"ranked": STATUS_RANKED, "approved": STATUS_APPROVED}


class MirrorError(Exception):
    pass


@dataclass(frozen=True)
class BeatmapData:
    id: int
    version: str
    stars: float
    ar: float
    cs: float
    od: float
    hp: float
    bpm: float
    total_length: int
    hit_length: int
    max_combo: int | None
    count_circles: int
    count_sliders: int
    play_count: int
    pass_count: int


@dataclass(frozen=True)
class BeatmapSetData:
    id: int
    artist: str
    title: str
    creator: str
    source: str
    tags: str
    status: str
    ranked_date: date | None
    play_count: int
    favourite_count: int
    bpm: float
    beatmaps: list[BeatmapData]  # osu!standard difficulties only


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def parse_beatmap(raw: dict) -> BeatmapData:
    return BeatmapData(
        id=raw["id"],
        version=raw.get("version") or "",
        stars=float(raw.get("difficulty_rating") or 0),
        ar=float(raw.get("ar") or 0),
        cs=float(raw.get("cs") or 0),
        od=float(raw.get("accuracy") or 0),
        hp=float(raw.get("drain") or 0),
        bpm=float(raw.get("bpm") or 0),
        total_length=int(raw.get("total_length") or 0),
        hit_length=int(raw.get("hit_length") or 0),
        max_combo=raw.get("max_combo"),
        count_circles=int(raw.get("count_circles") or 0),
        count_sliders=int(raw.get("count_sliders") or 0),
        play_count=int(raw.get("playcount") or 0),
        pass_count=int(raw.get("passcount") or 0),
    )


def parse_set(raw: dict) -> BeatmapSetData:
    return BeatmapSetData(
        id=raw["id"],
        artist=raw.get("artist") or "",
        title=raw.get("title") or "",
        creator=raw.get("creator") or "",
        source=raw.get("source") or "",
        tags=raw.get("tags") or "",
        status=raw.get("status") or "",
        ranked_date=_parse_date(raw.get("ranked_date")),
        play_count=int(raw.get("play_count") or 0),
        favourite_count=int(raw.get("favourite_count") or 0),
        bpm=float(raw.get("bpm") or 0),
        beatmaps=[
            parse_beatmap(b)
            for b in raw.get("beatmaps") or []
            if b.get("mode_int") == 0 and not b.get("convert")
        ],
    )


class MirrorClient:
    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(
            base_url=MIRROR_API_URL, headers={"User-Agent": USER_AGENT}, timeout=30
        )

    def _get(self, path: str, params: dict | None = None):
        try:
            resp = self.http.get(path, params=params)
        except httpx.HTTPError as e:
            raise MirrorError(f"mirror request failed: {e}") from e
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise MirrorError(f"mirror returned {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as e:
            raise MirrorError("mirror returned invalid JSON") from e

    def search_page(self, status: int, offset: int) -> list[BeatmapSetData]:
        """One page of osu!standard sets with the given status, oldest ranked first."""
        data = self._get(
            "/v2/search",
            {
                "q": "",
                "mode": 0,
                "status": status,
                "sort": "ranked_date:asc",
                "amount": PAGE_SIZE,
                "offset": offset,
            },
        )
        if not isinstance(data, list):
            raise MirrorError(f"unexpected search response: {str(data)[:200]}")
        return [parse_set(raw) for raw in data]

    def get_set(self, set_id: int) -> BeatmapSetData | None:
        data = self._get(f"/v2/s/{set_id}")
        return parse_set(data) if data else None

    def get_set_for_beatmap(self, beatmap_id: int) -> BeatmapSetData | None:
        data = self._get(f"/v2/b/{beatmap_id}")
        if not data:
            return None
        return self.get_set(data["beatmapset_id"])
