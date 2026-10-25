"""Mind: confidence per kind of map and fear of particular opponents.

State lives in Player.story_state["mind"]. Confidence (-1..1) grows with passes on a map family and drops with
fails and chokes; fear (0..1) grows after losing to an opponent and fades once beaten or with time. Both decay
towards neutral. Effects are small by design (play skills at most +-4%, a bump to choke pressure).
"""

import math
from datetime import date

FAMILIES = ("jumps", "streams", "tech", "reading", "hd", "dt", "hr")
CONF_HALF_LIFE_DAYS = 21.0
FEAR_HALF_LIFE_DAYS = 30.0
MAX_SKILL_EFFECT = 0.04
FEAR_PRESSURE = 0.15
BIG_STAGE_MIN_MAPS = 6


def family(prof, mods: str) -> str:
    if "DT" in mods:
        return "dt"
    if "HR" in mods:
        return "hr"
    if "HD" in mods:
        return "hd"
    if prof.ar <= 8.5:
        return "reading"
    if prof.longest_stream >= 12 or (prof.fastest_stream_bpm >= 170 and prof.longest_stream >= 8):
        return "streams"
    if prof.sv_variability >= 0.35:
        return "tech"
    return "jumps"


def _mind(player) -> dict:
    return (player.story_state or {}).get("mind") or {}


def _save(player, mind: dict) -> None:
    player.story_state = {**(player.story_state or {}), "mind": mind}


def _decay(value: float, since: str, on: date, half_life: float) -> float:
    days = max(0, (on - date.fromisoformat(since)).days)
    return value * 0.5 ** (days / half_life)


def confidence(player, fam: str, on: date) -> float:
    entry = _mind(player).get("conf", {}).get(fam)
    return _decay(entry[0], entry[1], on, CONF_HALF_LIFE_DAYS) if entry else 0.0


def fear(player, npc_id: int | None, on: date) -> float:
    if npc_id is None:
        return 0.0
    entry = _mind(player).get("fear", {}).get(str(npc_id))
    return _decay(entry[0], entry[1], on, FEAR_HALF_LIFE_DAYS) if entry else 0.0


def skill_multiplier(conf: float) -> float:
    return 1.0 + MAX_SKILL_EFFECT * max(-1.0, min(1.0, conf))


def scale_skills(skills: dict[str, float], conf: float) -> dict[str, float]:
    factor = skill_multiplier(conf)
    if abs(factor - 1.0) < 1e-9:
        return skills
    return {k: v * factor for k, v in skills.items()}


def pressure_multiplier(fear_level: float) -> float:
    return 1.0 + FEAR_PRESSURE * max(0.0, min(1.0, fear_level))


def record_attempt(player, fam: str, passed: bool, choked: bool, misses: int, on: date) -> None:
    mind = {**_mind(player)}
    conf = {**mind.get("conf", {})}
    now = confidence(player, fam, on)
    if not passed:
        delta = -0.15
    elif choked:
        delta = -0.05
    elif misses == 0:
        delta = 0.18
    else:
        delta = 0.1 if misses <= 5 else 0.04
    conf[fam] = [round(max(-1.0, min(1.0, now + delta)), 3), on.isoformat()]
    mind["conf"] = conf
    _save(player, mind)


def record_match(player, npc_ids: list[int], won: bool, on: date) -> None:
    mind = {**_mind(player)}
    fears = {**mind.get("fear", {})}
    for npc_id in npc_ids:
        now = fear(player, npc_id, on)
        new = max(0.0, now - 0.35) if won else min(1.0, now + 0.4)
        if new < 0.02:
            fears.pop(str(npc_id), None)
        else:
            fears[str(npc_id)] = [round(new, 3), on.isoformat()]
    mind["fear"] = fears
    _save(player, mind)


def record_decisive(player, won_map: bool) -> None:
    mind = {**_mind(player)}
    w, l = mind.get("big", [0, 0])
    mind["big"] = [w + int(won_map), l + int(not won_map)]
    _save(player, mind)


def big_stage_rating(player) -> float | None:
    """Share of decisive maps won, or None until there is enough history."""
    w, l = _mind(player).get("big", [0, 0])
    return w / (w + l) if w + l >= BIG_STAGE_MIN_MAPS else None


def clutch_factor(player) -> float:
    rating = big_stage_rating(player)
    return 1.0 if rating is None else 1.0 + 0.03 * (2 * rating - 1)


def summary(player, on: date) -> dict:
    mind = _mind(player)
    return {
        "confidence": {f: round(confidence(player, f, on), 2) for f in FAMILIES},
        "fear": sorted(({"npc_id": int(k), "value": round(fear(player, int(k), on), 2)} for k in mind.get("fear", {})),
                       key=lambda e: -e["value"]),
        "big_stage": None if big_stage_rating(player) is None else round(big_stage_rating(player), 2),
        "big_stage_maps": sum(mind.get("big", [0, 0])),
    }


assert math.isclose(skill_multiplier(1.0), 1.04)
