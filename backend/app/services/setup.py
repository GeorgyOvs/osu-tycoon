"""The player's setup condition: gear wear, settings comfort and connection quality."""

from sqlalchemy.orm import Session

from app.engine import gear, network, wear
from app.models import Player
from app.services import story


class SetupError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def wear_state(player: Player) -> dict[str, float]:
    return dict(story.get(player, "wear", {}))


def wear_of(player: Player, category: str) -> float:
    return float(wear_state(player).get(category, 0.0))


def active_categories(player: Player) -> list[str]:
    return [player.input_device if player.input_device in ("mouse", "tablet") else "mouse", "keyboard"]


def worst_wear(player: Player) -> float:
    return max(wear_of(player, c) for c in active_categories(player))


def comfort(player: Player) -> float:
    return float(story.get(player, "comfort", wear.COMFORT_START))


def isp_level(player: Player) -> int:
    return int(story.get(player, "isp_level", 0))


def multipliers(player: Player) -> tuple[float, float]:
    """(aim, tapping) multipliers from worn gear and unsettled settings."""
    c = wear.comfort_multiplier(comfort(player))
    device, keyboard = active_categories(player)
    return wear.wear_multiplier(wear_of(player, device)) * c, wear.wear_multiplier(wear_of(player, keyboard)) * c


def add_hours(player: Player, hours: float) -> None:
    if hours <= 0:
        return
    state = wear_state(player)
    for category in active_categories(player):
        state[category] = round(wear.grow_wear(state.get(category, 0.0), category, hours), 4)
    story.put(player, "wear", state)
    story.put(player, "comfort", round(wear.grow_comfort(comfort(player), hours), 4))


def reset_wear(player: Player, category: str) -> None:
    if category in wear.CATEGORIES:
        state = wear_state(player)
        state[category] = 0.0
        story.put(player, "wear", state)


def on_gear_change(player: Player, category: str) -> None:
    """A different item in use: partly lost settings comfort."""
    if category in ("mouse", "tablet"):
        story.put(player, "comfort", round(comfort(player) * wear.COMFORT_AFTER_GEAR_CHANGE, 4))


def on_device_switch(player: Player) -> None:
    story.put(player, "comfort", round(comfort(player) * wear.COMFORT_AFTER_DEVICE_SWITCH, 4))


def adjust_wear(player: Player, delta: float) -> float:
    """Used by life events: negative repairs the active input device, positive wears it."""
    state = wear_state(player)
    category = active_categories(player)[0]
    state[category] = round(max(0.0, min(1.0, state.get(category, 0.0) + delta)), 4)
    story.put(player, "wear", state)
    return state[category]


def _equipped(db: Session, player: Player, category: str):
    from app.services import condition

    return next((i for i in condition.equipped(db, player) if i.category == category), None)


def maintain(db: Session, player: Player, category: str) -> dict:
    if category not in wear.CATEGORIES:
        raise SetupError(422, f"unknown category '{category}'")
    cost = wear.SERVICE_COST[category]
    if player.money < cost:
        raise SetupError(409, f"servicing the {category} costs ${cost:.0f}; you have ${player.money:.0f}")
    player.money -= cost
    state = wear_state(player)
    state[category] = round(max(0.0, state.get(category, 0.0) - wear.SERVICE_REMOVES), 4)
    story.put(player, "wear", state)
    return {"category": category, "cost": cost, "wear": state[category]}


def replace(db: Session, player: Player, category: str) -> dict:
    if category not in wear.CATEGORIES:
        raise SetupError(422, f"unknown category '{category}'")
    item = _equipped(db, player, category)
    if item is None:
        raise SetupError(409, f"no {category} is equipped")
    cost = round(item.price_on(player.in_game_date) * wear.REPLACE_PRICE_SHARE)
    if player.money < cost:
        raise SetupError(409, f"a new {category} costs ${cost}; you have ${player.money:.0f}")
    player.money -= cost
    state = wear_state(player)
    state[category] = 0.0
    story.put(player, "wear", state)
    if category in ("mouse", "tablet"):  # same model: only a little of the feel is lost
        story.put(player, "comfort", round(comfort(player) * 0.9, 4))
    return {"category": category, "cost": cost, "wear": 0.0}


def isp_price(player: Player) -> float | None:
    level = isp_level(player)
    return None if level >= network.MAX_ISP_LEVEL else network.ISP_COST[level]


def upgrade_isp(player: Player) -> dict:
    price = isp_price(player)
    if price is None:
        raise SetupError(409, "your connection is already as good as it gets")
    if player.in_game_date.year < 2009:
        raise SetupError(409, "no better plans are on offer yet")
    if player.money < price:
        raise SetupError(409, f"a better connection costs ${price:.0f}; you have ${player.money:.0f}")
    player.money -= price
    story.put(player, "isp_level", isp_level(player) + 1)
    return {"cost": price, "isp_level": isp_level(player)}


def ping_to(player: Player, country: str) -> int:
    return network.ping(network.region(player.country), network.region(country), player.in_game_date.year, isp_level(player))


def overview(db: Session, player: Player) -> dict:
    year = player.in_game_date.year
    own = network.region(player.country)
    devices = active_categories(player)
    rows = []
    for category in wear.CATEGORIES:
        item = _equipped(db, player, category)
        w = wear_of(player, category)
        rows.append({
            "category": category, "item": item.name if item else None, "active": category in devices,
            "wear": round(w, 3), "condition": wear.condition_label(w),
            "penalty": round(1 - wear.wear_multiplier(w), 4),
            "service_cost": wear.SERVICE_COST[category],
            "replace_cost": round(item.price_on(player.in_game_date) * wear.REPLACE_PRICE_SHARE) if item else None,
        })
    lobby = network.lobby_ping(own, year, isp_level(player))
    return {
        "wear": rows,
        "comfort": round(comfort(player), 3), "comfort_penalty": round(1 - wear.comfort_multiplier(comfort(player)), 4),
        "network": {
            "region": own, "region_name": network.REGION_NAMES[own], "local_ping": ping_to(player, player.country),
            "lobby_ping": lobby, "tier": network.tier(lobby), "isp_level": isp_level(player),
            "isp_max": network.MAX_ISP_LEVEL, "isp_price": isp_price(player),
            "pressure_penalty": round(network.pressure_factor(lobby) - 1, 4),
            "regional_servers": year >= 2018,
        },
        "money": round(player.money, 2),
    }
