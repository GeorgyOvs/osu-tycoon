import random
import statistics

from app.engine import attributes as A
from app.engine import play, playstyle
from app.engine.map_analysis import analyze
from tests.conftest import make_osu_file


def skills(**groups: float) -> dict[str, float]:
    out = {k: 60.0 for k in A.SUBSTATS}
    for g in A.GROUPS:
        for sub in g.subs:
            out[sub.key] = groups.get(g.key, 60.0)
    return out


def test_a_player_always_plays_the_same_way():
    s = skills()
    assert playstyle.describe(7, s) == playstyle.describe(7, s)
    assert playstyle.describe(7, s) != playstyle.describe(8, s)
    # Knowing the device doesn't reshuffle the rest of the hand.
    mouse, tablet = playstyle.describe(7, s, "mouse", "alternate"), playstyle.describe(7, s, "tablet", "alternate")
    assert mouse["tablet"] == 0 and tablet["tablet"] == 1
    assert mouse["hold"] == tablet["hold"] and mouse["bias_x"] == tablet["bias_x"] and mouse["spin"] == tablet["spin"]
    assert playstyle.describe(7, s, tap_style="singletap")["singletap"] == 1


def test_jump_players_snap_and_stream_players_flow():
    jumper = [playstyle.describe(i, skills(aim=90, tapping=40, technical=40))["flow"] for i in range(200)]
    streamer = [playstyle.describe(i, skills(aim=40, tapping=90, technical=70))["flow"] for i in range(200)]
    assert statistics.mean(jumper) < 0.35 < 0.65 < statistics.mean(streamer)


def test_styles_vary_within_reason():
    styles = [playstyle.describe(i, skills(), year=2016) for i in range(400)]
    assert 0.6 < statistics.mean(s["tablet"] for s in styles) < 0.9
    assert 0.05 < statistics.mean(s["singletap"] for s in styles) < 0.25
    assert all(0.5 <= s["hold"] <= 1.7 and 3.5 <= s["spin"] <= 8 and -12 <= s["timing_bias"] <= 10 for s in styles)
    assert statistics.mean(s["timing_bias"] for s in styles) < 0  # most players hit a little early
    early = [playstyle.describe(i, skills(), year=2008)["tablet"] for i in range(400)]
    assert statistics.mean(early) < statistics.mean(s["tablet"] for s in styles)


def test_timing_habit_moves_the_errors():
    profile = analyze(make_osu_file(1, 1, spacing=60, gap_ms=400).encode())
    s = {k: 80.0 for k in A.SUBSTATS}

    def mean_error(bias: float) -> float:
        errors = []
        for k in range(10):
            a = play.simulate(profile, s, "", play.DayModifiers(timing_bias=bias), random.Random(k))
            errors += [e for e, c in zip(a.trace.error, a.trace.cause) if not c]
        return statistics.mean(errors)

    assert mean_error(-10) < mean_error(0) - 6
    assert mean_error(8) > mean_error(0) + 5
