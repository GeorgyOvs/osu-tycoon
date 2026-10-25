"""The living world: NPC careers ticking weekly on composites only.

Legends follow their historical curve (world_data) plus a random walk; procedural players
get a generated career (rise, prime, decline, retirement). Both can get injured, slump,
take hiatuses, or be fired up by a rivalry. Everything is seeded, so a world replays
identically.
"""

import bisect
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

from app.engine import attributes as A
from app.engine import pp_history
from app.engine.world_data import COUNTRIES, LEGENDS, NAME_HEADS, NAME_TAILS, NAME_WORDS, Legend
from app.services.ranking import estimate_global_rank, top_pp

LEGENDS_BY_NAME = {legend.name: legend for legend in LEGENDS}
RESERVED_NAMES = set(LEGENDS_BY_NAME) | {alias for legend in LEGENDS for alias in legend.aliases}
GROUP_KEYS = [g.key for g in A.GROUPS]

# Best overall rating in the world over time: the competitive ceiling keeps rising.
_ERA_TOP: list[tuple[float, float]] = [
    (2007.7, 75), (2009.0, 82), (2011.0, 90), (2012.5, 97), (2015.0, 97), (2017.0, 98), (2019.0, 99),
    (2021.0, 101), (2023.0, 106), (2025.0, 108),
]
PP_PER_POINT = 0.045  # pp = era top pp * exp(0.045 * (overall - era top overall))
STYLE_SPREAD = 0.15  # a style of +1 puts a composite 15% above overall

# Playstyle archetypes: style vectors in units of STYLE_SPREAD (so +2 = 30% above overall).
ARCHETYPES: dict[str, dict[str, float]] = {
    "farmer": {"aim": 2.0, "tapping": -1.4, "reading": 0.4, "technical": 0.2, "mentality": -0.4, "physical": -0.6},
    "streamer": {"aim": -1.0, "tapping": 2.0, "reading": -0.2, "technical": -0.6, "mentality": 0.0, "physical": 1.4},
    "tech": {"aim": 0.2, "tapping": -0.6, "reading": 1.4, "technical": 2.0, "mentality": 0.2, "physical": -0.6},
    "all-rounder": {"aim": 0.2, "tapping": 0.2, "reading": 0.2, "technical": 0.0, "mentality": 0.0, "physical": 0.0},
    "tournament player": {"aim": -0.3, "tapping": -0.3, "reading": 0.5, "technical": 0.4, "mentality": 2.0, "physical": 0.4},
    "reader": {"aim": 0.0, "tapping": -0.8, "reading": 2.0, "technical": 0.8, "mentality": 0.2, "physical": -0.4},
}
ARCHETYPE_WEIGHTS = {"farmer": 3, "streamer": 2, "tech": 2, "all-rounder": 3, "tournament player": 1, "reader": 1}

# How much each skill group is worth for *pp* (the best plays in the era's meta). Mentality is absent:
# scores can be retried hundreds of times, so nerves barely matter for pp (they decide matches).
PP_META: dict[str, dict[str, float]] = {
    "ranked_score": {"aim": 0.27, "tapping": 0.27, "reading": 0.2, "technical": 0.13, "physical": 0.13},
    "ppv1": {"aim": 0.27, "tapping": 0.27, "reading": 0.2, "technical": 0.13, "physical": 0.13},
    "ppv2": {"aim": 0.36, "tapping": 0.26, "reading": 0.2, "technical": 0.1, "physical": 0.08},  # jump farm and DT
    "ppv2_2021_01": {"aim": 0.36, "tapping": 0.26, "reading": 0.2, "technical": 0.1, "physical": 0.08},
    "ppv2_2021_11": {"aim": 0.34, "tapping": 0.3, "reading": 0.18, "technical": 0.1, "physical": 0.08},  # streams uncapped
    "ppv2_2024_10": {"aim": 0.3, "tapping": 0.28, "reading": 0.18, "technical": 0.14, "physical": 0.1},
}
SPECIALIST_BONUS = 0.35  # top scores come from the best skill type: a peak counts beyond the average
PEAK_NORM = 1.052  # keeps the average player at their overall, so rank curves stay calibrated

PROCEDURAL_COUNT = 1600
PROCEDURAL_WITH_REAL = 1200
WEEK = timedelta(days=7)


@dataclass
class WorldNews:
    type: str
    message: str
    importance: int = 1
    data: dict | None = None


def _year(d: date) -> float:
    return d.year + (d.timetuple().tm_yday - 1) / 366


def _interp(points: list[tuple[float, float]], x: float) -> float:
    xs = [p[0] for p in points]
    if x <= xs[0]:
        return points[0][1]
    if x >= xs[-1]:
        return points[-1][1]
    i = bisect.bisect_right(xs, x)
    (x0, y0), (x1, y1) = points[i - 1], points[i]
    return y0 + (x - x0) / (x1 - x0) * (y1 - y0)


def era_top_overall(on: date) -> float:
    return _interp(_ERA_TOP, _year(on))


def pp_for_overall(overall: float, on: date) -> float:
    return top_pp(on) * math.exp(PP_PER_POINT * (overall - era_top_overall(on)))


def overall_for_pp(pp: float, on: date) -> float:
    return era_top_overall(on) + math.log(max(pp, 1.0) / top_pp(on)) / PP_PER_POINT


# Calibration (tools/calibrate_skill.py, real careers): a player's note-by-note play earns about 20% more pp than an
# NPC of the same number on this curve, i.e. ~4 points. The NPC curve is anchored to real rank/pp history, so instead
# of weakening the player, every NPC's *playing* skill is shown and simulated 4 points below the curve value: a rank-76
# NPC and a rank-76 player now carry the same numbers. pp for NPCs is unchanged (pp_overall adds the offset back).
SKILL_OFFSET = 4.0


def display_overall(curve_overall: float) -> float:
    """An NPC's overall on the player's scale."""
    return A.clamp(curve_overall - SKILL_OFFSET)


def composites(overall: float, style: dict[str, float]) -> dict[str, float]:
    return {g: A.clamp(display_overall(overall) * (1 + STYLE_SPREAD * style.get(g, 0.0))) for g in GROUP_KEYS}


def pp_overall(comps: dict[str, float], on: date) -> float:
    """The overall rating that matters for pp in this era's meta: a weighted mean over the skills that
    produce top scores, plus credit for the best of them (specialists farm their strongest type)."""
    weights = PP_META[pp_history.era_for(on).key]
    mean = sum(comps[g] * w for g, w in weights.items())
    peak = max(comps[g] for g in weights)
    return (mean + SPECIALIST_BONUS * max(0.0, peak - mean)) / PEAK_NORM + SKILL_OFFSET / PEAK_NORM


TOURNAMENT_WEIGHTS = {
    "aim": 0.18, "tapping": 0.18, "reading": 0.16,
    "technical": 0.16, "mentality": 0.22, "physical": 0.10,
}


def tournament_overall(comps: dict[str, float]) -> float:
    """Pool-wide strength. Unlike pp potential it rewards nerves and having no free ban."""
    mean = sum(comps[g] * w for g, w in TOURNAMENT_WEIGHTS.items())
    spread = max(comps.values()) - min(comps.values())
    return A.clamp(mean - 0.08 * spread)


def best_score_types(comps: dict[str, float]) -> list[str]:
    """Human-readable scouting summary derived from the player's strongest map families."""
    candidates = {
        "DT jumps": 0.72 * comps["aim"] + 0.28 * comps["tapping"],
        "220+ BPM streams": 0.68 * comps["tapping"] + 0.32 * comps["physical"],
        "awkward tech": 0.65 * comps["technical"] + 0.35 * comps["reading"],
        "HD and reading": 0.72 * comps["reading"] + 0.28 * comps["aim"],
        "HR precision": 0.58 * comps["aim"] + 0.42 * comps["technical"],
    }
    return sorted(candidates, key=candidates.get, reverse=True)[:2]


def archetype(style: dict[str, float]) -> str:
    """Closest archetype to a style vector (legends and older worlds have free-form styles)."""
    def dist(a: dict[str, float]) -> float:
        return sum((style.get(g, 0.0) * 1.0 - a.get(g, 0.0) * 0.5) ** 2 for g in GROUP_KEYS)

    return min(ARCHETYPES, key=lambda k: dist(ARCHETYPES[k]))


def random_style(rng: random.Random) -> dict[str, float]:
    kind = rng.choices(list(ARCHETYPE_WEIGHTS), list(ARCHETYPE_WEIGHTS.values()))[0]
    return {g: round(ARCHETYPES[kind][g] * 0.5 + rng.uniform(-0.35, 0.35), 2) for g in GROUP_KEYS}


def initialize_development(npc) -> None:
    """Give a fictional NPC stable aptitudes and a career-arc personality."""
    if npc.development:
        return
    rng = random.Random(f"development:{npc.seed}")
    era = pp_history.era_for(npc.join_date or date(2007, 9, 16)).key
    aptitudes = {g: round(rng.uniform(0.7, 1.3), 3) for g in GROUP_KEYS}
    weights = PP_META[era]
    focus = max(weights, key=lambda g: weights[g] * aptitudes[g] * (1 + max(0, npc.style.get(g, 0))))
    npc.development = {
        "focus": focus, "aptitudes": aptitudes, "meta": era, "retraining_weeks": 0,
        "training_weeks": 0, "plateau_weeks": 0, "plateau_anchor": None,
        "breakthroughs": 0,
    }
    npc.story = {
        "arc": rng.choices(
            ["prodigy", "grinder", "late bloomer", "volatile"], [2, 4, 2, 2]
        )[0],
        "phase": "rise", "rival_id": None, "rival_ahead": None,
        "comebacks": 0, "max_score_pp": 0.0,
    }


def _arc_modifier(npc, on: date) -> float:
    if not npc.join_date or not npc.story:
        return 0.0
    years = max(0.0, (on - npc.join_date).days / 365)
    progress = min(1.0, years / max(npc.ramp_years, 0.5))
    arc = npc.story.get("arc")
    if arc == "prodigy":
        return 3.0 * math.sin(math.pi * progress)
    if arc == "late bloomer":
        return -2.5 * math.sin(math.pi * progress) + (1.5 if progress >= 1 else 0)
    if arc == "volatile":
        return 1.2 * math.sin(years * 5.1 + npc.seed % 7)
    return 0.0


def _advance_development(npc, on: date, base: float, status: str, notable: bool,
                         rng: random.Random) -> tuple[float, list[WorldNews]]:
    """Deliberate practice, meta adaptation and persistent plateau/breakthrough arcs."""
    if npc.kind != "procedural":
        return base, []
    initialize_development(npc)
    dev = dict(npc.development)
    story = dict(npc.story)
    news: list[WorldNews] = []
    era = pp_history.era_for(on).key
    aptitudes = dev["aptitudes"]

    if status in ("injured", "hiatus"):
        story["phase"] = "recovery" if status == "injured" else "burnout"
    elif status == "active" and not dev.get("plateau_weeks"):
        breakthrough_on = story.get("breakthrough_on")
        still_breaking_through = breakthrough_on and (on - date.fromisoformat(breakthrough_on)).days < 84
        if not still_breaking_through:
            years = (on - npc.join_date).days / 365 if npc.join_date else 0
            story["phase"] = ("rise" if years < npc.ramp_years else
                              "prime" if years < npc.ramp_years + npc.prime_years else "decline")

    if era != dev.get("meta"):
        old_focus = dev["focus"]
        new_focus = max(PP_META[era], key=lambda g: PP_META[era][g] * aptitudes[g]
                        * (1 + max(0, npc.style.get(g, 0))))
        # Some players rebuild their game for the patch; others trust what already works.
        retrains = rng.random() < 0.58 and new_focus != old_focus
        dev.update({"meta": era, "retraining_weeks": rng.randint(18, 52) if retrains else 0})
        if retrains:
            dev["focus"] = new_focus
            if notable:
                news.append(WorldNews("RETRAINING", f"{npc.name} is rebuilding their game for the new pp meta: "
                                      f"{old_focus} -> {new_focus}.", 2,
                                      {"from": old_focus, "to": new_focus}))

    if status == "active":
        dev["training_weeks"] = int(dev.get("training_weeks", 0)) + 1
        plateau = int(dev.get("plateau_weeks", 0))
        rising = npc.join_date and (on - npc.join_date).days / 365 < npc.ramp_years + npc.prime_years
        if not plateau and rising and dev["training_weeks"] > 20 and rng.random() < 0.008:
            plateau = 1
            dev["plateau_anchor"] = npc.overall or base
            story["phase"] = "plateau"
            if notable:
                news.append(WorldNews("PLATEAU", f"{npc.name}'s rapid progress has stalled at a plateau.", 2))
        elif plateau:
            plateau += 1
            if plateau >= 12 and (rng.random() < 0.035 or plateau >= 80):
                plateau = 0
                dev["breakthroughs"] = int(dev.get("breakthroughs", 0)) + 1
                dev["plateau_anchor"] = None
                npc.deviation = min(8.0, npc.deviation + rng.uniform(1.5, 3.5))
                style = dict(npc.style)
                style[dev["focus"]] = min(2.7, style.get(dev["focus"], 0) + 0.12)
                npc.style = style
                story["phase"] = "breakthrough"
                story["breakthrough_on"] = on.isoformat()
                if notable:
                    news.append(WorldNews("BREAKTHROUGH", f"{npc.name} breaks through a long plateau!", 3,
                                          {"focus": dev["focus"]}))
        dev["plateau_weeks"] = plateau

        # NPCs practise what helps their best scores. Off-focus skills barely move relative to OVR.
        style = dict(npc.style)
        focus = dev["focus"]
        gain = 0.0008 if plateau else 0.004
        if dev.get("retraining_weeks", 0):
            gain *= 1.7
            dev["retraining_weeks"] -= 1
        gain *= aptitudes[focus]
        for g in GROUP_KEYS:
            style[g] = round(max(-2.7, min(2.7, style.get(g, 0) + (gain if g == focus else -gain / 5))), 4)
        npc.style = style

        if plateau and dev.get("plateau_anchor") is not None:
            base = min(base, float(dev["plateau_anchor"]) + 0.25)

    npc.development = dev
    npc.story = story
    return base + _arc_modifier(npc, on), news


def substats(comps: dict[str, float], seed: int) -> dict[str, float]:
    """Expand composites into the 21 sub-stats the play simulator needs (seeded jitter)."""
    rng = random.Random(seed)
    out = {}
    for group in A.GROUPS:
        for sub in group.subs:
            out[sub.key] = A.clamp(comps[group.key] + rng.gauss(0, 4))
    return out


# --- legends ---------------------------------------------------------------------------


def _ym(text: str) -> float:
    y, m = text.split("-")
    return int(y) + (int(m) - 1) / 12


def legend_status(legend: Legend, on: date) -> str:
    y = _year(on)
    if y < _ym(legend.curve[0][0]):
        return "not_started"
    for start, end, status in legend.breaks:
        if _ym(start) <= y and (end is None or y < _ym(end) + 1 / 12):
            return status
    return "active"


def legend_curve(legend: Legend, on: date, shift_weeks: int = 0) -> float:
    """Curve value; a rivalry shift delays everything after the legend's peak."""
    points = [(_ym(d), v) for d, v in legend.curve]
    y = _year(on)
    peak_x = max(points, key=lambda p: p[1])[0]
    if shift_weeks and y > peak_x:
        y = max(peak_x, y - shift_weeks / 52)
    return _interp(points, y)


# --- procedural players ------------------------------------------------------------------


def generate_name(rng: random.Random, taken: set[str]) -> str:
    for _ in range(50):
        roll = rng.random()
        if roll < 0.4:
            name = rng.choice(NAME_HEADS) + rng.choice(NAME_TAILS)
        elif roll < 0.7:
            name = rng.choice(NAME_WORDS) + rng.choice(["", "_", "-"]) + rng.choice(NAME_HEADS).lower()
        else:
            name = rng.choice(NAME_HEADS) + rng.choice(NAME_TAILS) + str(rng.randint(1, 999))
        if rng.random() < 0.15:
            name = name.capitalize()
        elif rng.random() < 0.1:
            name = name.lower()
        if name not in taken and name not in RESERVED_NAMES:
            taken.add(name)
            return name
    name = f"player{len(taken)}"
    taken.add(name)
    return name


def generate_country(rng: random.Random) -> str:
    countries, weights = zip(*COUNTRIES)
    return rng.choices(countries, weights=weights)[0]


@dataclass
class ProceduralCareer:
    name: str
    country: str
    style: dict[str, float]
    seed: int
    join_date: date
    peak: float
    ramp_years: float
    prime_years: float
    decline_per_year: float


def generate_procedural(world_seed: int, count: int = PROCEDURAL_COUNT) -> list[ProceduralCareer]:
    """Careers spread over 2005-2025 so every era has a full field at every level."""
    rng = random.Random(f"world:{world_seed}")
    taken: set[str] = set()
    out = []
    for i in range(count):
        join = date(2005, 1, 1) + timedelta(days=rng.randint(0, 20 * 365))
        ramp = rng.uniform(1.0, 4.0)
        peak_date = join + timedelta(days=int(ramp * 365))
        # Distance below the era's best. Roughly log-uniform ranks down to ~300k, but sparse at
        # the very top so the elite stays a small club (mostly legends).
        peak = era_top_overall(min(peak_date, date(2025, 6, 1))) - (2 + 53 * rng.random() ** 0.6)
        out.append(
            ProceduralCareer(
                name=generate_name(rng, taken),
                country=generate_country(rng),
                style=random_style(rng),
                seed=rng.randint(0, 2**31 - 1),
                join_date=join,
                peak=round(peak, 1),
                ramp_years=round(ramp, 2),
                prime_years=round(rng.uniform(0.5, 4.0), 2),
                decline_per_year=round(rng.uniform(1.5, 6.0), 2),
            )
        )
    return out


def real_career(rec: dict, fetched: date, world_seed: int) -> ProceduralCareer | None:
    """A real player's career from API anchors: joined -> highest rank (dated) -> current rank."""
    from app.services.ranking import pp_for_rank

    try:
        join = date.fromisoformat(rec["join_date"])
    except (KeyError, TypeError, ValueError):
        return None
    peak_rank = rec.get("highest_rank") or rec.get("current_rank")
    if not peak_rank:
        return None
    peak_date = date.fromisoformat(rec["highest_rank_date"]) if rec.get("highest_rank_date") else fetched
    peak_date = max(peak_date, join + timedelta(days=180))
    peak = overall_for_pp(pp_for_rank(peak_rank, peak_date), peak_date)
    if rec.get("current_rank"):
        now = overall_for_pp(pp_for_rank(rec["current_rank"], fetched), fetched)
    else:
        now = peak - 15  # no longer ranked
    years_after = max(0.5, (fetched - peak_date).days / 365)
    rng = random.Random(f"real:{world_seed}:{rec.get('id')}")
    return ProceduralCareer(
        name=rec["name"], country=rec.get("country") or "XX",
        style={g: round(rng.uniform(-1, 1), 2) for g in GROUP_KEYS}, seed=rng.randint(0, 2**31 - 1),
        join_date=join, peak=round(peak, 1), ramp_years=round(max(0.5, (peak_date - join).days / 365), 2),
        # Negative "decline" = still improving: the overall ceiling keeps rising over the years.
        prime_years=0.3, decline_per_year=round((peak - now) / years_after, 2),
    )


def procedural_curve(c, on: date) -> float | None:
    """Career curve value, or None before joining. `c` is a ProceduralCareer or Npc row."""
    if c.join_date is None or on < c.join_date:
        return None
    years = (on - c.join_date).days / 365
    start = max(5.0, c.peak * 0.25)
    if years < c.ramp_years:
        return start + (c.peak - start) * (1 - math.exp(-3 * years / c.ramp_years)) / (1 - math.exp(-3))
    after_prime = years - c.ramp_years - c.prime_years
    return c.peak - max(0.0, after_prime) * c.decline_per_year


# --- weekly tick --------------------------------------------------------------------------


def weekly_step(npc, on: date, notable: bool) -> list[WorldNews]:
    """Advance one NPC by a week. `npc` is an Npc row; `notable` = worth a headline."""
    rng = random.Random(f"{npc.seed}:{on.isoformat()}")
    news: list[WorldNews] = []
    legend = LEGENDS_BY_NAME.get(npc.name) if npc.kind == "legend" else None
    previous = npc.status

    # Career curve and scripted breaks.
    if legend:
        scripted = legend_status(legend, on)
        base = legend_curve(legend, on, npc.curve_shift_weeks)
        if scripted == "retired" and npc.curve_shift_weeks > 0:
            npc.curve_shift_weeks -= 1  # a rivalry keeps them going a while longer
            scripted = "active"
    else:
        base = procedural_curve(npc, on)
        scripted = "not_started" if base is None else "active"
        if base is not None and npc.status != "retired" and npc.kind == "procedural":
            years_past_prime = (on - npc.join_date).days / 365 - npc.ramp_years - npc.prime_years
            if years_past_prime > 0 and rng.random() < 0.004 + 0.003 * years_past_prime:
                scripted = "retired"
        if npc.status == "retired":
            scripted = "retired"

    # Random walk around the curve, form and motivation.
    npc.deviation = max(-8.0, min(8.0, 0.93 * npc.deviation + rng.gauss(0, 0.8)))
    npc.form = max(-2.0, min(2.0, 0.7 * npc.form + rng.gauss(0, 0.35)))
    npc.motivation = max(0.0, min(100.0, npc.motivation + 0.1 * (70 - npc.motivation) + rng.gauss(0, 2)))

    status = scripted
    if scripted == "active":
        if npc.away_until and on < npc.away_until:
            status = npc.status if npc.status in ("injured", "hiatus") else "active"
        else:
            npc.away_until = None
            intensity = max(0.0, (npc.overall - 50) / 50)
            if rng.random() < 0.002 + 0.004 * intensity:
                weeks = rng.randint(2, 10)
                npc.away_until = on + weeks * WEEK
                status = "injured"
                if notable:
                    news.append(WorldNews("INJURY", f"{npc.name} is out with a wrist injury (~{weeks} weeks).", 2,
                                          {"weeks": weeks}))
            elif npc.motivation < 30 and rng.random() < 0.02:
                weeks = rng.randint(4, 26)
                npc.away_until = on + weeks * WEEK
                status = "hiatus"
                if notable:
                    news.append(WorldNews("HIATUS", f"{npc.name} announces a break from osu! (~{weeks} weeks).", 2,
                                          {"weeks": weeks}))

    if base is not None:
        base, development_news = _advance_development(npc, on, base, status, notable, rng)
        news.extend(development_news)
        penalty = {"injured": 6.0, "hiatus": 4.0, "inactive": 8.0, "restricted": 0.0}.get(status, 0.0)
        npc.overall = A.clamp(base + npc.deviation - penalty, 1, A.ATTR_ABSOLUTE_MAX)
    npc.status = status

    if legend and previous != status and previous != "not_started":
        if status == "retired":
            news.append(WorldNews("RETIRED", f"{npc.name} retires from competitive osu!.", 3))
        elif status == "inactive":
            news.append(WorldNews("INACTIVE", f"{npc.name} goes quiet; the account has gone inactive.", 3))
        elif status == "active" and previous in ("inactive", "retired"):
            news.append(WorldNews("RETURN", f"{npc.name} is back!", 3))
    elif notable and previous == "active" and status == "retired":
        news.append(WorldNews("RETIRED", f"{npc.name} quietly retires.", 1))
    elif notable and previous in ("injured", "hiatus") and status == "active":
        story = dict(npc.story or {})
        story["comebacks"] = int(story.get("comebacks", 0)) + 1
        npc.story = story
        news.append(WorldNews("COMEBACK", f"{npc.name} returns after {previous} and begins a comeback.", 2,
                              {"from": previous, "comebacks": story["comebacks"]}))
    return news


PP_SMOOTHING = 0.15  # pp is a sum of best plays: it follows skill with a lag of ~10 weeks


def refresh_pp(npc, on: date, smooth: bool = True) -> None:
    if npc.status in ("not_started", "retired", "inactive", "restricted"):
        npc.rank = None  # hidden from the rankings, but their pp is kept for a comeback
        if npc.status == "not_started":
            npc.pp = 0.0
        return
    target = pp_for_overall(pp_overall(composites(npc.overall, npc.style), on), on)
    npc.pp = npc.pp + PP_SMOOTHING * (target - npc.pp) if smooth and npc.pp > 0 else target
    npc.rank = estimate_global_rank(npc.pp, on)
    if npc.rank and (npc.best_rank is None or npc.rank < npc.best_rank):
        npc.best_rank = npc.rank


# --- lightweight match strength ---------------------------------------------------------

# Which composites a pool slot leans on.
SLOT_WEIGHTS: dict[str, dict[str, float]] = {
    "NM1": {"aim": 0.7, "reading": 0.2, "mentality": 0.1},
    "NM2": {"aim": 0.45, "tapping": 0.45, "mentality": 0.1},
    "NM3": {"tapping": 0.6, "physical": 0.3, "mentality": 0.1},
    "NM4": {"technical": 0.6, "reading": 0.3, "mentality": 0.1},
    "NM5": {"reading": 0.7, "technical": 0.2, "mentality": 0.1},
    "HD": {"reading": 0.5, "aim": 0.4, "mentality": 0.1},
    "HR": {"technical": 0.4, "aim": 0.5, "mentality": 0.1},
    "DT": {"tapping": 0.5, "aim": 0.4, "mentality": 0.1},
    "TB": {"aim": 0.25, "tapping": 0.25, "physical": 0.2, "mentality": 0.3},
}


def slot_family(slot: str) -> str:
    return slot if slot.startswith("NM") else slot.rstrip("0123456789")


def slot_strength(comps: dict[str, float], slot: str) -> float:
    weights = SLOT_WEIGHTS[slot_family(slot)]
    return sum(comps[g] * w for g, w in weights.items())


def map_performance(comps: dict[str, float], slot: str, stars: float, form: float, rng: random.Random) -> float:
    """Relative performance on a map: handled stars / map stars, with form and noise."""
    handled = 2 * (0.6 + 0.04 * slot_strength(comps, slot))
    return handled / max(stars, 0.5) * math.exp(0.035 * form + rng.gauss(0, 0.06))
