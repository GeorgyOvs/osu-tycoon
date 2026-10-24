"""Turn a .osu file + mods into per-object skill demands for the play simulator.

Absolute difficulty comes from rosu-pp (aim/speed difficulty, hit windows, AR/CS/HP after
mods); its 400ms strain sections give the shape over time. On top of that the raw hit
objects are parsed for things rosu doesn't expose directly: stream BPM and length, jump
velocity and angles, slider velocity changes and irregular rhythm snaps.
"""

import math
from dataclasses import dataclass, field

import rosu_pp_py as rosu

from app.config import PP_LAZER

STREAM_MAX_GAP_MS = 100.0  # real time; 1/4 notes at >= 150 BPM
STREAM_GAP_TOLERANCE = 0.2  # consecutive gaps within 20% count as one stream
MIN_STREAM_NOTES = 3
DEMAND_REF_SHARE = 0.1  # strain peaks (top 10% of sections) correspond to the map's difficulty values
COMMON_SNAPS = (1.0, 0.5, 0.25, 0.125, 0.75, 1.5, 2.0, 0.375)


@dataclass
class HitObject:
    time: float  # real ms (clock rate applied)
    kind: str  # circle | slider | spinner
    x: float
    y: float
    aim_demand: float = 0.0  # in rosu aim-difficulty units
    speed_demand: float = 0.0  # in rosu speed-difficulty units
    stream_bpm: float | None = None
    stream_len: int = 0
    velocity: float = 0.0  # px per real ms from the previous object
    sharp_angle: bool = False
    complex_rhythm: bool = False


@dataclass
class MapProfile:
    stars: float
    aim: float
    speed: float
    ar: float
    od: float
    cs: float
    hp: float
    bpm: float
    clock_rate: float
    great_window: float  # +- ms, real time
    ok_window: float
    meh_window: float
    max_combo: int
    drain_seconds: float
    sv_variability: float  # 0 = constant slider velocity, ~1 = wild SV changes
    objects: list[HitObject] = field(default_factory=list)

    @property
    def longest_stream(self) -> int:
        return max((o.stream_len for o in self.objects), default=0)

    @property
    def fastest_stream_bpm(self) -> float:
        return max((o.stream_bpm or 0.0 for o in self.objects), default=0.0)


def _sections(content: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current = ""
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            out.setdefault(current, [])
        elif current:
            out[current].append(line)
    return out


def _parse_timing(lines: list[str]) -> tuple[list[tuple[float, float]], list[float]]:
    """(red line time, beat length) pairs and the list of SV multipliers from green lines."""
    red, sv = [], []
    for line in lines:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            t, beat = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        uninherited = parts[6].strip() == "1" if len(parts) > 6 else beat > 0
        if uninherited and beat > 0:
            red.append((t, beat))
        elif beat < 0:
            sv.append(-100.0 / beat)
    return red, sv


def _beat_at(red: list[tuple[float, float]], t: float) -> float:
    beat = red[0][1] if red else 500.0
    for start, length in red:
        if start > t:
            break
        beat = length
    return beat


def _parse_objects(lines: list[str]) -> list[tuple[float, str, float, float]]:
    objs = []
    for line in lines:
        parts = line.split(",")
        if len(parts) < 4:
            continue
        try:
            x, y, t, typ = float(parts[0]), float(parts[1]), float(parts[2]), int(parts[3])
        except ValueError:
            continue
        kind = "spinner" if typ & 8 else "slider" if typ & 2 else "circle"
        objs.append((t, kind, x, y))
    objs.sort(key=lambda o: o[0])
    return objs


def _normalized(strains: list[float], difficulty: float) -> list[float]:
    """Scale strains so the peak sections equal the map's difficulty value."""
    if not strains:
        return []
    top = sorted(strains, reverse=True)[: max(1, int(len(strains) * DEMAND_REF_SHARE))]
    ref = sum(top) / len(top)
    return [difficulty * s / ref if ref > 0 else 0.0 for s in strains]


def analyze(osu_file: bytes, mods: str = "") -> MapProfile:
    content = osu_file.decode("utf-8", errors="replace")
    beatmap = rosu.Beatmap(bytes=osu_file)
    diff_calc = rosu.Difficulty(mods=mods, lazer=PP_LAZER)
    attrs = diff_calc.calculate(beatmap)
    strains = diff_calc.strains(beatmap)
    map_attrs = rosu.BeatmapAttributesBuilder(map=beatmap, mods=mods).build()
    clock = map_attrs.clock_rate

    sections = _sections(content)
    red, sv = _parse_timing(sections.get("TimingPoints", []))
    raw_objects = _parse_objects(sections.get("HitObjects", []))

    aim_curve = _normalized(strains.aim or [], attrs.aim or 0.0)
    speed_curve = _normalized(strains.speed or [], attrs.speed or 0.0)
    section_len = strains.section_length

    objects: list[HitObject] = []
    first_section = math.floor(raw_objects[0][0] / clock / section_len) if raw_objects else 0
    for i, (t_map, kind, x, y) in enumerate(raw_objects):
        t = t_map / clock
        idx = math.floor(t / section_len) - first_section
        obj = HitObject(time=t, kind=kind, x=x, y=y)
        if aim_curve:
            obj.aim_demand = aim_curve[max(0, min(idx, len(aim_curve) - 1))]
        if speed_curve:
            obj.speed_demand = speed_curve[max(0, min(idx, len(speed_curve) - 1))]
        if i > 0 and kind != "spinner":
            prev = objects[-1]
            gap = max(1.0, t - prev.time)
            obj.velocity = math.dist((x, y), (prev.x, prev.y)) / gap
            snap = (t_map - raw_objects[i - 1][0]) / _beat_at(red, t_map)
            obj.complex_rhythm = snap < 2.5 and not any(abs(snap - s) < 0.04 for s in COMMON_SNAPS)
            if i > 1:
                pp = objects[-2]
                a = (prev.x - pp.x, prev.y - pp.y)
                b = (x - prev.x, y - prev.y)
                na, nb = math.hypot(*a), math.hypot(*b)
                if na > 60 and nb > 60:  # only real jumps have meaningful angles
                    cos = (a[0] * b[0] + a[1] * b[1]) / (na * nb)
                    obj.sharp_angle = cos < -0.5  # turn back by more than 120 degrees
        objects.append(obj)

    _mark_streams(objects)

    if objects:
        drain = (objects[-1].time - objects[0].time) / 1000
    else:
        drain = 0.0
    sv_var = 0.0
    if len(sv) > 4:
        mean = sum(sv) / len(sv)
        sv_var = min(1.0, (sum((v - mean) ** 2 for v in sv) / len(sv)) ** 0.5 / max(mean, 0.1) + len(set(round(v, 2) for v in sv)) / 200)

    return MapProfile(
        stars=attrs.stars,
        aim=attrs.aim or 0.0,
        speed=attrs.speed or 0.0,
        ar=map_attrs.ar,
        od=map_attrs.od,
        cs=map_attrs.cs,
        hp=map_attrs.hp,
        bpm=beatmap.bpm * clock,
        clock_rate=clock,
        great_window=attrs.great_hit_window or 50.0,
        ok_window=attrs.ok_hit_window or 100.0,
        meh_window=attrs.meh_hit_window or 150.0,
        max_combo=attrs.max_combo,
        drain_seconds=drain,
        sv_variability=sv_var,
        objects=objects,
    )


def _mark_streams(objects: list[HitObject]) -> None:
    """Find runs of evenly spaced fast notes and tag every note with the run's BPM and length."""
    i = 0
    n = len(objects)
    while i < n - 1:
        gap = objects[i + 1].time - objects[i].time
        if objects[i].kind == "spinner" or gap > STREAM_MAX_GAP_MS or gap <= 0:
            i += 1
            continue
        j = i + 1
        while j < n - 1:
            next_gap = objects[j + 1].time - objects[j].time
            if objects[j + 1].kind == "spinner" or abs(next_gap - gap) > gap * STREAM_GAP_TOLERANCE:
                break
            j += 1
        length = j - i + 1
        if length >= MIN_STREAM_NOTES:
            bpm = 15000.0 / gap  # notes are 1/4 beats
            for k in range(i, j + 1):
                objects[k].stream_bpm = bpm
                objects[k].stream_len = length
        i = j
