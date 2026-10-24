"""Performance calculation via rosu-pp."""

from dataclasses import dataclass

import rosu_pp_py as rosu

from app.config import PP_LAZER

# osu!stable mods, in the order the client displays them.
MOD_ORDER = ["NF", "EZ", "TD", "HD", "HR", "SD", "PF", "DT", "NC", "HT", "RX", "AP", "FL", "SO"]
_INCOMPATIBLE = [({"EZ"}, {"HR"}), ({"DT", "NC"}, {"HT"}), ({"NF"}, {"SD", "PF"})]


class InvalidMods(ValueError):
    pass


class InvalidBeatmap(ValueError):
    pass


def normalize_mods(mods: str | None) -> str:
    """Turn user input like 'hd,dt', 'HD DT', 'NM' into canonical 'HDDT' ('' for nomod)."""
    cleaned = "".join(ch for ch in (mods or "").upper() if ch.isalpha())
    if cleaned in ("", "NM", "NOMOD"):
        return ""
    if len(cleaned) % 2:
        raise InvalidMods(f"cannot parse mods '{mods}'")

    found = {cleaned[i : i + 2] for i in range(0, len(cleaned), 2)}
    unknown = found - set(MOD_ORDER)
    if unknown:
        raise InvalidMods(f"unknown mods: {', '.join(sorted(unknown))}")
    for left, right in _INCOMPATIBLE:
        if found & left and found & right:
            raise InvalidMods(f"incompatible mods: {''.join(sorted(found & (left | right)))}")

    # NC implies DT and PF implies SD; keep only the stronger one like the client does.
    if "NC" in found:
        found.discard("DT")
    if "PF" in found:
        found.discard("SD")
    return "".join(m for m in MOD_ORDER if m in found)


def display_mods(mods: str) -> str:
    return mods or "NM"


@dataclass(frozen=True)
class PpResult:
    pp: float
    pp_aim: float
    pp_speed: float
    pp_accuracy: float
    stars: float
    aim_difficulty: float
    speed_difficulty: float
    max_combo: int
    ar: float
    od: float
    cs: float
    hp: float
    bpm: float


def calculate(
    osu_file: bytes,
    mods: str = "",
    accuracy: float | None = None,
    misses: int = 0,
    combo: int | None = None,
    n100: int | None = None,
    n50: int | None = None,
) -> PpResult:
    """Calculate stable PP for a play. `mods` must already be normalized."""
    try:
        beatmap = rosu.Beatmap(bytes=osu_file)
    except Exception as e:  # rosu raises ParseError, but be defensive about the file
        raise InvalidBeatmap(str(e)) from e
    # rosu happily parses garbage into an empty map.
    if beatmap.n_objects == 0:
        raise InvalidBeatmap("beatmap has no hit objects")
    if beatmap.mode != rosu.GameMode.Osu:
        raise InvalidBeatmap("only osu!standard beatmaps are supported")
    if beatmap.is_suspicious():
        raise InvalidBeatmap("beatmap looks like a stress test, refusing to calculate")

    perf = rosu.Performance(mods=mods, misses=misses, lazer=PP_LAZER)
    if accuracy is not None:
        perf.set_accuracy(accuracy)
    if combo is not None:
        perf.set_combo(combo)
    if n100 is not None:
        perf.set_n100(n100)
    if n50 is not None:
        perf.set_n50(n50)

    attrs = perf.calculate(beatmap)
    diff = attrs.difficulty
    map_attrs = rosu.BeatmapAttributesBuilder(map=beatmap, mods=mods).build()

    return PpResult(
        pp=attrs.pp,
        pp_aim=attrs.pp_aim or 0.0,
        pp_speed=attrs.pp_speed or 0.0,
        pp_accuracy=attrs.pp_accuracy or 0.0,
        stars=diff.stars,
        aim_difficulty=diff.aim or 0.0,
        speed_difficulty=diff.speed or 0.0,
        max_combo=diff.max_combo,
        ar=map_attrs.ar,
        od=map_attrs.od,
        cs=map_attrs.cs,
        hp=map_attrs.hp,
        bpm=beatmap.bpm * map_attrs.clock_rate,
    )
