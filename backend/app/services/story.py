"""Glue for the story layer (life events, goals/arcs, teams): shared player state and one tick hook."""

from datetime import date

from sqlalchemy.orm import Session

from app.models import Player


def get(player: Player, key: str, default=None):
    return (player.story_state or {}).get(key, default)


def put(player: Player, key: str, value) -> None:
    player.story_state = {**(player.story_state or {}), key: value}


def get_date(player: Player, key: str, default: date) -> date:
    raw = get(player, key)
    return date.fromisoformat(raw) if raw else default


def put_date(player: Player, key: str, value: date) -> None:
    put(player, key, value.isoformat())


# --- lasting effects (from life events): [{event_id, until, free_hours, learning, play, label_en, label_ru}] ---


def mods(player: Player, on: date | None = None) -> list[dict]:
    day = (on or player.in_game_date).isoformat()
    return [m for m in get(player, "mods", []) if m["until"] >= day and m.get("from", "") <= day]


# Several sources of the same kind stack with diminishing returns: the product is clamped to a sane band.
LIMITS = {"recovery": (0.7, 1.35), "injury": (0.55, 1.6), "income": (0.6, 1.5), "followers_mult": (0.6, 1.6),
          "learning": (0.5, 1.5), "pack": (0.8, 1.4), "hiatus": (0.6, 1.3)}


def mod_sum(player: Player, key: str, on: date | None = None) -> float:
    return sum(m.get(key, 0.0) for m in mods(player, on))


def mod_product(player: Player, key: str, on: date | None = None) -> float:
    out = 1.0
    for m in mods(player, on):
        out *= m.get(key, 1.0)
    lo, hi = LIMITS.get(key, (0.0, 99.0))
    if key.startswith("learn_"):
        lo, hi = 0.8, 1.6
    elif key.startswith("skill_"):
        lo, hi = 0.9, 1.15
    return max(lo, min(hi, out))


def skill_multipliers(player: Player, on: date | None = None) -> dict[str, float]:
    """{sub_stat: multiplier} from every active 'skill_<sub_stat>' modifier."""
    out: dict[str, float] = {}
    for m in mods(player, on):
        for k, v in m.items():
            if k.startswith("skill_"):
                out[k[6:]] = out.get(k[6:], 1.0) * v
    return {k: max(0.9, min(1.15, v)) for k, v in out.items()}


def add_mod(player: Player, mod: dict) -> None:
    put(player, "mods", [*get(player, "mods", []), mod])


def prune_mods(player: Player, on: date) -> None:
    put(player, "mods", mods(player, on))


def tick(db: Session, player: Player, news: list) -> None:
    """Called at the end of every world advance. Each system keeps its own watermark in story_state."""
    from app.services import chatter, events, goals, integrity, teams

    events.tick(db, player, news)
    teams.tick(db, player, news)
    goals.tick(db, player, news)
    chatter.tick(db, player, news)
    from app.services import profile_stats, progression

    progression.tick(db, player, news)
    profile_stats.snapshot(db, player)
    integrity.tick(db, player, news)
    from app.services import mentors

    mentors.tick(db, player, news)
    from app.services import legacy

    legacy.tick(db, player, news)
