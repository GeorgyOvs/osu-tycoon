"""Deterministic casting for replays and matches: two casters, templated lines, timestamps.

Commentary is derived from stored results (replay columns, scores), so nothing here is persisted
and the same match always gets the same broadcast. Text is English; the UI translates common lines.
"""

import random
from datetime import date

# (first year, caster handles): era-flavoured but fictional.
CASTER_POOLS = [
    (2007, ["Mikazuki", "Rhythmic", "Daisuke_", "pippi", "Cherry"]),
    (2012, ["Nightfall", "Kirin", "Ostrich", "Lumi", "Arrowhead"]),
    (2017, ["Quasar", "Hikari", "Verdict", "Palette", "Ryo"]),
    (2022, ["Stardust", "Meridian", "Koto", "Fenwick", "Aria"]),
]

MISS_CAUSE_TEXT = {
    "aim": "couldn't reach that jump",
    "tapping": "the tapping got away from them",
    "reading": "lost the pattern",
    "stamina": "the hands are running out of gas",
    "nerves": "the nerves got to them",
    "accuracy": "timing slipped",
}


def casters(on: date, rng: random.Random) -> tuple[str, str]:
    pool = [names for year, names in CASTER_POOLS if on.year >= year][-1]
    a, b = rng.sample(pool, 2)
    return a, b


def _mods(mods: str) -> str:
    return "" if not mods or mods == "NM" else f" +{mods}"


class _Booth:
    """Alternates casters and builds lines."""

    def __init__(self, names: tuple[str, str], rng: random.Random):
        self.names, self.rng, self.i = names, rng, 0
        self.lines: list[dict] = []

    def say(self, t: float, text: str, tone: str = "neutral", who: int | None = None) -> None:
        idx = who if who is not None else self.i % 2
        self.i += 1
        self.lines.append({"t": round(t, 1), "text": text, "tone": tone, "who": self.names[idx]})

    def pick(self, options: list[str]) -> str:
        return self.rng.choice(options)


def play_lines(replay: dict, ctx: dict, on: date, seed: str) -> list[dict]:
    """Lines for one play. ctx: player, title, mods, stars, passed, accuracy, misses, grade, combo,
    max_combo, choked, ranked (bool, session plays say 'attempt' rather than 'match')."""
    rng = random.Random(f"{seed}:cast")
    booth = _Booth(casters(on, rng), rng)
    player, title = ctx["player"], ctx.get("title", "this map")
    stars = ctx.get("stars")
    star_text = f", {stars:.1f}★" if stars else ""
    booth.say(0.0, booth.pick([
        f"{player} on {title}{_mods(ctx.get('mods', ''))}{star_text}. Here we go.",
        f"Next up, {player} with {title}{_mods(ctx.get('mods', ''))}{star_text}.",
        f"{player} takes on {title}{_mods(ctx.get('mods', ''))}{star_text}; let's see how this goes.",
    ]), "neutral")
    duration = replay.get("duration", 0.0) if replay else 0.0
    if not replay:
        booth.say(duration, _result_line(booth, ctx), _result_tone(ctx))
        return booth.lines

    last = -99.0
    for m in replay.get("moments", []):
        t, kind = m["t"], m["type"]
        if t - last < 3.0 and kind not in ("fail", "fc", "choke"):
            continue
        last = t
        if kind == "stream":
            booth.say(t, booth.pick([f"Here comes the {m['text']}.", f"{m['text'].capitalize()} coming up, this is the test.",
                                     f"Stream time: {m['text']}."]), "tense")
        elif kind == "jump":
            booth.say(t, booth.pick(["Big jumps now, they need to stay accurate.", "The spacing opens up here.",
                                     "Jump section, no room for mistakes."]), "tense")
        elif kind == "rhythm":
            booth.say(t, booth.pick(["Tricky rhythm incoming.", "This part is all about reading the timing."]), "tense")
        elif kind == "miss_streak":
            booth.say(t, booth.pick([f"{m.get('n', 3)} misses in a row, the combo is gone.",
                                     "That section just fell apart.", "Ouch, they lost control there."]), "sad")
        elif kind == "miss":
            booth.say(t, booth.pick(["A miss. Small mistake, but it counts.", "Dropped the combo there.",
                                     f"Miss: {MISS_CAUSE_TEXT.get(m.get('cause', ''), 'unlucky')}."]), "sad")
        elif kind == "choke":
            booth.say(t, booth.pick([f"No! They choke at {m.get('combo', 0)}x!", f"The {m.get('combo', 0)}x combo breaks. Brutal.",
                                     "Nerves! That's a heartbreaker."]), "sad")
        elif kind == "hp_scare":
            booth.say(t, booth.pick(["The health bar is almost empty!", "They are barely alive here, wow."]), "tense")
        elif kind == "fail":
            booth.say(t, booth.pick(["And that's the fail. The health bar is gone.", "They can't hold on, it's a fail.",
                                     "The map ends here for them."]), "sad")
        elif kind == "fc":
            booth.say(t, booth.pick(["Full combo! Clean.", "No misses the whole way, what a run!", "FC secured."]), "hype")
    booth.say(max(duration, replay.get("end", duration)) + 0.5, _result_line(booth, ctx), _result_tone(ctx))
    return booth.lines


def _result_tone(ctx: dict) -> str:
    if not ctx["passed"]:
        return "sad"
    return "hype" if ctx["misses"] == 0 else "neutral"


def _result_line(booth: _Booth, ctx: dict) -> str:
    if not ctx["passed"]:
        return booth.pick([f"{ctx['player']} fails the map.", "Not this time. Back to the drawing board."])
    acc = f"{ctx['accuracy']:.2f}%"
    if ctx["misses"] == 0:
        return booth.pick([f"{ctx['player']} finishes with a full combo at {acc}.", f"Clean run: {acc}, grade {ctx['grade']}."])
    return booth.pick([f"{ctx['player']} clears it with {ctx['misses']} misses at {acc}.",
                       f"{acc}, {ctx['misses']}x miss, grade {ctx['grade']}."])


def _focus(map_detail: dict, user_side: str | None) -> dict | None:
    players = map_detail.get("players", [])
    if not players:
        return None
    for p in players:
        if p.get("kind") == "user":
            return p
    side = user_side or "a"
    return next((p for p in players if p["side"] == side), players[0])


def match_commentary(maps: list[dict], *, on: date, seed: str, name_a: str, name_b: str, user_side: str | None,
                     first_to: int, stage: str, winner: str | None) -> dict:
    """Broadcast for a whole match: {pre, maps: [[lines]], between: [[lines]], post}."""
    rng = random.Random(f"{seed}:match")
    booth = _Booth(casters(on, rng), rng)
    played = [m for m in maps if "slot" in m]
    bans = next((m["bans"] for m in maps if "bans" in m), {"a": [], "b": []})

    pre = []
    booth.say(0, booth.pick([f"Welcome to the {stage}! {name_a} against {name_b}, first to {first_to}.",
                             f"{name_a} vs {name_b} in the {stage}. First to {first_to} takes it."]), "neutral")
    ban_text = ", ".join(f"{n} bans {', '.join(bans.get(s, [])) or 'nothing'}" for n, s in ((name_a, "a"), (name_b, "b")))
    booth.say(1, f"Bans: {ban_text}.", "neutral")
    pre, booth.lines = booth.lines, []

    per_map, between = [], []
    sa = sb = 0
    for i, m in enumerate(played):
        focus = _focus(m, user_side)
        replay = (focus or {}).get("replay") or {}
        picked = {"a": name_a, "b": name_b}.get(m.get("picked_by", ""), None)
        booth.lines = []
        if focus:
            ctx = {"player": focus["name"], "title": m.get("title") or m["slot"], "mods": m.get("mods", ""),
                   "stars": m.get("stars"), "passed": focus.get("passed", True), "accuracy": focus.get("accuracy", 0),
                   "misses": focus.get("misses", 0), "grade": focus.get("grade", ""), "choked": focus.get("choked", False)}
            lines = play_lines(replay, ctx, on, f"{seed}:{i}")
            if m.get("picked_by") == "tb":
                lines.insert(0, {"t": 0.0, "text": "Tiebreaker! Everything comes down to this map.", "tone": "tense",
                                 "who": booth.names[0]})
            elif picked:
                lines.insert(0, {"t": 0.0, "text": f"{picked} picks {m['slot']}.", "tone": "neutral", "who": booth.names[1]})
            per_map.append(lines)
        else:
            per_map.append([])
        lead_before = (sa > sb) - (sa < sb)
        if m.get("winner", "a" if m["score_a"] > m["score_b"] else "b") == "a":
            sa += 1
            w = name_a
        else:
            sb += 1
            w = name_b
        booth.lines = []
        diff = abs(m["score_a"] - m["score_b"]) / max(1, max(m["score_a"], m["score_b"]))
        booth.say(0, booth.pick([f"{w} takes {m['slot']}, {m['score_a']:,} to {m['score_b']:,}.",
                                 f"{m['slot']} goes to {w}."]) + (" What a close one!" if diff < 0.03 else ""),
                  "hype" if diff < 0.03 else "neutral")
        booth.say(1, f"Score: {name_a} {sa} - {sb} {name_b}.", "neutral")
        if sa == first_to - 1 and sb == first_to - 1:
            booth.say(2, "Both players are on match point. Tiebreaker incoming!", "tense")
        elif sa == first_to - 1 or sb == first_to - 1:
            leader = name_a if sa > sb else name_b
            booth.say(2, f"{leader} is on match point.", "tense")
        lead_after = (sa > sb) - (sa < sb)
        if lead_before and lead_after and lead_before != lead_after:
            booth.say(3, "And just like that the lead changes hands.", "hype")
        between.append(booth.lines)

    booth.lines = []
    if winner:
        w = name_a if winner == "a" else name_b
        l = name_b if winner == "a" else name_a
        booth.say(0, booth.pick([f"{w} wins {sa}-{sb}! GG to both.", f"It's over! {w} advances, {l} will be back."]), "hype")
        if user_side and winner != user_side:
            booth.say(1, "Tough loss for the home side, but plenty to learn from.", "sad")
    return {"pre": pre, "maps": per_map, "between": between, "post": booth.lines}
