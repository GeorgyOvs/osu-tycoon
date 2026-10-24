from fastapi import APIRouter, HTTPException

from app.schemas import BeatmapInfo, PpRequest, PpResponse
from app.services import osu_files, pp

router = APIRouter(prefix="/api/pp", tags=["pp"])

PREVIEW_URL = "https://b.ppy.sh/preview/{beatmapset_id}.mp3"


def beatmap_info(meta: osu_files.BeatmapMeta) -> BeatmapInfo:
    return BeatmapInfo(
        beatmap_id=meta.beatmap_id,
        beatmapset_id=meta.beatmapset_id,
        artist=meta.artist,
        title=meta.title,
        version=meta.version,
        creator=meta.creator,
        preview_url=PREVIEW_URL.format(beatmapset_id=meta.beatmapset_id)
        if meta.beatmapset_id
        else None,
    )


def load_and_calculate(
    beatmap_id: int,
    mods: str,
    accuracy: float | None = None,
    misses: int = 0,
    combo: int | None = None,
    n100: int | None = None,
    n50: int | None = None,
) -> tuple[osu_files.BeatmapMeta, str, pp.PpResult]:
    """Fetch the beatmap and run the calculation, mapping failures to HTTP errors."""
    try:
        norm_mods = pp.normalize_mods(mods)
    except pp.InvalidMods as e:
        raise HTTPException(422, str(e)) from e

    try:
        content = osu_files.get_osu_file(beatmap_id)
    except osu_files.BeatmapNotFound as e:
        raise HTTPException(404, str(e)) from e

    try:
        result = pp.calculate(content, norm_mods, accuracy, misses, combo, n100, n50)
    except pp.InvalidBeatmap as e:
        raise HTTPException(422, str(e)) from e

    if combo is not None and combo > result.max_combo:
        raise HTTPException(422, f"combo {combo} exceeds beatmap max combo {result.max_combo}")
    return osu_files.parse_meta(beatmap_id, content), norm_mods, result


@router.post("/calculate", response_model=PpResponse)
def calculate(req: PpRequest) -> PpResponse:
    meta, mods, result = load_and_calculate(
        req.beatmap_id, req.mods, req.accuracy, req.misses, req.combo, req.n100, req.n50
    )
    return PpResponse(beatmap=beatmap_info(meta), mods=pp.display_mods(mods), **vars(result))
