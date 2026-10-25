"""Starting levels: who you already are on day one, independent of the talent/weakness build.

The default newcomer begins near the bottom of the ladder. The other backgrounds put a floor under
each skill group (so careers can start as a veteran or a prodigy), raise the ceiling a little and
add the money/followers that such a past would have earned. Floors are calibrated against the world's
overall -> pp -> rank curve: rhythm_gamer ~ overall 30, veteran ~ 46, ex_pro ~ 62, phenom ~ 76.
"""

import random
from dataclasses import dataclass, field

from app.engine import attributes as A


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    description: str
    min_age: float = 7
    floors: dict[str, float] = field(default_factory=dict)  # group -> minimum starting sub-stat value
    spread: float = 4.0  # +/- random spread around the floor per sub-stat
    cap_bonus: float = 0.0
    money: float = 0.0
    followers: int = 0
    motivation: float | None = None
    rust: float = 0.0


SCENARIOS: dict[str, Scenario] = {s.key: s for s in [
    Scenario("newcomer", "Новичок", "Первая игра в osu!. Классический старт с нуля."),
    Scenario(
        "rhythm_gamer", "Ветеран ритм-игр",
        "Годы в DJMAX, o2jam и StepMania: пальцы и чтение ритма уже на уровне, но аим пока сырой.",
        min_age=12, floors={"tapping": 40, "reading": 36, "aim": 22, "technical": 20, "mentality": 44, "physical": 48},
        cap_bonus=1, money=60,
    ),
    Scenario(
        "returning_veteran", "Вернувшийся ветеран",
        "Играл в osu! несколько лет назад и вернулся. Все навыки на уровне крепкого середняка.",
        min_age=17, floors={"aim": 48, "tapping": 48, "reading": 46, "technical": 40, "mentality": 50, "physical": 50},
        cap_bonus=2, money=400, followers=40,
    ),
    Scenario(
        "ex_pro", "Бывший топ-игрок",
        "Когда-то играл на высоком уровне и вернулся после перерыва. Старт в районе первых тысяч рейтинга.",
        min_age=16, floors={"aim": 66, "tapping": 64, "reading": 62, "technical": 56, "mentality": 62, "physical": 58},
        cap_bonus=4, money=1200, followers=800, rust=2.0,
    ),
    Scenario(
        "phenom", "Вундеркинд",
        "Редкий талант: уже на старте играет как игрок из мирового топ-100, с огромным потолком и большим вниманием "
        "сообщества. Ожидания очень высоки.",
        min_age=14, floors={"aim": 80, "tapping": 78, "reading": 76, "technical": 68, "mentality": 70, "physical": 64},
        spread=3.0, cap_bonus=8, money=800, followers=5000, motivation=95,
    ),
]}


def options() -> dict[str, dict]:
    return {s.key: {"label": s.label, "description": s.description, "min_age": s.min_age} for s in SCENARIOS.values()}


def validate(key: str, age: float) -> Scenario:
    scenario = SCENARIOS.get(key)
    if scenario is None:
        raise ValueError(f"Unknown starting level '{key}'")
    if age < scenario.min_age:
        raise ValueError(f"{scenario.label} requires age {scenario.min_age:g}+")
    return scenario


def apply(player, scenario: Scenario) -> None:
    if scenario.key == "newcomer":
        return
    rng = random.Random(f"{player.seed}:scenario:{scenario.key}")
    player.potential = A.clamp(player.potential + scenario.cap_bonus)
    for attr in player.attributes:
        attr.cap = A.clamp(attr.cap + scenario.cap_bonus)
        floor = scenario.floors.get(A.GROUP_OF[attr.key])
        if floor is None:
            continue
        target = floor + rng.uniform(-scenario.spread, scenario.spread)
        attr.base = round(A.clamp(max(attr.base, target), high=attr.cap - 1), 1)
        # A past at this level means the easy gains were made long ago.
        attr.plateau = round(max(0.0, (attr.base - 30) * 0.4), 1)
        if scenario.rust:
            attr.rust = round(min(scenario.rust, attr.base * 0.2), 1)
    player.money += scenario.money
    player.followers += scenario.followers
    if scenario.motivation is not None:
        player.motivation = scenario.motivation
