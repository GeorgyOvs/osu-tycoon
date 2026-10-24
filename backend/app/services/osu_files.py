"""Fetching, caching and parsing metadata of .osu beatmap files."""

from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import MIRROR_BEATMAP_URL, OSU_CACHE_DIR, OSU_FILE_URL, USER_AGENT


class BeatmapNotFound(Exception):
    pass


@dataclass(frozen=True)
class BeatmapMeta:
    beatmap_id: int
    beatmapset_id: int | None
    artist: str
    title: str
    version: str
    creator: str


def _cache_path(beatmap_id: int) -> Path:
    return OSU_CACHE_DIR / f"{beatmap_id}.osu"


_MEMORY: dict[int, bytes] = {}
_MEMORY_LIMIT = 512  # files kept in RAM (a few MB); the disk cache keeps everything
_SETID_MISSES: set[int] = set()


def get_osu_file(beatmap_id: int) -> bytes:
    """Return the raw .osu file, downloading and caching it on first use."""
    cached = _MEMORY.get(beatmap_id)
    if cached is not None:
        return cached
    path = _cache_path(beatmap_id)
    if path.exists():
        return _remember(beatmap_id, path.read_bytes())

    try:
        resp = httpx.get(
            OSU_FILE_URL.format(beatmap_id=beatmap_id), timeout=15, follow_redirects=True
        )
    except httpx.HTTPError as e:
        raise BeatmapNotFound(f"failed to download beatmap {beatmap_id}: {e}") from e

    # osu.ppy.sh answers 200 with an empty body for unknown ids.
    if resp.status_code != 200 or not resp.content.lstrip().startswith(b"osu file format"):
        raise BeatmapNotFound(f"beatmap {beatmap_id} not found")

    OSU_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return _remember(beatmap_id, resp.content)


def _remember(beatmap_id: int, content: bytes) -> bytes:
    if len(_MEMORY) >= _MEMORY_LIMIT:
        _MEMORY.pop(next(iter(_MEMORY)))  # oldest first
    _MEMORY[beatmap_id] = content
    return content


def lookup_beatmapset_id(beatmap_id: int) -> int | None:
    """Old .osu files (format < v10) lack BeatmapSetID; ask a mirror. Best-effort, cached."""
    if beatmap_id in _SETID_MISSES:
        return None
    path = OSU_CACHE_DIR / f"{beatmap_id}.setid"
    if path.exists():
        cached = path.read_text().strip()
        return int(cached) if cached.isdigit() else None

    try:
        resp = httpx.get(
            MIRROR_BEATMAP_URL.format(beatmap_id=beatmap_id),
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        set_id = resp.json().get("beatmapset_id") if resp.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        _SETID_MISSES.add(beatmap_id)  # don't retry within this run
        return None

    if not isinstance(set_id, int):
        _SETID_MISSES.add(beatmap_id)
        return None
    OSU_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(str(set_id))
    return set_id


def parse_meta(beatmap_id: int, content: bytes) -> BeatmapMeta:
    fields: dict[str, str] = {}
    in_metadata = False
    for raw in content.decode("utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("["):
            if in_metadata:
                break
            in_metadata = line == "[Metadata]"
            continue
        if in_metadata and ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()

    set_id = fields.get("BeatmapSetID", "")
    return BeatmapMeta(
        beatmap_id=beatmap_id,
        beatmapset_id=int(set_id)
        if set_id.lstrip("-").isdigit() and int(set_id) > 0
        else lookup_beatmapset_id(beatmap_id),
        artist=fields.get("Artist", ""),
        title=fields.get("Title", ""),
        version=fields.get("Version", ""),
        creator=fields.get("Creator", ""),
    )
