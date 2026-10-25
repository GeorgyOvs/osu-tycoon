"""Gear wear and settings comfort.

Wear (0..1) builds per equipped category with hours played; it shaves a little off aim/tapping and makes
misclicks likelier until the item is serviced or replaced. Comfort (0..1) is how settled your sensitivity,
tablet area and key bindings are: it grows with consistent use and is partly lost when you change gear.
"""

WEAR_PER_HOUR = {"mouse": 0.0007, "tablet": 0.0006, "keyboard": 0.0006}
CATEGORIES = tuple(WEAR_PER_HOUR)
SERVICE_COST = {"mouse": 15.0, "tablet": 20.0, "keyboard": 12.0}
SERVICE_REMOVES = 0.35  # a cleaning / new switches / new pen nib takes this much wear away
REPLACE_PRICE_SHARE = 0.5  # a replacement of the same item costs half its street price
COMFORT_START = 0.5
COMFORT_PER_HOUR = 0.004
COMFORT_AFTER_GEAR_CHANGE = 0.6
COMFORT_AFTER_DEVICE_SWITCH = 0.7
WORN_EVENT_THRESHOLD = 0.3


def wear_multiplier(wear: float) -> float:
    """Aim/tapping multiplier of worn gear (1.0 new, ~0.95 when completely worn out)."""
    return 1.0 - 0.05 * max(0.0, min(1.0, wear)) ** 1.5


def comfort_multiplier(comfort: float) -> float:
    return 0.97 + 0.03 * max(0.0, min(1.0, comfort))


def grow_wear(wear: float, category: str, hours: float) -> float:
    return min(1.0, wear + WEAR_PER_HOUR.get(category, 0.0) * hours)


def grow_comfort(comfort: float, hours: float) -> float:
    return comfort + (1.0 - comfort) * min(1.0, COMFORT_PER_HOUR * hours)


def condition_label(wear: float) -> str:
    if wear < 0.15:
        return "like new"
    if wear < 0.35:
        return "used"
    if wear < 0.65:
        return "worn"
    return "worn out"
