"""Historical ranking systems and pp reworks.

rosu-pp calculates today's formula. Each era below says how its pp differed from today's:
component multipliers (aim / speed / accuracy), whether the classic ppv2 combo scaling
applied (min((combo / max_combo)^0.8, 1), removed in October 2024), and whether pp decayed
with age (ppv1). Dates and descriptions follow the official osu! wiki and news posts; the
multipliers are approximations of each change's direction, not reimplementations of old code.

Sources:
- https://osu.ppy.sh/wiki/en/History_of_osu!/Online_rankings/osu!  (ranked score -> ppv1 -> ppv2 dates)
- https://osu.ppy.sh/wiki/en/Performance_points/ppv1                (ppv1 biases and decay)
- https://osu.ppy.sh/home/news/2021-01-14-performance-points-updates
- https://osu.ppy.sh/home/news/2021-11-09-performance-points-star-rating-updates
- https://osu.ppy.sh/community/forums/topics/2146340              (October 2024 rework megathread)
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PpEra:
    start: date
    key: str
    name: str
    summary: str
    aim: float = 1.0
    speed: float = 1.0
    acc: float = 1.0
    combo_scaling: bool = False
    decay: bool = False
    ranking: str = "pp"  # pp | ranked_score


ERAS: tuple[PpEra, ...] = (
    PpEra(date(2007, 10, 6), "ranked_score", "Ranked score",
          "Players are ranked by total ranked score; pp doesn't exist yet (shown here retroactively).",
          ranking="ranked_score", combo_scaling=True),
    PpEra(date(2012, 7, 24), "ppv1", "ppv1",
          "Opaque algorithm that favours Hard difficulties with mods and undervalues Insanes; "
          "pp decays over time, so inactive players can lose up to half within a year.",
          aim=0.85, speed=0.85, acc=1.1, combo_scaling=True, decay=True),
    PpEra(date(2014, 1, 27), "ppv2", "ppv2 (Tom94)",
          "Complete redesign based on osu!tp: separate aim, speed and accuracy values. "
          "Sliders don't count for aim yet and speed is capped at 300 BPM.",
          aim=0.92, speed=0.97, combo_scaling=True),
    PpEra(date(2021, 1, 16), "ppv2_2021_01", "ppv2, January 2021 update",
          "AR11 bonus scales with length, new miss penalty curve, speed now factors in OD and accuracy.",
          aim=0.94, speed=0.98, combo_scaling=True),
    PpEra(date(2021, 11, 9), "ppv2_2021_11", "ppv2, November 2021 rework",
          "New aim algorithm (angle changes, sliders, velocity changes buffed), 300 BPM speed cap removed, "
          "quick doubles and lenient streams nerfed.",
          speed=1.03, combo_scaling=True),
    PpEra(date(2024, 10, 28), "ppv2_2024_10", "ppv2, October 2024 rework",
          "Combo scaling removed (a miss mid-map costs the same as one at the end), small speed nerf "
          "mostly hitting flow aim.",
          combo_scaling=False),
)


def era_for(on: date) -> PpEra:
    current = ERAS[0]
    for era in ERAS:
        if on >= era.start:
            current = era
    return current


def adjust(
    pp_modern: float,
    aim: float,
    speed: float,
    acc: float,
    combo: int,
    map_max_combo: int,
    era: PpEra,
    age_days: int = 0,
) -> float:
    """A score's pp under an era's rules, from today's components."""
    parts = [aim, speed, acc]
    weights = [era.aim, era.speed, era.acc]
    if sum(parts) > 0:
        # Total pp is ~ a power mean of components; scale it by how much the components moved.
        before = sum(p**1.1 for p in parts)
        after = sum((p * w) ** 1.1 for p, w in zip(parts, weights))
        factor = (after / before) ** (1 / 1.1)
    else:
        factor = (era.aim + era.speed + era.acc) / 3
    if era.combo_scaling and map_max_combo > 0:
        factor *= min((combo / map_max_combo) ** 0.8, 1.0)
    if era.decay:
        factor *= max(0.5, 1 - age_days / 730)
    return pp_modern * factor


def style_multiplier(era: PpEra, aim_share: float) -> float:
    """For NPCs, who have no individual scores: how an era treats an aim-heavy vs speed-heavy player.

    Normalised to the era's average, because the rank curve is already calibrated to each era's
    real pp level; only the relative shift between playstyles is applied.
    """
    return (aim_share * era.aim + (1 - aim_share) * era.speed) / ((era.aim + era.speed) / 2)
