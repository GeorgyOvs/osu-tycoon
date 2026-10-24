"""Eras and the training drills each era makes available."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Era(str, Enum):
    OLD_SCHOOL = "old_school"  # 2007-2011: ranked packs only, no practice tools
    COMPETITIVE = "competitive"  # 2012-2015: stream practice maps, tech maps, AR edits
    FARM = "farm"  # 2016-2020: osu!trainer, BPM/AR changers, 1-minute jump maps
    MODERN = "modern"  # 2021+: finger control maps, rapid trigger, health routines


ERA_ORDER = [Era.OLD_SCHOOL, Era.COMPETITIVE, Era.FARM, Era.MODERN]
ERA_LABELS = {
    Era.OLD_SCHOOL: "Old-School Era",
    Era.COMPETITIVE: "Competitive Revolution",
    Era.FARM: "Farm & Toolset Era",
    Era.MODERN: "Modern Science",
}


def era_for(d: date) -> Era:
    if d.year <= 2011:
        return Era.OLD_SCHOOL
    if d.year <= 2015:
        return Era.COMPETITIVE
    if d.year <= 2020:
        return Era.FARM
    return Era.MODERN


@dataclass(frozen=True)
class Drill:
    key: str
    label: str
    description: str
    targets: dict[str, float]  # sub-stat -> share of the training gain
    available_from: Era = Era.OLD_SCHOOL
    strain: float = 1.0  # fatigue / RSI load multiplier
    era_efficiency: dict[Era, float] = field(default_factory=dict)
    # Drills that are really just playing ranked maps also produce real scores (an autoplay preset).
    ranked_preset: str | None = None
    hands_on: bool = True  # False: no physical conditioning from it (e.g. watching replays)
    motivation_per_hour: float = -0.1

    def available(self, d: date) -> bool:
        return ERA_ORDER.index(era_for(d)) >= ERA_ORDER.index(self.available_from)

    def efficiency(self, d: date) -> float:
        return self.era_efficiency.get(era_for(d), 1.0)


DRILLS: dict[str, Drill] = {
    d.key: d
    for d in [
        Drill(
            "ranked_pack_grind",
            "Ranked Pack Grind",
            "Play through full beatmap packs (DJ POP, SiFa, James). The only practice there is in the early days.",
            {"low_ar_reading": 1.0, "rhythm_reading": 0.8, "awkward_angles": 0.7,
             "snap_aim": 0.5, "flow_aim": 0.5, "low_mid_bpm": 0.5},
            era_efficiency={Era.OLD_SCHOOL: 1.2, Era.FARM: 0.8, Era.MODERN: 0.7},
            ranked_preset="farm",
        ),
        Drill(
            "hidden_grind",
            "Hidden Grind",
            "Replay favourite maps with HD until fading circles feel natural.",
            {"hidden": 1.0, "precision": 0.5, "low_ar_reading": 0.4},
            ranked_preset="hidden",
        ),
        Drill(
            "hardrock_practice",
            "HardRock Practice",
            "Small circles and strict OD. Punishing, but it sharpens timing.",
            {"strict_od": 1.0, "precision": 0.8, "high_ar_reaction": 0.3},
            strain=1.1,
            ranked_preset="hardrock",
        ),
        Drill(
            "multiplayer_lobbies",
            "Multiplayer Lobbies",
            "Head-to-head lobbies and community matches: practising under pressure.",
            {"nerve_resistance": 1.0, "clutch": 0.8, "tilt_resilience": 0.8},
            strain=0.8,
            ranked_preset="farm",
        ),
        Drill(
            "watch_replays",
            "Watch Top Players' Replays",
            "Study how the best players of the day read, move and stay calm. Easy on the hands, "
            "and worth more the further you are from the top.",
            {"rhythm_reading": 0.6, "hidden": 0.4, "awkward_angles": 0.4, "high_ar_reaction": 0.3,
             "nerve_resistance": 0.5, "clutch": 0.3},
            strain=0.1,
            hands_on=False,
            motivation_per_hour=0.15,
        ),
        Drill(
            "stream_practice",
            "Stream Practice Maps",
            "Long Stream Practice Maps, drilling BPM thresholds 180 -> 200 -> 220.",
            {"deathstream": 1.0, "low_mid_bpm": 0.8, "burst": 0.4},
            available_from=Era.COMPETITIVE,
            strain=1.3,
        ),
        Drill(
            "deathstream_240",
            "240+ BPM Deathstreams",
            "Fast continuous streams. Big stamina gains and the highest RSI risk.",
            {"deathstream": 1.2, "burst": 0.8, "finger_independence": 0.3},
            available_from=Era.COMPETITIVE,
            strain=1.8,
        ),
        Drill(
            "tech_maps",
            "Unranked Tech Maps",
            "SV changes, buzz sliders and awkward geometry.",
            {"slider_velocity": 1.0, "awkward_angles": 0.8, "finger_independence": 0.5, "rhythm_reading": 0.4},
            available_from=Era.COMPETITIVE,
        ),
        Drill(
            "high_ar_edits",
            "High AR Edits",
            "AR10+ edits of familiar maps to train reaction speed.",
            {"high_ar_reaction": 1.0, "snap_aim": 0.4, "distance": 0.3},
            available_from=Era.COMPETITIVE,
        ),
        Drill(
            "jump_farm",
            "1-Minute Jump Farm Maps",
            "Spam short Sotarks/Monstrata jump maps. Hyper-efficient raw aim and reaction.",
            {"snap_aim": 1.0, "distance": 0.9, "high_ar_reaction": 0.6, "flow_aim": 0.3},
            available_from=Era.FARM,
            era_efficiency={Era.FARM: 1.3},
            ranked_preset="jumps",
        ),
        Drill(
            "osutrainer",
            "osu!trainer Drills",
            "Rate-changed and AR-modified maps that isolate exactly one weakness.",
            {"burst": 0.8, "high_ar_reaction": 0.8, "precision": 0.6, "low_mid_bpm": 0.4},
            available_from=Era.FARM,
            strain=1.2,
        ),
        Drill(
            "finger_control_maps",
            "Finger Control Maps",
            "Low-BPM polyrhythms, triples and quintuples.",
            {"finger_independence": 1.0, "rhythm_reading": 0.8, "slider_velocity": 0.4},
            available_from=Era.MODERN,
        ),
        Drill(
            "rapid_trigger_drills",
            "Rapid Trigger Drills",
            "Optimise actuation and tapping on Hall Effect keyboards.",
            {"burst": 1.0, "low_mid_bpm": 0.6, "deathstream": 0.3},
            available_from=Era.MODERN,
            strain=1.2,
        ),
        Drill(
            "health_warmup",
            "Health & Warmup Routine",
            "Stretching, warmups and short sessions. Builds resilience, low strain.",
            {"rsi_resistance": 1.0, "hand_stamina": 0.6, "visual_endurance": 0.5},
            available_from=Era.MODERN,
            strain=0.4,
        ),
    ]
}


def available_drills(d: date) -> list[Drill]:
    return [drill for drill in DRILLS.values() if drill.available(d)]
