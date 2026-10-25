"""The scene's skill ceiling rises with the years, and so does yours.

Players learn better ways to train, new tools appear and the best of each generation beat the previous one: the
era's top overall grows from ~84 (2009) to ~106 (2023). A career keeps its place in the pecking order by letting
every skill ceiling grow with that curve from the day it began (80% of it; the rest is only the pp meta moving).
"""

from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import world
from app.models import Player
from app.services import story, tournaments

GROWTH_SHARE = 0.8
MIN_STEP = 0.5  # apply in half-point steps so the news isn't a daily trickle


def target_growth(start_top: float, on_top: float) -> float:
    return max(0.0, GROWTH_SHARE * (on_top - start_top))


def tick(db: Session, player: Player, news: list) -> None:
    on = player.in_game_date
    top = world.era_top_overall(on)
    ref = story.get(player, "cap_ref_top")
    if ref is None:
        story.put(player, "cap_ref_top", top)
        story.put(player, "cap_growth", 0.0)
        return
    applied = float(story.get(player, "cap_growth", 0.0))
    delta = target_growth(ref, top) - applied
    if delta < MIN_STEP:
        return
    for attr in player.attributes:
        attr.cap = A.clamp(attr.cap + delta)
    player.potential = A.clamp(player.potential + delta)
    story.put(player, "cap_growth", applied + delta)
    tournaments._news(db, player, on, "SKILL_CAP",
                      f"The scene moves on: skill ceilings rise by {delta:.1f} (+{applied + delta:.1f} since your career began).",
                      1, {"delta": round(delta, 2), "total": round(applied + delta, 2)}, [])
