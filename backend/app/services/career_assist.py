"""How the character's stats and condition bend real gameplay in the tycoon client.

The client applies these as a hidden mod: a strong, fresh character plays the map a little easier than it is,
a weak or exhausted one a little harder. NEUTRAL is the character level that plays the map exactly as written.
Per-career settings scale the whole effect and switch on the cursor magnet (strong aim only).
"""
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import simulation
from app.models import AssistSettings, Player
from app.services import sessions

NEUTRAL = 50.0
SPAN = 40.0  # stat points from neutral to full effect

TIMING = {"strict_od": 1.2, "low_mid_bpm": 1.0, "rhythm_reading": 0.8}
READING = {"high_ar_reaction": 1.1, "low_ar_reading": 0.9}
PHYSICAL = {"hand_stamina": 1.2, "visual_endurance": 0.8}

MAX_OD, MAX_CS, MAX_AR, MAX_HP = 4.0, 1.5, 1.5, 2.0
MAX_MAGNET = 0.6  # pull strength at full aim edge and scale 1 (the client accepts 0..1)
MIN_SCALE, MAX_SCALE = 0.0, 2.0


@dataclass(frozen=True)
class Assist:
    od_delta: float
    cs_delta: float
    ar_delta: float
    hp_delta: float
    magnet: float  # 0 = off
    scale: float
    condition: float  # form/fatigue/motivation/tilt multiplier applied to every stat
    timing: float  # effective stat values the deltas came from
    aim: float
    reading: float
    physical: float


def settings_for(db: Session, player: Player) -> AssistSettings:
    settings = db.get(AssistSettings, player.id)
    if settings is None:
        settings = AssistSettings(player_id=player.id, scale=1.0, magnet=False)
        db.add(settings)
        db.flush()
    return settings


def _weighted(values: dict[str, float], weights: dict[str, float]) -> float:
    return sum(values[k] * w for k, w in weights.items()) / sum(weights.values())


def _edge(value: float) -> float:
    return max(-1.0, min(1.0, (value - NEUTRAL) / SPAN))


def for_player(player: Player, scale: float = 1.0, magnet: bool = False, session_hours: float = 0.0) -> Assist:
    values = simulation.effective_values(player)
    day = sessions.day_modifiers(player)
    day.session_hours = session_hours
    condition = day.capability(values["tilt_resilience"])
    timing = _weighted(values, TIMING) * condition
    aim = A.composite(values, A.GROUPS_BY_KEY["aim"]) * condition
    reading = _weighted(values, READING) * condition
    physical = _weighted(values, PHYSICAL) * condition
    # Fatigue drains HP faster on top of weak stamina; it never makes the bar kinder.
    hp = -MAX_HP * _edge(physical) + 1.5 * player.fatigue / 100
    # The magnet is a reward for strong aim only; weak aim is already punished through CS.
    pull = min(1.0, max(0.0, _edge(aim)) * MAX_MAGNET * scale) if magnet else 0.0
    return Assist(
        od_delta=round(-MAX_OD * _edge(timing) * scale, 2),
        cs_delta=round(-MAX_CS * _edge(aim) * scale, 2),
        ar_delta=round(-MAX_AR * _edge(reading) * scale, 2),
        hp_delta=round(max(-MAX_HP, min(MAX_HP + 1.5, hp)) * scale, 2),
        magnet=round(pull, 2),
        scale=scale,
        condition=round(condition, 3),
        timing=round(timing, 1), aim=round(aim, 1), reading=round(reading, 1), physical=round(physical, 1),
    )


def for_career(db: Session, player: Player) -> Assist:
    from app.services import hand_play

    settings = settings_for(db, player)
    return for_player(player, settings.scale, settings.magnet, hand_play.session_hours(db, player))


def as_dict(assist: Assist) -> dict:
    return asdict(assist)
