"""FIFA-style attribute hierarchy: 21 granular sub-stats rolled up into 6 composites."""

from collections.abc import Mapping
from dataclasses import dataclass

ATTR_MIN = 1.0
ATTR_SOFT_MAX = 99.0
ATTR_ABSOLUTE_MAX = 115.0  # transcendent historical peaks only


@dataclass(frozen=True)
class SubStat:
    key: str
    label: str
    weight: float = 1.0


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    overall_weight: float
    subs: tuple[SubStat, ...]


GROUPS: tuple[Group, ...] = (
    Group("aim", "Aim", 0.24, (
        SubStat("snap_aim", "Snap Aim", 1.2),
        SubStat("flow_aim", "Flow Aim", 1.0),
        SubStat("precision", "Precision & Small CS", 0.9),
        SubStat("distance", "High-Velocity Distance", 0.9),
    )),
    Group("tapping", "Tapping", 0.22, (
        SubStat("low_mid_bpm", "Low/Mid BPM Control", 1.0),
        SubStat("burst", "High BPM Burst", 1.0),
        SubStat("deathstream", "Deathstream Stamina", 1.0),
        SubStat("finger_independence", "Finger Independence", 0.8),
    )),
    Group("reading", "Reading", 0.20, (
        SubStat("low_ar_reading", "Low AR / Density Reading", 0.9),
        SubStat("high_ar_reaction", "High AR Reaction", 1.1),
        SubStat("rhythm_reading", "Complex Rhythm Reading", 0.9),
        SubStat("hidden", "Hidden Mod Competence", 1.0),
    )),
    Group("technical", "Technical", 0.12, (
        SubStat("slider_velocity", "Complex Slider Velocity", 1.0),
        SubStat("awkward_angles", "Awkward Angle Correction", 1.0),
        SubStat("strict_od", "HardRock / Strict OD", 1.0),
    )),
    Group("mentality", "Mentality", 0.14, (
        SubStat("nerve_resistance", "Nerve Resistance", 1.2),
        SubStat("clutch", "Match Clutchness", 1.0),
        SubStat("tilt_resilience", "Tilt & Reset Resilience", 0.8),
    )),
    Group("physical", "Physical", 0.08, (
        SubStat("hand_stamina", "Hand Stamina & Energy", 1.2),
        SubStat("rsi_resistance", "RSI Resistance", 1.0),
        SubStat("visual_endurance", "Visual Endurance", 0.8),
    )),
)

GROUPS_BY_KEY: dict[str, Group] = {g.key: g for g in GROUPS}
SUBSTATS: dict[str, SubStat] = {s.key: s for g in GROUPS for s in g.subs}
GROUP_OF: dict[str, str] = {s.key: g.key for g in GROUPS for s in g.subs}


def composite(values: Mapping[str, float], group: Group) -> float:
    total_weight = sum(s.weight for s in group.subs)
    return sum(values[s.key] * s.weight for s in group.subs) / total_weight


def composites(values: Mapping[str, float]) -> dict[str, float]:
    return {g.key: composite(values, g) for g in GROUPS}


def overall(values: Mapping[str, float]) -> float:
    comps = composites(values)
    return sum(comps[g.key] * g.overall_weight for g in GROUPS) / sum(g.overall_weight for g in GROUPS)


def clamp(value: float, low: float = ATTR_MIN, high: float = ATTR_ABSOLUTE_MAX) -> float:
    return max(low, min(high, value))
