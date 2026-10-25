"""Teams and clans: pure rules and flavour (no database).

The user is always a member of their own team; `TeamMember` rows are the NPC teammates. A team of
three (user + two) can enter clan cups. Chemistry (0-100) is built by practising together and
decays when ignored; each teammate also has a personal bond with the user.
"""

import math
import random
import re
from datetime import date

TEAMS_FROM = date(2009, 1, 1)
MIN_AGE = 12
MAX_SIZE = 5  # the user plus up to four teammates
CUP_SIZE = 3
FOUND_COST = 25.0
INVITE_DAYS = 21
INVITE_COOLDOWN_DAYS = 60
LEAVE_COOLDOWN_DAYS = 30
REFUSAL_DAYS = 14
MAX_SCRIM_HOURS = 4.0

ROLES = ("leader", "anchor", "speed", "accuracy", "member")

_A = ("Neon", "Crimson", "Velvet", "Static", "Lunar", "Arctic", "Rapid", "Silent", "Golden", "Hyper", "Pixel",
      "Vortex", "Amber", "Cobalt", "Echo", "Frost", "Nimbus", "Orbit", "Quartz", "Sakura")
_B = ("Tappers", "Circles", "Clickers", "Wolves", "Collective", "Syndicate", "Riders", "Legion", "Crew", "Guild",
      "Squad", "Union", "Pact", "Order", "Division", "Dynasty")

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{1,30}[A-Za-z0-9]$")
TAG_RE = re.compile(r"^[A-Za-z0-9]{2,5}$")


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name))


def valid_tag(tag: str) -> bool:
    return bool(TAG_RE.match(tag))


def team_name(rng: random.Random, taken: set[str]) -> tuple[str, str]:
    for _ in range(50):
        a, b = rng.choice(_A), rng.choice(_B)
        name = f"{a} {b}"
        if name.lower() not in taken:
            return name, a[:3].upper() if rng.random() < 0.7 else (a[0] + b[0]).upper()
    return f"{rng.choice(_A)} {rng.choice(_B)} {rng.randint(2, 99)}", "XT"


def assign_roles(people: dict[str, dict[str, float]]) -> dict[str, str]:
    """Roles from composites (group -> value). Keys are any ids; the user is usually 'user'."""
    left = dict(people)
    roles: dict[str, str] = {}

    def overall(c: dict[str, float]) -> float:
        return sum(c.values()) / max(1, len(c))

    def take(role: str, score) -> None:
        if not left:
            return
        key = max(left, key=lambda k: (score(left[k]), -len(k)))
        roles[key] = role
        del left[key]

    take("leader", lambda c: c.get("mentality", 0) + 0.3 * overall(c))
    take("anchor", overall)
    take("speed", lambda c: c.get("tapping", 0))
    take("accuracy", lambda c: c.get("technical", 0) + 0.5 * c.get("reading", 0))
    for key in left:
        roles[key] = "member"
    return roles


def recruit_odds(user_rank: float, npc_rank: float, reputation: float, bond: float, rival_heat: float,
                 motivation: float) -> float:
    """Chance that an NPC joins. Better players want a reason; rivals rarely sign up to your team."""
    gap = math.log10(max(user_rank, 1.0) / max(npc_rank, 1.0))  # > 0: they outrank you
    p = 0.72 - 0.30 * max(0.0, gap) + 0.05 * max(0.0, -gap)
    p += reputation / 250 + bond / 300 + (motivation - 50) / 400
    if rival_heat >= 40:
        p -= 0.3
    elif rival_heat > 0:
        p -= 0.1
    return max(0.03, min(0.95, p))


def chemistry_gain(hours: float, chemistry: float, avg_bond: float) -> float:
    """A scrim: diminishing near the top, better with teammates who like you."""
    return hours * 2.6 * (0.6 + avg_bond / 120) * (1 - chemistry / 130)


def weekly_decay(chemistry: float, days_since_activity: int) -> float:
    if days_since_activity <= 7:
        return 0.0
    return min(3.0, 0.5 + 0.15 * (days_since_activity - 7)) * (0.4 + chemistry / 100)


def learning_multiplier(chemistry: float, days_since_scrim: int | None) -> float:
    """Up to +8% learning speed for two days after a scrim."""
    if days_since_scrim is None or days_since_scrim > 2:
        return 1.0
    return 1.0 + 0.08 * chemistry / 100


def nerve_factor(chemistry: float) -> float:
    """Multiplier on nerves/clutch for the team in clan cups: up to +6%."""
    return 1.0 + 0.06 * chemistry / 100


def sponsor_monthly(reputation: float, community: float) -> int:
    if reputation < 40:
        return 0
    return round((reputation - 30) * 6 * community)


def follower_gain(reputation: float) -> int:
    return int(reputation // 25)


# --- flavour ----------------------------------------------------------------------------------

BANTER = [
    "scrim was fun, same time tomorrow?", "who keeps picking the 240bpm maps lol", "{other} your aim was disgusting today (good)",
    "nice teamwork o/", "we need a better map pool for {tag}", "gg, I'm tired but one more", "{other} stop fc-ing without me",
    "anyone up for pack grind?", "{tag} gonna get that cup", "my hands hurt, need a break",
]
INVITE_DM = [
    "hey, we're building {team} - we watched your plays. wanna join?",
    "{team} is looking for someone like you. interested?",
    "your rank is climbing fast, come play for {team} :)",
]
DRAMA = [
    "can we stop arguing about who plays anchor?", "{other} did you leave the lobby on purpose?",
    "ok I'm muting this chat for a day", "this is not what we agreed on",
]
CELEBRATE = ["LETS GOOO", "gg wp everyone", "{tag} on top!!", "can't believe we did it"]
POACH = ["{other} got an offer from another team...", "heard {other} might be leaving"]


def line(rng: random.Random, pool: list[str], **fmt: str) -> str:
    return rng.choice(pool).format(**fmt)
