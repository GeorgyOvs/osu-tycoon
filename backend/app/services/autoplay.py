"""Automatic map selection: play sessions from presets instead of hand-picked difficulties.

Maps come from the local ranked index (only what exists on the in-game date), chosen around a
target difficulty relative to the player's current ability. Already-downloaded maps are
preferred, and a weekly rotation means a farmer keeps replaying the same handful of maps,
like real players do.
"""

import math
import random
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import OSU_CACHE_DIR
from app.engine import attributes as A
from app.engine import simulation
from app.engine.training import ERA_ORDER, Era, era_for
from app.models import Beatmap, BeatmapSet, Player
from app.services.sessions import ATTEMPT_OVERHEAD_S, PlayRequest

# Mirror star ratings use today's algorithm and run ~5% above stable's.
MIRROR_TO_STABLE = 0.95
MOD_STAR_MULT = {"": 1.0, "HD": 1.04, "HR": 1.08, "DT": 1.45, "HDHR": 1.12, "HDDT": 1.5, "HDHRDT": 1.63}
MAX_MAPS = 25


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    description: str
    target: float  # map stars / handled stars
    attempts: int
    mods: str = ""
    weights: dict[str, float] = field(default_factory=lambda: {"aim": 0.5, "tapping": 0.5})
    min_bpm: float | None = None
    max_bpm: float | None = None
    max_ar: float | None = None
    max_length: int = 330
    newest_days: int | None = None
    available_from: Era = Era.OLD_SCHOOL


PRESETS: dict[str, Preset] = {p.key: p for p in [
    Preset("warmup", "Warm-up", "Easy, comfortable maps to get the hands going.", 0.6, 1),
    Preset("farm", "Farm at your level", "Maps you can pass and might FC with a few tries.", 0.85, 3),
    Preset("push", "Push your limits", "Right at the edge of what you can do. Expect fails.", 1.0, 4),
    Preset("streams", "Stream maps", "Stamina and tapping: maps full of 1/4 streams.", 0.85, 3,
           weights={"tapping": 0.8, "physical": 0.2}, min_bpm=170),
    Preset("jumps", "Jump maps", "Aim-heavy maps; in the farm era, short jump farm maps.", 0.88, 3,
           weights={"aim": 0.8, "reading": 0.2}, max_bpm=210, max_length=240),
    Preset("lowar", "Low AR reading", "Old-school dense, low-AR maps.", 0.8, 2,
           weights={"reading": 0.6, "aim": 0.4}, max_ar=8.0),
    Preset("hidden", "Hidden session", "Your usual maps with HD.", 0.8, 3, mods="HD",
           weights={"reading": 0.5, "aim": 0.3, "tapping": 0.2}),
    Preset("hardrock", "HardRock session", "Small circles, strict timing.", 0.8, 3, mods="HR",
           weights={"aim": 0.5, "technical": 0.5}),
    Preset("doubletime", "DT session", "Speed it up: DT on maps you know.", 0.85, 3, mods="DT",
           weights={"tapping": 0.5, "aim": 0.4, "reading": 0.1}, available_from=Era.COMPETITIVE),
    Preset("hdhr", "HDHR session", "Hidden and HardRock together: tiny circles that vanish.", 0.75, 3, mods="HDHR",
           weights={"aim": 0.4, "technical": 0.3, "reading": 0.3}),
    Preset("hddt", "HDDT session", "Hidden and DT together: fast maps you must read on the fly.", 0.78, 3, mods="HDDT",
           weights={"tapping": 0.35, "aim": 0.3, "reading": 0.35}, available_from=Era.COMPETITIVE),
    Preset("hdhrdt", "HDHRDT session", "All three at once. Brutal, and the best practice for mod-heavy tournament slots.",
           0.7, 3, mods="HDHRDT", weights={"aim": 0.4, "tapping": 0.25, "reading": 0.25, "technical": 0.1},
           available_from=Era.COMPETITIVE),
    Preset("new_ranked", "Newly ranked", "Whatever got ranked in the last couple of months.", 0.85, 2,
           newest_days=60),
]}


def available(preset: Preset, player: Player) -> bool:
    return ERA_ORDER.index(era_for(player.in_game_date)) >= ERA_ORDER.index(preset.available_from)


def handled_stars(player: Player, preset: Preset) -> float:
    """Stars the player handles reliably, on the composites the preset leans on."""
    comps = A.composites(simulation.effective_values(player))
    total = sum(preset.weights.values())
    skill = sum(comps[g] * w for g, w in preset.weights.items()) / total
    return 2 * (0.6 + 0.04 * skill)


def _candidates(db: Session, player: Player, preset: Preset, target_nm: float, window: float):
    q = (select(Beatmap, BeatmapSet).join(BeatmapSet)
         .where(BeatmapSet.ranked_date <= player.in_game_date,
                Beatmap.stars.between(target_nm - window, target_nm + window),
                Beatmap.hit_length.between(45, preset.max_length)))
    if preset.min_bpm:
        q = q.where(Beatmap.bpm >= preset.min_bpm)
    if preset.max_bpm:
        q = q.where(Beatmap.bpm <= preset.max_bpm)
    if preset.max_ar:
        q = q.where(Beatmap.ar <= preset.max_ar)
    if preset.newest_days:
        q = q.where(BeatmapSet.ranked_date >= player.in_game_date - timedelta(days=preset.newest_days))
    return list(db.execute(q.order_by(BeatmapSet.play_count.desc()).limit(300)))


def select_maps(db: Session, player: Player, preset: Preset, n_maps: int, rng: random.Random) -> list[Beatmap]:
    target_nm = preset.target * handled_stars(player, preset) / MOD_STAR_MULT[preset.mods] / MIRROR_TO_STABLE
    rows = []
    for window in (0.25, 0.5, 1.0, 2.0):
        rows = _candidates(db, player, preset, target_nm, window)
        if len({s.id for _, s in rows}) >= n_maps:
            break
    if not rows:
        return []

    def weight(row) -> float:
        b, s = row
        closeness = math.exp(-(((b.stars - target_nm) / 0.4) ** 2))
        cached = 3.0 if (OSU_CACHE_DIR / f"{b.id}.osu").exists() else 1.0
        popular = 1 + math.log10(s.play_count + 10) / 4
        return closeness * cached * popular

    picked: list[Beatmap] = []
    used_sets: set[int] = set()
    pool = list(rows)
    while pool and len(picked) < n_maps:
        row = rng.choices(pool, weights=[weight(r) for r in pool])[0]
        pool.remove(row)
        if row[1].id in used_sets:
            continue
        used_sets.add(row[1].id)
        picked.append(row[0])
    return picked


def plan_session(db: Session, player: Player, preset: Preset, hours: float, tag: str = "auto") -> list[PlayRequest]:
    """Enough maps and retries to fill `hours`."""
    rng = random.Random(f"{player.seed}:{tag}:{preset.key}:{player.in_game_date.isoformat()}")
    budget = hours * 3600
    per_map = preset.attempts * (150 + ATTEMPT_OVERHEAD_S)  # first guess before we know lengths
    maps = select_maps(db, player, preset, max(1, min(MAX_MAPS, round(budget / per_map))), rng)
    requests, used = [], 0.0
    for b in maps:
        cost = b.hit_length / (1.5 if "DT" in preset.mods else 1.0) + ATTEMPT_OVERHEAD_S
        attempts = max(1, min(preset.attempts + rng.randint(-1, 2), round((budget - used) / cost)))
        if used + cost > budget and requests:
            break
        requests.append(PlayRequest(b.id, preset.mods, attempts))
        used += attempts * cost
    # Out of fresh maps before the hours are used up: keep grinding the same ones, like real players.
    costs = [r.attempts and (b.hit_length / (1.5 if "DT" in preset.mods else 1.0) + ATTEMPT_OVERHEAD_S)
             for r, b in zip(requests, maps)]
    i = 0
    while requests and used + costs[i % len(requests)] <= budget and i < 500:
        requests[i % len(requests)].attempts += 1
        used += costs[i % len(requests)]
        i += 1
    return requests


def training_plays(db: Session, player: Player, preset_key: str, count: int = 3) -> list[PlayRequest]:
    """A few maps from this week's rotation, played as part of a training day."""
    preset = PRESETS[preset_key]
    week = player.in_game_date.isocalendar()
    rotation = select_maps(db, player, preset, 6,
                           random.Random(f"{player.seed}:rotation:{preset_key}:{week.year}:{week.week}"))
    day_rng = random.Random(f"{player.seed}:training:{player.in_game_date.isoformat()}")
    chosen = day_rng.sample(rotation, k=min(count, len(rotation)))
    return [PlayRequest(b.id, preset.mods, preset.attempts) for b in chosen]
