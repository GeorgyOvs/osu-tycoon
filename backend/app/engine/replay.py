"""Compact replay data derived from what an attempt already computed (no extra randomness).

The play simulator records one row per hit object it reached (combo, hp, points, miss cause). This turns
them into ~40 columnar buckets plus a short list of moments, small enough to store with every match map.
"""

from dataclasses import dataclass, field

from app.engine.map_analysis import HitObject, MapProfile

BUCKETS = 40
MAX_MOMENTS = 14


@dataclass
class Trace:
    """One entry per object reached: combo after it, hp after it, points (0/50/100/300), miss cause or '',
    signed timing error in real ms (0 when the object was never timed: spinners, aim misses), and for sliders
    whose head was hit: 'b' broken on a tick or repeat, 'e' end dropped, '' otherwise."""

    combo: list[int] = field(default_factory=list)
    hp: list[float] = field(default_factory=list)
    points: list[int] = field(default_factory=list)
    cause: list[str] = field(default_factory=list)
    error: list[float] = field(default_factory=list)
    slider: list[str] = field(default_factory=list)

    def add(self, combo: int, hp: float, points: int, cause: str = "", error: float = 0.0, slider: str = "") -> None:
        self.combo.append(combo)
        self.hp.append(max(0.0, min(1.0, hp)))
        self.points.append(points)
        self.cause.append(cause)
        self.error.append(error)
        self.slider.append(slider)


def _kind(o: HitObject) -> str:
    if o.stream_bpm:
        return "stream"
    if o.velocity > 1.5:
        return "jump"
    if o.kind == "slider":
        return "slider"
    if o.complex_rhythm:
        return "rhythm"
    return "calm"


def _sections(objs: list[HitObject], first: float, played: int) -> list[dict]:
    """Candidate callouts: the longest streams, fastest jumps, odd rhythms."""
    out: list[dict] = []
    seen_stream = -1
    for i, o in enumerate(objs[:played]):
        t = (o.time - first) / 1000
        if o.stream_bpm and o.stream_len >= 12 and i > seen_stream:
            out.append({"t": t, "type": "stream", "weight": o.stream_len,
                        "text": f"{o.stream_bpm:.0f} BPM stream, {o.stream_len} notes"})
            seen_stream = i + o.stream_len
        elif o.velocity > 2.2 and not o.stream_bpm and (i == 0 or objs[i - 1].velocity <= 2.2):
            out.append({"t": t, "type": "jump", "weight": 6 + o.velocity, "text": "big jumps"})
        elif o.complex_rhythm and (i == 0 or not objs[i - 1].complex_rhythm) and o.speed_demand + o.aim_demand > 0:
            out.append({"t": t, "type": "rhythm", "weight": 4, "text": "tricky rhythm"})
    return out


def build(profile: MapProfile, trace: Trace, fail_index: int | None, choke_note) -> dict:
    objs = profile.objects
    n = len(objs)
    played = len(trace.combo)
    if n == 0 or played == 0:
        return {}
    first = objs[0].time
    last_t = (objs[min(played, n) - 1].time - first) / 1000
    duration = (objs[-1].time - first) / 1000
    scale = profile.max_combo / n

    max_aim = max((o.aim_demand for o in objs), default=0.0) or 1.0
    max_speed = max((o.speed_demand for o in objs), default=0.0) or 1.0
    cols: dict[str, list] = {k: [] for k in ("t", "combo", "hp", "misses", "acc", "strain", "kind")}
    misses = points = 0
    seen = 0
    strains = []
    groups: dict[int, list[int]] = {}
    for i in range(played):
        groups.setdefault(min(BUCKETS - 1, i * BUCKETS // n), []).append(i)
    for b in sorted(groups):
        idx = groups[b]
        for i in idx:
            misses += 1 if trace.cause[i] else 0
            points += trace.points[i]
        seen += len(idx)
        lo, hi = idx[0], idx[-1]
        strain = sum(max(objs[i].aim_demand / max_aim, objs[i].speed_demand / max_speed) for i in idx) / len(idx)
        strains.append(strain)
        kinds = [_kind(objs[i]) for i in idx]
        cols["t"].append(round((objs[lo].time - first) / 1000, 1))
        cols["combo"].append(round(trace.combo[hi] * scale))
        cols["hp"].append(round(min(trace.hp[i] for i in idx), 2))
        cols["misses"].append(misses)
        cols["acc"].append(round(100 * points / (300 * seen), 2))
        cols["strain"].append(round(strain, 3))
        cols["kind"].append(max(set(kinds), key=kinds.count))
    top = max(strains) or 1.0
    cols["strain"] = [round(s / top, 2) for s in cols["strain"]]

    moments: list[dict] = []
    # Miss streaks and notable single misses.
    run: list[int] = []
    miss_ids = [i for i in range(played) if trace.cause[i]]
    for i in miss_ids + [None]:
        if run and (i is None or i - run[-1] > 4):
            t = (objs[run[0]].time - first) / 1000
            if len(run) >= 3:
                moments.append({"t": t, "type": "miss_streak", "weight": 20 + len(run),
                                "text": f"{len(run)} misses in a row", "n": len(run)})
            run = []
        if i is not None:
            run.append(i)
    if len(miss_ids) <= 6:
        for i in miss_ids:
            moments.append({"t": (objs[i].time - first) / 1000, "type": "miss", "weight": 8,
                            "text": f"miss ({trace.cause[i]})", "cause": trace.cause[i]})
    if choke_note:
        combo, left, t = choke_note
        moments.append({"t": (t - first) / 1000, "type": "choke", "weight": 40,
                        "text": f"choke at {combo}x", "combo": combo, "left": left})
    # A hp scare that was survived.
    if played:
        low_i = min(range(played), key=lambda i: trace.hp[i])
        if trace.hp[low_i] < 0.2 and fail_index is None and low_i < played - 5:
            moments.append({"t": (objs[low_i].time - first) / 1000, "type": "hp_scare", "weight": 30,
                            "text": "almost failed"})
    if fail_index is not None:
        moments.append({"t": (objs[fail_index].time - first) / 1000, "type": "fail", "weight": 100,
                        "text": "fail"})
    elif misses == 0:
        moments.append({"t": duration, "type": "fc", "weight": 100, "text": "full combo"})
    moments += _sections(objs, first, played)

    moments.sort(key=lambda m: -m["weight"])
    keep = sorted(moments[:MAX_MOMENTS], key=lambda m: m["t"])
    for m in keep:
        m["t"] = round(m["t"], 1)
        m.pop("weight")
    return {"duration": round(duration, 1), "end": round(last_t, 1), "max_combo": profile.max_combo,
            "objects": n, **cols, "moments": keep}
