"""Map skill hints: what a map tests and roughly how good you need to be, read with your experience.

The map part is objective and cached per beatmap+mods: the play simulation is run (NoFail, neutral day)
for uniform skill levels 10..110 and, per dimension, we find the level where the hardest moment sits at a
comfortable (peak ratio 0.9) or a just-passable (1.15) load. The personal part places you on the same scale
(the uniform level that matches your own peak ratio) and blurs the numbers by experience: a newcomer reads a
map vaguely and sometimes wrongly, a veteran sees it precisely and notices the details.
"""

import math
import random
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import play, simulation
from app.engine.map_analysis import MapProfile
from app.models import Duel, Match, Player, Tournament, TournamentEntry
from app.services import condition, familiarity, sessions

GRID = [1, 5] + list(range(10, 115, 10))
COMFORT, PASS = 0.9, 1.15
STAMINA_COMFORT, STAMINA_PASS = 1.03, 1.12
DIMS = ("aim", "tapping", "reading", "stamina")

TEXT = {
    "en": {
        "aim": "Aim", "tapping": "Tapping", "reading": "Reading", "stamina": "Stamina",
        "comfortable": "comfortable", "passable": "passable", "over": "over your head",
        "rough": "rough", "decent": "decent", "sharp": "sharp",
        "jumps": "jumps", "jumps_v": "hard jumps", "jumps_d": "jumps at {bpm} BPM", "wide": "wide jumps",
        "burst": "bursts", "burst_d": "bursts up to {n} notes @ {bpm} BPM",
        "streams": "streams", "streams_v": "long streams", "streams_d": "{n}-note streams @ {bpm} BPM",
        "high_ar": "high AR", "high_ar_d": "AR{ar} reading", "low_ar": "dense low-AR reading", "low_ar_d": "AR{ar} density reading",
        "hidden": "Hidden reading", "sv": "slider velocity changes", "angles": "awkward angles", "rhythm": "tricky rhythm",
        "strict": "strict timing", "strict_d": "OD{od} timing", "small": "small circles", "small_d": "CS{cs} circles",
        "long": "a long map", "long_d": "{m}:{s:02d} of drain",
        "n_hr_ar": "HR makes this AR{ar}", "n_dt": "DT: {bpm} BPM effective", "n_long": "tiebreaker-length stamina test",
        "n_hp": "HP drain is harsh: chokes hurt", "n_fam": "you know this map, it plays a bit easier",
        "n_rough": "Hard to tell how hard this really is yet: play more to read maps better.",
    },
    "ru": {
        "aim": "Аим", "tapping": "Тэппинг", "reading": "Ридинг", "stamina": "Выносливость",
        "comfortable": "комфортно", "passable": "пройти можно", "over": "пока не по силам",
        "rough": "навскидку", "decent": "неплохо", "sharp": "точно",
        "jumps": "прыжки", "jumps_v": "сложные прыжки", "jumps_d": "прыжки на {bpm} BPM", "wide": "дальние прыжки",
        "burst": "бёрсты", "burst_d": "бёрсты до {n} нот на {bpm} BPM",
        "streams": "стримы", "streams_v": "длинные стримы", "streams_d": "стримы по {n} нот на {bpm} BPM",
        "high_ar": "высокий AR", "high_ar_d": "ридинг на AR{ar}", "low_ar": "плотный ридинг на низком AR", "low_ar_d": "плотный ридинг на AR{ar}",
        "hidden": "ридинг с Hidden", "sv": "смены скорости слайдеров", "angles": "неудобные углы", "rhythm": "сложный ритм",
        "strict": "строгий тайминг", "strict_d": "тайминг на OD{od}", "small": "маленькие круги", "small_d": "круги CS{cs}",
        "long": "длинная карта", "long_d": "{m}:{s:02d} драина",
        "n_hr_ar": "HR делает тут AR{ar}", "n_dt": "DT: фактически {bpm} BPM", "n_long": "проверка выносливости как на тайбрейкере",
        "n_hp": "жёсткий HP-драин: ошибки дорого стоят", "n_fam": "вы знаете эту карту, она играется чуть легче",
        "n_rough": "Пока трудно понять, насколько она сложна: чем больше играете, тем точнее читаете карты.",
    },
}


def _neutral() -> play.DayModifiers:
    return play.DayModifiers(form=0.0, fatigue=0.0, motivation=80.0)


def _peaks(profile: MapProfile, skills: dict[str, float], mods: str) -> dict[str, float]:
    attempt = play.simulate(profile, skills, mods + "NF", _neutral(), random.Random("hint"))
    return {k: attempt.peak_ratios[k] for k in DIMS}


def _crossing(levels: list[int], values: list[float], target: float) -> float:
    """The level where a decreasing peak ratio drops to `target` (interpolated on the grid)."""
    if values[0] <= target:
        return float(levels[0])
    for (l0, v0), (l1, v1) in zip(zip(levels, values), zip(levels[1:], values[1:])):
        if v1 <= target < v0 or v0 <= target < v1:
            return l0 + (v0 - target) / (v0 - v1) * (l1 - l0) if v0 != v1 else float(l1)
    return float(levels[-1]) + 10.0  # beyond the scale


def _placement(levels: list[int], values: list[float], ratio: float) -> float:
    """Your 'uniform-equivalent' level on this map: where the reference curve meets your own peak ratio."""
    return _crossing(levels, values, ratio)


@dataclass(frozen=True)
class MapRead:
    curves: dict[str, tuple[float, ...]]
    comfort: dict[str, float]
    passing: dict[str, float]
    features: dict
    stars: float
    bpm: float
    length: int


@lru_cache(maxsize=256)
def analyse(beatmap_id: int, mods: str) -> MapRead:
    profile = sessions.map_profile(beatmap_id, mods)
    curves: dict[str, list[float]] = {k: [] for k in DIMS}
    for level in GRID:
        peaks = _peaks(profile, {k: float(level) for k in A.SUBSTATS}, mods)
        for k in DIMS:
            curves[k].append(peaks[k])
    comfort, passing = {}, {}
    for k in DIMS:
        lo_target, hi_target = (STAMINA_COMFORT, STAMINA_PASS) if k == "stamina" else (COMFORT, PASS)
        comfort[k] = round(_crossing(GRID, curves[k], lo_target), 1)
        passing[k] = round(_crossing(GRID, curves[k], hi_target), 1)
    return MapRead({k: tuple(v) for k, v in curves.items()}, comfort, passing, _features(profile, mods),
                   round(profile.stars, 2), round(profile.bpm, 1), round(profile.drain_seconds))


def _features(profile: MapProfile, mods: str) -> dict:
    objs = [o for o in profile.objects if o.kind != "spinner"]
    n = max(1, len(objs))
    jumps = [o for o in objs if o.velocity > 0.6 and not o.stream_bpm]
    streams = [o for o in objs if o.stream_bpm]
    return {
        "jump_share": len(jumps) / n,
        "wide_share": sum(1 for o in jumps if o.velocity > 1.8) / n,
        "stream_share": len(streams) / n,
        "longest_stream": profile.longest_stream,
        "stream_bpm": round(profile.fastest_stream_bpm),
        "angle_share": sum(1 for o in objs if o.sharp_angle) / n,
        "rhythm_share": sum(1 for o in objs if o.complex_rhythm) / n,
        "sv": profile.sv_variability,
        "ar": round(profile.ar, 1), "od": round(profile.od, 1), "cs": round(profile.cs, 1), "hp": round(profile.hp, 1),
        "bpm": round(profile.bpm), "drain": round(profile.drain_seconds), "hidden": "HD" in mods,
        "hr": "HR" in mods, "dt": "DT" in mods or "NC" in mods,
    }


# --- the reader ------------------------------------------------------------------------------


def experience(db: Session, player: Player) -> float:
    """0 (never read a map seriously) .. 1 (a veteran who reads maps at a glance). One definition for the game."""
    values = simulation.effective_values(player)
    comps = A.composites(values)
    entries = list(db.scalars(select(TournamentEntry.id).join(Tournament, Tournament.id == TournamentEntry.tournament_id)
                              .where(Tournament.player_id == player.id, TournamentEntry.includes_user.is_(True))))
    matches = db.scalar(select(func.count()).select_from(Match).where(
        Match.played_on.is_not(None), (Match.entry_a.in_(entries)) | (Match.entry_b.in_(entries)))) if entries else 0
    duels = db.scalar(select(func.count()).select_from(Duel).where(Duel.player_id == player.id, Duel.status == "played")) or 0
    plays = min(1.0, math.log10(1 + player.play_count) / 3)
    competitive = min(1.0, ((matches or 0) + duels) / 30)
    skill = min(1.0, A.overall(values) / 85)
    insight = min(1.0, (comps["reading"] + comps["mentality"]) / 2 / 85)
    return round(0.35 * plays + 0.25 * competitive + 0.25 * skill + 0.15 * insight, 3)


def precision(exp: float) -> str:
    return "rough" if exp < 0.35 else "decent" if exp < 0.65 else "sharp"


def _round_to(x: float, step: int) -> int:
    return int(step * round(x / step))


def _main_skills(read: MapRead, prec: str, lang: str) -> list[dict]:
    f, T = read.features, TEXT[lang]
    exact = prec == "sharp"
    bpm = f["bpm"] if exact else _round_to(f["bpm"], 10)
    sbpm = f["stream_bpm"] if exact else _round_to(f["stream_bpm"], 10)
    items: list[tuple[float, dict]] = []
    if f["jump_share"] > 0.15:
        detail = T["jumps_v"] if prec == "rough" else T["jumps_d"].format(bpm=bpm)
        if f["wide_share"] > 0.12 and prec != "rough":
            detail += f" · {T['wide']}"
        items.append((read.passing["aim"] + 20 * f["jump_share"], {"key": "aim", "label": T["jumps"], "detail": detail}))
    if f["longest_stream"] >= 5:
        long_ = f["longest_stream"] > 12
        label = T["streams"] if long_ else T["burst"]
        if prec == "rough":
            detail = T["streams_v"] if long_ else T["burst"]
        elif long_:
            detail = T["streams_d"].format(n=f["longest_stream"], bpm=sbpm)
        else:
            detail = T["burst_d"].format(n=f["longest_stream"], bpm=sbpm)
        items.append((read.passing["tapping"] + 20 * f["stream_share"], {"key": "tapping", "label": label, "detail": detail}))
    if f["ar"] >= 9.6 or f["ar"] <= 8.0 or f["hidden"]:
        if f["hidden"]:
            label = detail = T["hidden"]
        elif f["ar"] >= 9.6:
            label, detail = T["high_ar"], (T["high_ar"] if prec == "rough" else T["high_ar_d"].format(ar=f["ar"] if exact else round(f["ar"])))
        else:
            label, detail = T["low_ar"], (T["low_ar"] if prec == "rough" else T["low_ar_d"].format(ar=f["ar"] if exact else round(f["ar"])))
        items.append((read.passing["reading"] + 5, {"key": "reading", "label": label, "detail": detail}))
    if f["sv"] > 0.3:
        items.append((40 + 40 * f["sv"], {"key": "technical", "label": T["sv"], "detail": T["sv"]}))
    if f["angle_share"] > 0.12 and prec != "rough":
        items.append((35 + 60 * f["angle_share"], {"key": "technical", "label": T["angles"], "detail": T["angles"]}))
    if f["rhythm_share"] > 0.1 and prec != "rough":
        items.append((35 + 60 * f["rhythm_share"], {"key": "reading", "label": T["rhythm"], "detail": T["rhythm"]}))
    if f["od"] >= 9 or f["hr"]:
        items.append((45, {"key": "technical", "label": T["strict"],
                           "detail": T["strict"] if prec == "rough" else T["strict_d"].format(od=f["od"] if exact else round(f["od"]))}))
    if f["cs"] >= 5:
        items.append((40, {"key": "aim", "label": T["small"], "detail": T["small"] if prec == "rough" else T["small_d"].format(cs=f["cs"])}))
    if f["drain"] >= 240:
        items.append((read.passing["stamina"] + 10, {"key": "stamina", "label": T["long"],
                                                     "detail": T["long"] if prec == "rough" else T["long_d"].format(m=f["drain"] // 60, s=f["drain"] % 60)}))
    items.sort(key=lambda x: -x[0])
    if not items:  # nothing stands out: name the dimension that asks the most
        k = max(("aim", "tapping", "reading"), key=lambda d: read.passing[d])
        items.append((0, {"key": k, "label": T[k], "detail": T[k]}))
    return [d for _, d in items[:3]]


def _notes(read: MapRead, prec: str, lang: str, fam: float) -> list[str]:
    f, T = read.features, TEXT[lang]
    if prec == "rough":
        return [T["n_rough"]]
    notes = []
    if f["hr"] and f["ar"] >= 9.5:
        notes.append(T["n_hr_ar"].format(ar=f["ar"]))
    if f["dt"]:
        notes.append(T["n_dt"].format(bpm=f["bpm"]))
    if prec == "sharp":
        if f["drain"] >= 300:
            notes.append(T["n_long"])
        if f["hp"] >= 7:
            notes.append(T["n_hp"])
        if fam >= 0.3:
            notes.append(T["n_fam"])
    return notes


_PERSONAL: "OrderedDict[tuple, dict]" = OrderedDict()
_PERSONAL_MAX = 512


def hint(db: Session, player: Player, beatmap_id: int, mods: str, lang: str = "en") -> dict:
    lang = "ru" if lang == "ru" else "en"
    key = (player.id, player.in_game_date, player.play_count, beatmap_id, mods, lang)
    cached = _PERSONAL.get(key)
    if cached is not None:
        _PERSONAL.move_to_end(key)
        return cached

    read = analyse(beatmap_id, mods)
    profile = sessions.map_profile(beatmap_id, mods)
    fam = familiarity.level(db, player, beatmap_id)
    master = familiarity.mastery(db, player, beatmap_id)
    mine = play.simulate(profile, condition.play_skills(db, player), mods + "NF",
                         play.DayModifiers(form=0.0, fatigue=0.0, motivation=80.0, familiarity=fam, mastery=master),
                         random.Random("hint"))
    exp = experience(db, player)
    prec = precision(exp)
    rng = random.Random(f"{player.seed}:hint:{beatmap_id}:{mods}")
    half = 3 + 22 * (1 - exp)  # how wide the ranges you can see are
    T = TEXT[lang]
    dims = []
    for k in DIMS:
        yours = round(min(_placement(GRID, list(read.curves[k]), mine.peak_ratios[k]), 120.0), 1)
        bias = rng.gauss(0, 9 * (1 - exp))  # an inexperienced reader can be a bit off, the same way every time
        need_c = read.comfort[k] + bias
        need_p = min(need_c, read.passing[k] + bias)
        comfort_rng = [max(1, round(need_c - half / 2)), round(need_c + half / 2)]
        pass_rng = [max(1, round(need_p - half / 2)), round(need_p + half / 2)]
        if read.comfort[k] <= GRID[1]:  # nothing to speak of in this dimension
            comfort_rng, pass_rng, verdict = [1, GRID[2]], [1, GRID[2]], "comfortable"
        else:
            verdict = "comfortable" if yours >= need_c else "passable" if yours >= need_p else "over"
        dims.append({"key": k, "label": T[k], "need_comfort": comfort_rng, "need_pass": pass_rng,
                     "yours": round(yours), "verdict": verdict, "verdict_label": T[verdict]})
    out = {
        "beatmap_id": beatmap_id, "mods": mods or "NM", "stars": read.stars, "bpm": read.bpm, "length": read.length,
        "main_skills": _main_skills(read, prec, lang), "dims": dims, "notes": _notes(read, prec, lang, fam),
        "precision": prec, "precision_label": T[prec], "experience": exp,
    }
    _PERSONAL[key] = out
    if len(_PERSONAL) > _PERSONAL_MAX:
        _PERSONAL.popitem(last=False)
    return out
