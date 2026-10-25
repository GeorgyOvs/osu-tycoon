"""Mentors: stronger players who coach one skill group. Pure rules; the service holds the state."""

import random

MENTOR_FROM_YEAR = 2009
MIN_AGE = 10
MENTOR_DRILL_SHARE = 0.6
BOOST_DAYS = 5
BOOST_BASE = 1.25
ASK_COOLDOWN_DAYS = 14
IDLE_GRACE_DAYS = 14
IDLE_DECAY_PER_DAY = 0.25
GRADUATION_MARGIN = 2.0
PRO_COST_PER_HOUR = 20.0

GROUP_LABELS = {"aim": "Aim", "tapping": "Tapping", "reading": "Reading", "technical": "Technical",
                "mentality": "Mentality", "physical": "Physical"}

ADVICE = {
    "aim": ["Stop chasing the cursor; aim ahead of it.", "Small, relaxed movements beat big tense ones.",
            "Slow the map down until the pattern is clean, then speed it up."],
    "tapping": ["Relax the wrist: tension is what kills your streams.", "Practise bursts, not endless streams.",
                "Your rhythm is fine; your timing breaks when you tense up."],
    "reading": ["Look at the next three circles, not the one you're hitting.", "Read the rhythm before the geometry.",
                "Drop the AR for a week; reading comes back stronger."],
    "technical": ["Slider ends are free time; use them to reposition.", "Learn the angle, not the map.",
                  "Buzz sliders are about feel, not speed."],
    "mentality": ["Nobody is watching as closely as you think.", "A miss is one note, not the whole map.",
                  "Breathe on the long breaks; that's where nerves build."],
    "physical": ["Take a break every hour. Your hands will thank you.", "Posture first, mouse second.",
                 "Warm up before ranked, always."],
}


def acceptance_chance(*, motivation: float, same_country: bool, followers: int, gap: float, rival_heat: float | None,
                      past_bond: float = 0.0) -> float:
    """Probability that a stronger player agrees to coach; rivals never do."""
    if rival_heat is not None and rival_heat >= 25:
        return 0.0
    p = 0.25 + 0.25 * motivation / 100 + (0.10 if same_country else 0.0) + min(0.15, followers / 5000)
    p += 0.002 * past_bond
    p -= 0.012 * max(0.0, gap - 15)
    return max(0.05, min(0.85, p))


def roll(seed: str, chance: float) -> bool:
    return random.Random(seed).random() < chance


def boost_for(bond: float) -> float:
    return round(min(1.5, BOOST_BASE + bond / 400), 3)
