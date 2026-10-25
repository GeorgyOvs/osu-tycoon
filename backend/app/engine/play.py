"""Object-by-object simulation of a player attempting a map.

For every hit object the simulator finds the player's weakest relevant skill (aim, tapping
or reading) and turns demand / capability into a miss probability. Hits get a timing error
drawn from the player's accuracy against the OD windows. An HP bar decides fails (unless
NF), nerves can choke a long combo, and long maps drain endurance. A single bad section
can sink an otherwise easy map, which is exactly what happens to real players.
"""

import math
import random
from dataclasses import dataclass, field

from app.engine.map_analysis import HitObject, MapProfile
from app.engine.replay import Trace
from app.engine import replay as replay_mod

# Skill (1-115) -> the rosu difficulty value the player handles reliably.
CAP_BASE, CAP_PER_POINT = 0.6, 0.04
# Miss probability: logistic in demand/capability; ~1-2% at ratio 1.0, ~50% at MISS_CENTER.
MISS_CENTER, MISS_WIDTH, MISS_FLOOR = 1.3, 0.075, 0.0004
ATTEMPT_SIGMA = 0.06  # some attempts just go better than others
# Hit timing: normal error with sigma falling as accuracy skill rises, plus occasional
# lapses (heavy tail) so even easy maps aren't automatic SSes.
TIMING_SIGMA_BASE, TIMING_SIGMA_PER_POINT = 28.0, 0.16
LAPSE_P, LAPSE_SIGMA_MULT = 0.03, 3.0
PANIC_OBJECTS, PANIC_PENALTY = 3, 0.08  # after a miss the next notes are harder
CHOKE_BASE = 0.00003
JUMP_SPACING_PX = 110.0  # closer than this inside a stream = flow, not snap
TIMELINE_BUCKETS = 40


@dataclass
class DayModifiers:
    form: float = 0.0
    fatigue: float = 0.0
    motivation: float = 80.0
    warmup: float = 1.0  # < 1 for the first maps of a session
    session_hours: float = 0.0
    tilt: float = 0.0  # builds with fails and chokes during a session
    morale: float = 50.0  # tournament morale
    pressure: float = 1.0  # choke multiplier: match point / tiebreaker with weak nerves -> up to 3x
    clutch: float = 1.0  # capability multiplier under pressure (Match Clutchness)
    familiarity: float = 0.0  # 0..1 knowledge of this particular map
    block_bucket: int | None = None  # mindlock: slice of the timeline where the player tenses up
    block_severity: float = 0.0
    mastery: float = 0.0  # 0..1 hundreds of attempts: the map is learned by heart (slow to build, slow to fade)

    def capability(self, tilt_resilience: float) -> float:
        factor = math.exp(0.035 * self.form)
        factor *= 1 - self.fatigue / 500
        factor *= 1 - max(0.0, 40 - self.motivation) / 400
        factor *= self.warmup
        factor *= 1 - 0.015 * max(0.0, self.session_hours - 2)
        factor *= 1 - 0.015 * self.tilt * max(0.2, 1.3 - tilt_resilience / 100)
        factor *= 1 + (self.morale - 50) / 1000
        factor *= self.clutch
        factor *= 1 + 0.05 * self.familiarity + 0.10 * self.mastery
        return max(0.5, factor)


@dataclass
class TimelineBucket:
    misses: int = 0
    hp_min: float = 1.0
    reached: bool = False


@dataclass
class Attempt:
    passed: bool
    fail_progress: float | None  # 0..1 of the objects, when failed
    fail_time: float | None  # seconds into the map
    n300: int
    n100: int
    n50: int
    misses: int
    max_combo: int
    accuracy: float
    grade: str
    choked: bool
    miss_causes: dict[str, int]
    key_moments: list[str]
    timeline: list[TimelineBucket] = field(default_factory=list)
    peak_ratios: dict[str, float] = field(default_factory=dict)
    trace: Trace | None = None
    fail_index: int | None = None
    choke_note: tuple | None = None

    def replay(self, profile: MapProfile) -> dict:
        """Columnar replay data (built on demand from the recorded trace; no randomness)."""
        return replay_mod.build(profile, self.trace, self.fail_index, self.choke_note) if self.trace else {}


def capability(skill: float) -> float:
    return CAP_BASE + CAP_PER_POINT * skill


def _preempt(ar: float) -> float:
    return 1200 + 600 * (5 - ar) / 5 if ar < 5 else 1200 - 750 * (ar - 5) / 5


def _fmt_time(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def grade(n300: int, n100: int, n50: int, misses: int) -> str:
    total = n300 + n100 + n50 + misses
    if total == 0:
        return "D"
    r300, r50 = n300 / total, n50 / total
    if n300 == total:
        return "SS"
    if r300 > 0.9 and r50 <= 0.01 and misses == 0:
        return "S"
    if (r300 > 0.8 and misses == 0) or r300 > 0.9:
        return "A"
    if (r300 > 0.7 and misses == 0) or r300 > 0.8:
        return "B"
    if r300 > 0.6:
        return "C"
    return "D"


class _Ratios:
    """Precomputed per-object demand/capability ratios (before day modifiers and noise)."""

    def __init__(self, profile: MapProfile, s: dict[str, float], mods: str):
        self.p = profile
        self.s = s
        self.hidden = "HD" in mods or "FL" in mods
        self.cs_weight = max(0.0, min(0.6, (profile.cs - 4) / 2.5))
        self.sv_weight = min(0.5, profile.sv_variability)
        self.endurance_s = 90 + 3.5 * (s["visual_endurance"] + s["hand_stamina"]) / 2
        self.acc_skill = 0.5 * s["strict_od"] + 0.3 * s["low_mid_bpm"] + 0.2 * s["rhythm_reading"]
        self.visible = self._visible_counts()

    def _visible_counts(self) -> list[int]:
        """Objects on screen at each object's hit time (low AR overlap reading)."""
        objs, preempt = self.p.objects, _preempt(self.p.ar)
        counts, j = [], 0
        for i, o in enumerate(objs):
            j = max(j, i)
            while j + 1 < len(objs) and objs[j + 1].time - o.time < preempt:
                j += 1
            counts.append(j - i + 1)
        return counts

    def aim_skill(self, o: HitObject, prev: HitObject | None) -> float:
        s = self.s
        spacing = math.dist((o.x, o.y), (prev.x, prev.y)) if prev else 0.0
        if o.kind == "slider":
            skill = (1 - self.sv_weight) * s["flow_aim"] + self.sv_weight * s["slider_velocity"]
        elif o.stream_bpm and spacing <= JUMP_SPACING_PX:
            skill = s["flow_aim"]
        else:
            skill = s["snap_aim"]
            if o.velocity > 1.5:
                w = min(0.6, (o.velocity - 1.5) / 1.5)
                skill = (1 - w) * skill + w * s["distance"]
            if o.sharp_angle:
                skill = 0.7 * skill + 0.3 * s["awkward_angles"]
        return (1 - self.cs_weight) * skill + self.cs_weight * s["precision"]

    def tapping(self, o: HitObject) -> tuple[float, float, float]:
        """(section speed ratio, stream bpm ratio, tapping skill) before modifiers."""
        s = self.s
        if o.stream_bpm:
            length = o.stream_len
            w = max(0.0, min(1.0, (length - 8) / 24))
            burst = 0.75 * s["burst"] + 0.25 * s["finger_independence"] if length <= 8 else s["burst"]
            skill = (1 - w) * burst + w * s["deathstream"]
            cap_bpm = (1 - w) * (140 + 1.7 * burst) + w * (130 + 1.45 * s["deathstream"])
            cap_bpm = max(cap_bpm, 120 + 1.2 * s["low_mid_bpm"]) if o.stream_bpm < 190 else cap_bpm
            bpm_ratio = o.stream_bpm / cap_bpm
        else:
            skill = 0.6 * s["low_mid_bpm"] + 0.4 * s["burst"]
            bpm_ratio = 0.0
        return o.speed_demand / capability(skill), bpm_ratio, skill

    def reading(self, i: int, o: HitObject) -> float:
        s, p = self.s, self.p
        intensity = 0.6 + 0.4 * (o.aim_demand / p.aim if p.aim else 0)
        ratios = [0.0]
        if p.ar > 9:
            ratios.append((p.ar - 9) * 40 * intensity / s["high_ar_reaction"])
        if p.ar < 8.5:
            crowd = max(0, self.visible[i] - 4) * 4 * (8.5 - p.ar) / 2.5
            ratios.append(crowd / s["low_ar_reading"])
        if self.hidden:
            ratios.append(16 * max(o.aim_demand, o.speed_demand) * (1.15 if p.ar < 9 else 1) / s["hidden"])
        if o.complex_rhythm:
            ratios.append(14 * max(o.aim_demand, o.speed_demand) / s["rhythm_reading"])
        return max(ratios)


def simulate(
    profile: MapProfile,
    skills: dict[str, float],
    mods: str,
    day: DayModifiers,
    rng: random.Random,
) -> Attempt:
    objs = profile.objects
    n = len(objs)
    ratios = _Ratios(profile, skills, mods)
    factor = day.capability(skills["tilt_resilience"])
    nerve = skills["nerve_resistance"]
    no_fail = "NF" in mods

    attempt_quality = rng.gauss(0, ATTEMPT_SIGMA)
    lapse_sigma = (0.025 + 0.03 * (1 - min(nerve, 100) / 100)) * (1 - min(0.6, 0.3 * day.familiarity + 0.25 * day.mastery))
    section_noise: dict[int, float] = {}

    hp = 1.0
    hp_drain = 0.0022 * profile.hp
    heal_300 = 0.03 * max(0.2, 1 - profile.hp / 14)
    heal_100 = 0.012 * max(0.2, 1 - profile.hp / 14)
    miss_damage = 0.04 + 0.014 * profile.hp

    n300 = n100 = n50 = misses = 0
    combo = best_run = 0
    panic = 0
    choked = False
    choke_note = None
    causes: dict[str, int] = {}
    peaks = {"aim": 0.0, "tapping": 0.0, "reading": 0.0, "stamina": 0.0}
    timeline = [TimelineBucket() for _ in range(TIMELINE_BUCKETS)]
    fail_index = None
    trace = Trace()
    first_time = objs[0].time if objs else 0.0
    recent_causes: list[tuple[str, HitObject]] = []

    for i, o in enumerate(objs):
        bucket = timeline[min(TIMELINE_BUCKETS - 1, i * TIMELINE_BUCKETS // max(n, 1))]
        bucket.reached = True
        prev = objs[i - 1] if i else None

        if prev is not None:
            gap = (o.time - prev.time) / 1000
            hp -= hp_drain * min(gap, 1.0 if gap > 3 else gap)  # breaks don't drain

        if o.kind == "spinner":
            n300 += 1
            combo += 1
            best_run = max(best_run, combo)
            hp = min(1.0, hp + heal_300)
            trace.add(combo, hp, 300)
            continue

        # Demand / capability per dimension, with today's form and the attempt's noise.
        sec = int(o.time // 2000)
        if sec not in section_noise:
            section_noise[sec] = rng.gauss(0, lapse_sigma)
        noise = math.exp(attempt_quality + section_noise[sec])
        r_aim = o.aim_demand / (capability(ratios.aim_skill(o, prev)) * factor)
        r_speed, r_bpm, _ = ratios.tapping(o)
        r_tap = max(r_speed, r_bpm) / factor
        r_read = ratios.reading(i, o) / factor / (1 + 0.15 * day.familiarity + 0.10 * day.mastery)  # known patterns read easier
        elapsed = (o.time - first_time) / 1000
        stamina = 1 + 0.0015 * max(0.0, elapsed - ratios.endurance_s)

        dims = {"aim": r_aim * stamina, "tapping": r_tap * stamina, "reading": r_read}
        cause = max(dims, key=dims.get)
        r = dims[cause] + 0.15 * sum(max(0.0, v - 0.85) for k, v in dims.items() if k != cause)
        r *= noise
        if day.block_bucket is not None and abs(min(TIMELINE_BUCKETS - 1, i * TIMELINE_BUCKETS // max(n, 1)) - day.block_bucket) <= 1:
            r *= 1 + 0.35 * day.block_severity  # the hands shake where the head is stuck
        if stamina > 1.05 and dims[cause] / stamina < 1.0 <= dims[cause]:
            cause = "stamina"
        for k, v in dims.items():
            peaks[k] = max(peaks[k], v)
        peaks["stamina"] = max(peaks["stamina"], stamina)
        if panic:
            r += PANIC_PENALTY
            panic -= 1

        p_miss = MISS_FLOOR + 1 / (1 + math.exp(-(r - MISS_CENTER) / MISS_WIDTH))
        missed = rng.random() < p_miss
        points = 0

        if not missed and combo > 100:
            # Nerves: the longer the combo and the closer the end, the shakier the hands.
            pressure = (combo / 500) ** 1.2 * (1.5 - min(nerve, 100) / 100)
            if n - i < 100 and combo > 300:
                pressure *= 2
            if rng.random() < CHOKE_BASE * pressure * day.pressure:
                missed, cause = True, "nerves"
                if not choked:
                    choked, choke_note = True, (combo, n - i, o.time)

        if not missed:
            # Timing: |error| against the OD windows; slider heads only need the 50 window.
            sigma = (TIMING_SIGMA_BASE - TIMING_SIGMA_PER_POINT * ratios.acc_skill) * (0.7 + 0.4 * min(r, 1.5)) / factor
            if rng.random() < LAPSE_P * (1 - min(ratios.acc_skill, 115) / 150):
                sigma *= LAPSE_SIGMA_MULT
            err = abs(rng.gauss(0, max(4.0, sigma)))
            if o.kind == "slider":
                result = 300 if err <= profile.meh_window else 0
            elif err <= profile.great_window:
                result = 300
            elif err <= profile.ok_window:
                result = 100
            elif err <= profile.meh_window:
                result = 50
            else:
                result = 0
                cause = "accuracy"
            missed = result == 0

        if missed:
            misses += 1
            combo = 0
            panic = PANIC_OBJECTS
            hp -= miss_damage
            causes[cause] = causes.get(cause, 0) + 1
            bucket.misses += 1
            recent_causes.append((cause, o))
            recent_causes = recent_causes[-20:]
        else:
            combo += 1
            best_run = max(best_run, combo)
            points = result
            if result == 300:
                n300 += 1
                hp += heal_300
            elif result == 100:
                n100 += 1
                hp += heal_100
            else:
                n50 += 1
            hp = min(1.0, hp)

        bucket.hp_min = min(bucket.hp_min, max(0.0, hp))
        trace.add(combo, hp, points, cause if missed else "")
        if hp <= 0:
            if no_fail:
                hp = 0.0
            else:
                fail_index = i
                break

    passed = fail_index is None
    if not passed:
        # Everything after the fail point counts as unplayed misses for bookkeeping.
        misses += n - (n300 + n100 + n50 + misses)

    total = max(1, n)
    accuracy = 100 * (300 * n300 + 100 * n100 + 50 * n50) / (300 * total)
    combo_scale = profile.max_combo / total
    max_combo = min(profile.max_combo, round(best_run * combo_scale))
    if passed and misses == 0:
        max_combo = profile.max_combo

    moments = _key_moments(profile, passed, fail_index, choke_note, causes, recent_causes, misses, n300, total)
    return Attempt(
        passed=passed,
        fail_progress=None if passed else fail_index / total,
        fail_time=None if passed else (objs[fail_index].time - first_time) / 1000,
        n300=n300,
        n100=n100,
        n50=n50,
        misses=misses,
        max_combo=max_combo,
        accuracy=accuracy,
        grade=grade(n300, n100, n50, misses) if passed else "F",
        choked=choked,
        miss_causes=causes,
        key_moments=moments,
        timeline=timeline,
        peak_ratios=peaks,
        trace=trace,
        fail_index=fail_index,
        choke_note=choke_note,
    )


CAUSE_TEXT = {
    "aim": "jumps they couldn't hit",
    "tapping": "tapping they couldn't keep up with",
    "reading": "patterns they couldn't read",
    "stamina": "running out of stamina",
    "nerves": "nerves",
    "accuracy": "sloppy timing",
}


def _key_moments(profile, passed, fail_index, choke_note, causes, recent, misses, n300, total) -> list[str]:
    out = []
    objs = profile.objects
    first = objs[0].time if objs else 0.0
    if not passed and fail_index is not None:
        o = objs[fail_index]
        when = f"{_fmt_time((o.time - first) / 1000)} ({100 * fail_index / total:.0f}%)"
        last = [c for c, _ in recent[-8:]]
        main = max(set(last), key=last.count) if last else "aim"
        context = {
            "tapping": "",
            "aim": " in a jump section",
            "reading": f" at AR{profile.ar:.1f}" + (" with Hidden" if "reading" in last else ""),
            "stamina": ": the hands gave out",
            "nerves": " after losing composure",
            "accuracy": ": timing fell apart",
        }.get(main, "")
        if main == "tapping":
            stream = next((ob for c, ob in reversed(recent) if c == "tapping" and ob.stream_bpm), None)
            context = (
                f" during a {stream.stream_bpm:.0f} BPM stream ({stream.stream_len} notes)"
                if stream
                else " in a fast tapping section"
            )
        out.append(f"Failed at {when}{context}.")
    if choke_note:
        combo, left, t = choke_note
        out.append(f"Choked at {combo}x with {left} notes left ({_fmt_time((t - first) / 1000)}).")
    if passed and misses == 0:
        out.append("SS!" if n300 == total else "Full combo!")
    if misses >= 3 and causes:
        top = max(causes, key=causes.get)
        if causes[top] / sum(causes.values()) >= 0.5:
            out.append(f"{causes[top]} of {sum(causes.values())} misses came from {CAUSE_TEXT[top]}.")
    return out


MOD_SCORE_MULTIPLIERS = {"HD": 1.06, "HR": 1.10, "DT": 1.20, "NC": 1.20, "FL": 1.12, "EZ": 0.5, "HT": 0.3}


def score_v2(attempt: Attempt, profile: MapProfile, mods: str) -> int:
    """Tournament score (ScoreV2-like): 70% combo, 30% accuracy^10, times mod multipliers."""
    combo = (attempt.max_combo / max(1, profile.max_combo)) ** 1.5
    acc = (attempt.accuracy / 100) ** 10
    mult = 1.0
    for i in range(0, len(mods), 2):
        mult *= MOD_SCORE_MULTIPLIERS.get(mods[i : i + 2], 1.0)
    return round(1_000_000 * (0.7 * combo + 0.3 * acc) * mult)


def match_pressure(nerve: float, clutch: float, decisive: bool) -> tuple[float, float]:
    """(choke multiplier, capability multiplier) for a tournament map."""
    if not decisive:
        return 1.0, 1.0
    return 1 + 2 * max(0.0, 1 - nerve / 100), 0.97 + 0.06 * min(clutch, 100) / 100


@dataclass
class Assessment:
    pass_rate: float
    fc_rate: float
    median_accuracy: float | None  # over passes
    median_misses: float | None
    peak_ratios: dict[str, float]  # 1.0 = at the limit of what the player handles reliably
    weakest: str


def assess(profile: MapProfile, skills: dict[str, float], mods: str, day: DayModifiers, seed: str, runs: int = 24) -> Assessment:
    """Monte Carlo preview: how would today's version of the player fare on this map?"""
    attempts = [simulate(profile, skills, mods, day, random.Random(f"{seed}:{k}")) for k in range(runs)]
    passes = [a for a in attempts if a.passed]
    peaks = {k: max(a.peak_ratios[k] for a in attempts) for k in ("aim", "tapping", "reading")}
    peaks["stamina"] = max(a.peak_ratios["stamina"] for a in attempts)

    def median(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else None

    return Assessment(
        pass_rate=len(passes) / runs,
        fc_rate=sum(1 for a in passes if a.misses == 0) / runs,
        median_accuracy=median([a.accuracy for a in passes]),
        median_misses=median([a.misses for a in passes]),
        peak_ratios=peaks,
        weakest=max(("aim", "tapping", "reading"), key=lambda k: peaks[k]),
    )


def training_targets(profile: MapProfile, mods: str, played: int) -> dict[str, float]:
    """Which sub-stats a play exercised, from the first `played` objects. Max share = 1."""
    w: dict[str, float] = {}

    def add(key: str, amount: float) -> None:
        w[key] = w.get(key, 0.0) + amount

    objs = profile.objects[:played]
    for i, o in enumerate(objs):
        if o.kind == "spinner":
            continue
        aim = o.aim_demand
        if o.kind == "slider":
            add("flow_aim", aim * 0.7)
            add("slider_velocity", aim * 0.3 * (0.3 + profile.sv_variability))
        elif o.stream_bpm and i and math.dist((o.x, o.y), (objs[i - 1].x, objs[i - 1].y)) <= JUMP_SPACING_PX:
            add("flow_aim", aim * 0.6)
        else:
            add("snap_aim", aim)
            if o.velocity > 1.5:
                add("distance", aim * min(1.0, (o.velocity - 1.5) / 1.5))
            if o.sharp_angle:
                add("awkward_angles", aim * 0.5)
        if o.stream_bpm:
            if o.stream_len <= 12:
                add("burst", o.speed_demand)
                add("finger_independence", o.speed_demand * 0.3)
            else:
                add("deathstream", o.speed_demand * min(1.0, o.stream_len / 32))
            if o.stream_bpm < 190:
                add("low_mid_bpm", o.speed_demand * 0.5)
        else:
            add("low_mid_bpm", o.speed_demand * 0.6)
        if o.complex_rhythm:
            add("rhythm_reading", max(aim, o.speed_demand))
        intensity = max(aim, o.speed_demand)
        if profile.ar > 9.3:
            add("high_ar_reaction", intensity * (profile.ar - 9.3))
        if profile.ar < 8:
            add("low_ar_reading", intensity * (8 - profile.ar) / 2)
        if "HD" in mods:
            add("hidden", intensity)
        if profile.od >= 8.5:
            add("strict_od", intensity * (profile.od - 8) / 2)
        if profile.cs >= 4.5:
            add("precision", aim * (profile.cs - 4))
    if objs:
        intensity = sum(max(o.aim_demand, o.speed_demand) for o in objs) / len(objs)
        add("nerve_resistance", intensity * len(objs) * min(1.0, profile.max_combo / 1500) * 0.15)
    top = max(w.values(), default=0.0)
    return {k: round(v / top, 3) for k, v in w.items() if top and v / top >= 0.05}
