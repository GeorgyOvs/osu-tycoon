"""How a player looks when they play: the hand behind the numbers.

Skills decide what happens on every note; the playstyle decides how it looks, so that two players with the same
stats still play recognisably differently. It is fixed per player (drawn from their seed), shaped by their
device and tapping style and by what kind of player they are: aim players snap from note to note, stream and
tech players flow. One value reaches the outcomes too: a habit of hitting a little early or late.

Everything is a float, so it can travel with the cursor knobs to the client (see TycoonHumanGenerator there):
  tablet     1 tablet, 0 mouse
  singletap  1 single-tapper (alternates only in streams), 0 alternate
  alt_all    1 alternates every note, even slow ones (alternate players only)
  flow       0 snaps (straight, stop-and-go movements) .. 1 flows (curved, continuous)
  area       0 small tablet area / high sensitivity (twitchy) .. 1 large area / low sensitivity (sweeping)
  hold       how long keys stay down, as a factor of the usual tap (0.5 short taps .. 1.7 long presses)
  bias_x, bias_y   where on the circle they tend to hit, in circle radii
  spin       spinner speed, rotations per second
  timing_bias      mean timing error in ms (negative = early)
"""
import math
import random

from app.engine import attributes as A


def _tablet_share(year: float) -> float:
    """Tablets took over osu! over the years: about half of the players early on, most of them later."""
    return max(0.4, min(0.82, 0.45 + 0.05 * (year - 2008)))


def describe(seed: int, skills: dict[str, float], device: str | None = None, tap_style: str | None = None,
             year: float = 2014.0) -> dict[str, float]:
    rng = random.Random(f"playstyle:{seed}")
    # Every draw happens in the same order whatever is known, so a player's habits never reshuffle.
    device_roll, tap_roll, alt_roll = rng.random(), rng.random(), rng.random()
    tablet = (device == "tablet") if device else device_roll < _tablet_share(year)
    singletap = (tap_style == "singletap") if tap_style else tap_roll < (0.3 if year < 2012 else 0.12)

    aim = A.composite(skills, A.GROUPS_BY_KEY["aim"])
    tapping = A.composite(skills, A.GROUPS_BY_KEY["tapping"])
    technical = A.composite(skills, A.GROUPS_BY_KEY["technical"])
    # Stream and tech players flow; jump players snap.
    lean = (tapping + 0.5 * technical - 1.5 * aim) / 25
    flow = 1 / (1 + math.exp(-(lean + rng.gauss(0, 0.8))))

    angle = rng.random() * 2 * math.pi
    reach = abs(rng.gauss(0, 0.12))
    return {
        "tablet": 1.0 if tablet else 0.0,
        "singletap": 1.0 if singletap else 0.0,
        "alt_all": 1.0 if not singletap and alt_roll < 0.3 else 0.0,
        "flow": round(flow, 3),
        "area": round(min(1.0, max(0.0, rng.betavariate(2, 2) + (0.15 if not tablet else 0.0))), 3),
        "hold": round(min(1.7, max(0.5, rng.lognormvariate(0, 0.3))), 3),
        "bias_x": round(reach * math.cos(angle), 3),
        "bias_y": round(reach * math.sin(angle), 3),
        "spin": round(min(8.0, max(3.5, rng.gauss(5.8, 0.9))), 2),
        "timing_bias": timing_bias(seed),
    }


def timing_bias(seed: int) -> float:
    """The player's habit of hitting early (negative) or late, in ms; it moves every timing error a little."""
    return round(max(-12.0, min(10.0, random.Random(f"timing:{seed}").gauss(-3.0, 4.5))), 1)


def of_player(player, skills: dict[str, float]) -> dict[str, float]:
    return describe(player.seed, skills, player.input_device, player.tap_style, player.in_game_date.year)
