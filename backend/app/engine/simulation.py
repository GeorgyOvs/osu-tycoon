"""Day-by-day career simulation: training gains, fatigue, rust and the injury state machine.

Every day draws its randomness from Random(f"{seed}:{date}"), so a career replays
identically no matter how actions are batched.
"""

import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.engine import attributes as A
from app.engine.training import Drill
from app.models import Player, PlayerAttribute

HEALTHY, MINOR_STRAIN, SEVERE_RSI = "healthy", "minor_strain", "severe_rsi"

# Effective-value multipliers while injured.
INJURY_MODIFIERS: dict[str, dict[str, float]] = {
    MINOR_STRAIN: {
        "deathstream": 0.85, "hand_stamina": 0.85,
        "low_mid_bpm": 0.90, "burst": 0.90, "finger_independence": 0.90,
    },
    SEVERE_RSI: {
        "deathstream": 0.60, "hand_stamina": 0.60,
        "low_mid_bpm": 0.70, "burst": 0.70, "finger_independence": 0.70,
        "snap_aim": 0.85, "flow_aim": 0.85, "distance": 0.85, "precision": 0.85,
    },
}

STARTING_RANGES = {
    "aim": (5, 15), "tapping": (5, 15), "reading": (5, 15), "technical": (4, 12),
    "mentality": (25, 45), "physical": (35, 55),
}
POTENTIAL_RANGE = (92.0, 108.0)

GAIN_PER_HOUR = 0.12
# Playing at all keeps the body conditioned, whatever the drill.
PASSIVE_TARGETS = {"hand_stamina": 0.15, "visual_endurance": 0.10}

RUST_GRACE_DAYS = 14
RUST_STEP_DAYS = 10
RUST_MAX = 5
RUST_MAX_SHARE = 0.2  # never more than 20% of the skill, so beginners aren't wiped out

FATIGUE_INJURY_THRESHOLD = 65.0
STRAIN_REST_DAYS_TO_HEAL = 5
SEVERE_HIATUS_DAYS = (30, 90)
PHYSIO_DAYS_TO_AVOID_DAMAGE = 14
PERMANENT_CAP_LOSS = (4.0, 8.0)
STAMINA_CEILING_KEYS = ("deathstream", "hand_stamina")

# Progression randomness. Talent and affinity are hidden and fixed per career; form
# drifts day to day; plateau builds with focused volume and resets on a breakthrough.
TALENT_SIGMA = 0.25
TALENT_RANGE = (0.6, 1.6)
GROUP_AFFINITY_SIGMA = 0.20
SUB_AFFINITY_SIGMA = 0.08
FORM_PERSISTENCE = 0.85
FORM_SHOCK_SIGMA = 0.30
FORM_GAIN_WEIGHT = 0.30
FORM_EVENT_THRESHOLD = 1.0
DAY_NOISE_SIGMA = 0.30
SKILL_NOISE_SIGMA = 0.12
PLATEAU_SCALE = 60.0  # plateau load at which gains are halved
PLATEAU_REST_DECAY = 0.9  # rest consolidates: each day off sheds 10% of the plateau
BREAKTHROUGH_BASE_P = 0.001
BREAKTHROUGH_P_PER_PLATEAU = 0.0003
BREAKTHROUGH_MAX_P = 0.03
BREAKTHROUGH_PLATEAU_KEEP = 0.3  # a breakthrough lowers the wall, it doesn't remove it
BREAKTHROUGH_JUMP = (1.0, 3.0)


class TrainingBlocked(Exception):
    pass


@dataclass
class Event:
    date: date
    type: str
    message: str
    data: dict = field(default_factory=dict)


@dataclass
class DayPlan:
    """A training day when `drill` is set, otherwise a rest day."""

    drill: Drill | None = None
    hours: float = 0.0
    physio: bool = False
    learning: float = 1.0  # age, playstyle adaptation...
    caps: dict[str, float] = field(default_factory=dict)  # trainable ceilings from gear (e.g. monitor -> AR)

    @property
    def is_training(self) -> bool:
        return self.drill is not None and self.hours > 0


@dataclass
class ActionResult:
    start_date: date
    end_date: date
    days: int
    events: list[Event]
    deltas: dict[str, float]  # effective value change per sub-stat


def new_career(name: str, country: str, start_date: date, seed: int, birth_date: date | None = None,
               occupation: str = "school", gender: str = "unspecified") -> Player:
    rng = random.Random(seed)
    potential = round(rng.uniform(*POTENTIAL_RANGE), 1)
    talent = round(A.clamp(math.exp(rng.gauss(0, TALENT_SIGMA)), *TALENT_RANGE), 3)
    player = Player(
        name=name,
        country=country,
        in_game_date=start_date,
        seed=seed,
        potential=potential,
        talent=talent,
        form=0.0,
        ergonomics=0.3,
        fatigue=0.0,
        motivation=80.0,
        morale=50.0,
        consecutive_training_days=0,
        injury=HEALTHY,
        injury_until=None,
        strain_recovery_days=0,
        physio_days=0,
        total_pp=0.0,
        accuracy=0.0,
        play_count=0,
        global_rank=None,
        previous_rank=None,
        birth_date=birth_date,
        occupation=occupation,
        gender=gender,
        money=100.0,
        input_device="mouse",
        tap_style="alternate",
        style_adaptation=1.0,
        followers=0,
        badges=[],
    )
    for group in A.GROUPS:
        low, high = STARTING_RANGES[group.key]
        group_affinity = math.exp(rng.gauss(0, GROUP_AFFINITY_SIGMA))
        for sub in group.subs:
            player.attributes.append(
                PlayerAttribute(
                    key=sub.key,
                    base=round(rng.uniform(low, high), 1),
                    cap=potential,
                    rust=0.0,
                    affinity=round(A.clamp(group_affinity * math.exp(rng.gauss(0, SUB_AFFINITY_SIGMA)), 0.5, 1.8), 3),
                    plateau=0.0,
                    last_trained_on=start_date,
                )
            )
    return player


def effective_value(attr: PlayerAttribute, injury: str) -> float:
    value = min(attr.base - attr.rust, attr.cap)
    value *= INJURY_MODIFIERS.get(injury, {}).get(attr.key, 1.0)
    return A.clamp(value)


def effective_values(player: Player) -> dict[str, float]:
    return {a.key: effective_value(a, player.injury) for a in player.attributes}


def run_days(player: Player, plan: DayPlan, days: int) -> ActionResult:
    """Simulate `days` consecutive days with the same plan."""
    if plan.is_training:
        assert plan.drill is not None
        if not plan.drill.available(player.in_game_date):
            raise TrainingBlocked(f"{plan.drill.label} doesn't exist yet in {player.in_game_date.year}")
        if player.injury == SEVERE_RSI:
            raise TrainingBlocked(f"recovering from severe RSI until {player.injury_until}")

    start = player.in_game_date
    before = effective_values(player)
    before_comps = A.composites(before)
    events: list[Event] = []

    simulated = 0
    for _ in range(days):
        if plan.is_training and player.injury == SEVERE_RSI:
            events.append(Event(player.in_game_date, "TRAINING_INTERRUPTED",
                                "Training stopped: forced hiatus.", {"days_lost": days - simulated}))
            break
        events.extend(simulate_day(player, plan))
        simulated += 1

    after = effective_values(player)
    for key, value in A.composites(after).items():
        old = before_comps[key]
        if int(value // 10) > int(old // 10):
            label = A.GROUPS_BY_KEY[key].label
            events.append(Event(player.in_game_date, "MILESTONE",
                                f"{label} reached {int(value // 10) * 10}.", {"group": key, "value": value}))

    return ActionResult(
        start_date=start,
        end_date=player.in_game_date,
        days=simulated,
        events=events,
        deltas={k: after[k] - before[k] for k in after if abs(after[k] - before[k]) >= 0.005},
    )


def simulate_day(player: Player, plan: DayPlan) -> list[Event]:
    today = player.in_game_date
    rng = random.Random(f"{player.seed}:{today.isoformat()}")
    attrs = {a.key: a for a in player.attributes}
    events: list[Event] = []

    _injury_expiry(player, attrs, today, rng, events)
    _update_form(player, rng, today, events)
    if plan.is_training:
        if player.injury == SEVERE_RSI:
            raise TrainingBlocked(f"recovering from severe RSI until {player.injury_until}")
        _train(player, attrs, plan, today, rng, events)
    else:
        _rest(player, attrs, plan)
    _injury_step(player, attrs, plan, today, rng, events)
    _rust_step(attrs, today, events)

    player.in_game_date = today + timedelta(days=1)
    return events


def _hours_effect(hours: float) -> float:
    """Diminishing returns: full value up to 3h, 70% up to 6h, 35% beyond."""
    return min(hours, 3) + 0.7 * max(0.0, min(hours, 6) - 3) + 0.35 * max(0.0, hours - 6)


def _gain(attr: PlayerAttribute, points: float, today: date, cap: float | None = None) -> None:
    """Apply training points. Rust clears twice as fast as raw skill builds."""
    ceiling = min(attr.cap, cap) if cap is not None else attr.cap
    room = max(0.0, (ceiling - attr.base) / attr.cap)
    points *= room**1.3
    if attr.rust > 0:
        cleared = min(attr.rust, 2 * points)
        attr.rust -= cleared
        points -= cleared / 2
    attr.base = A.clamp(attr.base + points)
    attr.last_trained_on = today


def _update_form(player: Player, rng: random.Random, today: date, events: list[Event]) -> None:
    """AR(1) process: form reverts to zero but good and bad streaks persist for days."""
    old = player.form
    bias = 0.01 * (player.motivation - 70) / 30 - (0.1 if player.fatigue > 70 else 0.0)
    player.form = max(-2.5, min(2.5, FORM_PERSISTENCE * old + rng.gauss(0, FORM_SHOCK_SIGMA) + bias))
    if old < FORM_EVENT_THRESHOLD <= player.form:
        events.append(Event(today, "FORM_PEAK", "In the zone: everything feels easy lately.",
                            {"form": player.form}))
    elif old > -FORM_EVENT_THRESHOLD >= player.form:
        events.append(Event(today, "FORM_SLUMP", "Slump: nothing is clicking these days.",
                            {"form": player.form}))


def _train(
    player: Player,
    attrs: dict[str, PlayerAttribute],
    plan: DayPlan,
    today: date,
    rng: random.Random,
    events: list[Event],
) -> None:
    assert plan.drill is not None
    drill = plan.drill
    hand = effective_value(attrs["hand_stamina"], player.injury)

    hours_effect = _hours_effect(plan.hours)
    pool = (
        GAIN_PER_HOUR
        * hours_effect
        * drill.efficiency(today)
        * (0.6 + 0.5 * player.motivation / 100)
        * (1 - player.fatigue / 200)
        * (0.7 if player.injury == MINOR_STRAIN else 1.0)
        * plan.learning
    )
    targets = dict(PASSIVE_TARGETS) if drill.hands_on else {}
    for key, share in drill.targets.items():
        targets[key] = targets.get(key, 0.0) + share
    # One roll for the whole session (good/bad day), a smaller one per skill.
    day_mult = player.talent * math.exp(FORM_GAIN_WEIGHT * player.form + rng.gauss(0, DAY_NOISE_SIGMA))
    for key, share in targets.items():
        a = attrs[key]
        mult = day_mult * a.affinity * math.exp(rng.gauss(0, SKILL_NOISE_SIGMA))
        _gain(a, pool * share * mult / (1 + a.plateau / PLATEAU_SCALE), today, plan.caps.get(key))
        a.plateau += share * hours_effect**0.6  # long days saturate, but not completely
        _maybe_breakthrough(player, a, share, rng, today, events)

    tolerance = 6 + hand / 25
    load = plan.hours * drill.strain * 2.5 + max(0.0, plan.hours - tolerance) * 6
    if player.consecutive_training_days >= 6 and plan.hours >= 6:
        load += 3  # long sessions with no rest days
    recovery = 14 * (0.5 + hand / 100)  # a night's sleep: 6h days with a weekly rest are sustainable
    player.fatigue = A.clamp(player.fatigue + load - recovery, 0, 100)
    player.consecutive_training_days += 1

    # A sane schedule is sustainable; long grinds and playing exhausted burn you out.
    player.motivation += drill.motivation_per_hour * plan.hours
    player.motivation -= 0.4 * max(0.0, plan.hours - 6) + (1.5 if player.fatigue > 70 else 0)
    player.motivation = A.clamp(player.motivation, 0, 100)


def _maybe_breakthrough(
    player: Player,
    attr: PlayerAttribute,
    share: float,
    rng: random.Random,
    today: date,
    events: list[Event],
) -> None:
    """The longer you grind against a wall, the likelier something suddenly clicks."""
    p = share * min(BREAKTHROUGH_MAX_P, BREAKTHROUGH_BASE_P + BREAKTHROUGH_P_PER_PLATEAU * attr.plateau)
    if rng.random() >= p or attr.base >= attr.cap:
        return
    room = (attr.cap - attr.base) / attr.cap
    jump = rng.uniform(*BREAKTHROUGH_JUMP) * math.sqrt(room) * math.sqrt(player.talent * attr.affinity)
    attr.base = min(attr.cap, attr.base + jump)
    attr.plateau *= BREAKTHROUGH_PLATEAU_KEEP
    label = A.SUBSTATS[attr.key].label
    events.append(Event(today, "BREAKTHROUGH", f"Something clicked: {label} +{jump:.1f}.",
                        {"skill": attr.key, "jump": jump}))


def _rest(player: Player, attrs: dict[str, PlayerAttribute], plan: DayPlan) -> None:
    hand = effective_value(attrs["hand_stamina"], player.injury)
    recovery = 25 * (0.5 + hand / 100) + (10 if plan.physio else 0)
    player.fatigue = A.clamp(player.fatigue - recovery, 0, 100)
    player.consecutive_training_days = 0
    player.motivation = A.clamp(player.motivation + 3, 0, 100)
    for a in attrs.values():
        a.plateau *= PLATEAU_REST_DECAY


def _risk_multiplier(player: Player, attrs: dict[str, PlayerAttribute], plan: DayPlan) -> float:
    resistance = effective_value(attrs["rsi_resistance"], player.injury)
    strain = plan.drill.strain if plan.drill else 1.0
    return (1.6 - resistance / 100) * (1.5 - player.ergonomics) * strain


def _injury_step(
    player: Player,
    attrs: dict[str, PlayerAttribute],
    plan: DayPlan,
    today: date,
    rng: random.Random,
    events: list[Event],
) -> None:
    if player.injury == HEALTHY:
        if plan.is_training and player.fatigue > FATIGUE_INJURY_THRESHOLD:
            excess = (player.fatigue - FATIGUE_INJURY_THRESHOLD) / (100 - FATIGUE_INJURY_THRESHOLD)
            if rng.random() < excess**2 * 0.25 * _risk_multiplier(player, attrs, plan):
                player.injury = MINOR_STRAIN
                player.strain_recovery_days = 0
                events.append(Event(today, "INJURY_MINOR_STRAIN",
                                    "Minor wrist strain: -15% stamina, -10% speed. Rest it off.",
                                    {"fatigue": player.fatigue}))

    elif player.injury == MINOR_STRAIN:
        if plan.is_training:
            p = (0.03 + 0.12 * player.fatigue / 100) * _risk_multiplier(player, attrs, plan)
            if rng.random() < p:
                hiatus = rng.randint(*SEVERE_HIATUS_DAYS)
                player.injury = SEVERE_RSI
                player.injury_until = today + timedelta(days=hiatus)
                player.physio_days = 0
                events.append(Event(today, "INJURY_SEVERE_RSI",
                                    f"Severe tendonitis: forced {hiatus}-day hiatus. "
                                    "Without physiotherapy the stamina ceiling drops for good.",
                                    {"hiatus_days": hiatus, "until": player.injury_until.isoformat()}))
        else:
            player.strain_recovery_days += 2 if plan.physio else 1
            if player.strain_recovery_days >= STRAIN_REST_DAYS_TO_HEAL and player.fatigue < 35:
                player.injury = HEALTHY
                player.strain_recovery_days = 0
                events.append(Event(today, "INJURY_RECOVERED", "Wrist strain has healed."))

    elif player.injury == SEVERE_RSI and plan.physio:
        assert player.injury_until is not None
        player.physio_days += 1
        if player.physio_days % 4 == 0:
            player.injury_until -= timedelta(days=1)


def _injury_expiry(
    player: Player,
    attrs: dict[str, PlayerAttribute],
    today: date,
    rng: random.Random,
    events: list[Event],
) -> None:
    if player.injury != SEVERE_RSI or player.injury_until is None or today < player.injury_until:
        return

    if player.physio_days >= PHYSIO_DAYS_TO_AVOID_DAMAGE:
        events.append(Event(today, "INJURY_RECOVERED", "Back from the hiatus: physiotherapy paid off."))
    else:
        losses = {}
        for key in STAMINA_CEILING_KEYS:
            loss = round(rng.uniform(*PERMANENT_CAP_LOSS), 1)
            attrs[key].cap = max(A.ATTR_MIN, attrs[key].cap - loss)
            losses[key] = loss
        events.append(Event(today, "PERMANENT_DAMAGE",
                            "Back from the hiatus, but untreated RSI permanently lowered the stamina ceiling.",
                            {"cap_loss": losses}))

    player.injury = HEALTHY
    player.injury_until = None
    player.physio_days = 0
    player.fatigue = min(player.fatigue, 20.0)


def _rust_step(attrs: dict[str, PlayerAttribute], today: date, events: list[Event]) -> None:
    for group in A.GROUPS:
        subs = [attrs[s.key] for s in group.subs]
        inactive = (today - max(a.last_trained_on for a in subs)).days
        if inactive <= RUST_GRACE_DAYS:
            continue
        target = min(RUST_MAX, 1 + (inactive - RUST_GRACE_DAYS - 1) // RUST_STEP_DAYS)
        increased = False
        for a in subs:
            allowed = round(min(target, a.base * RUST_MAX_SHARE), 1)
            if a.rust < allowed:
                a.rust = allowed
                increased = True
        if increased:
            worst = max(a.rust for a in subs)
            events.append(Event(today, "RUST", f"{group.label} is getting rusty (up to -{worst:g}).",
                                {"group": group.key, "rust": worst, "inactive_days": inactive}))


def traits(player: Player) -> list[str]:
    """Visible hints about the hidden talent profile."""
    from app.engine.character import PERKS
    build = player.character_build or {}
    out = [PERKS[p]["label"] for p in build.get("perks", []) if p in PERKS]
    if player.talent >= 1.25:
        out.append("Fast learner")
    elif player.talent <= 0.8:
        out.append("Slow learner")
    for group in A.GROUPS:
        subs = [a for a in player.attributes if A.GROUP_OF[a.key] == group.key]
        affinity = sum(a.affinity for a in subs) / len(subs)
        if affinity >= 1.2:
            out.append(f"Natural {group.label.lower()}")
        elif affinity <= 0.8:
            out.append(f"Struggles with {group.label.lower()}")
    return out
