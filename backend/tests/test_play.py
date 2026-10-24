import random

import pytest

from app.engine import attributes as A
from app.engine import play
from app.engine.map_analysis import analyze
from app.services import sessions
from datetime import date

from tests.conftest import FIXTURE_BEATMAP_ID, STREAM_BEATMAP_ID, make_osu_file, make_set, make_stream_osu


def skills(value: float, **overrides: float) -> dict[str, float]:
    s = {k: float(value) for k in A.SUBSTATS}
    s.update(overrides)
    return s


TAPPING = ("burst", "deathstream", "low_mid_bpm", "finger_independence")


@pytest.fixture(scope="module")
def jump_map():
    return analyze(make_osu_file(1, 1).encode())


@pytest.fixture(scope="module")
def stream_map():
    return analyze(make_stream_osu(2, 2, bpm=240, stream_len=32).encode())


def run(profile, sk, mods="", seed="t", day=None):
    return play.simulate(profile, sk, mods, day or play.DayModifiers(), random.Random(seed))


def test_analysis_finds_streams_and_applies_mods(stream_map):
    assert stream_map.longest_stream == 32
    assert stream_map.fastest_stream_bpm == pytest.approx(240, rel=0.02)
    dt = analyze(make_stream_osu(2, 2, bpm=240).encode(), "DT")
    assert dt.fastest_stream_bpm == pytest.approx(360, rel=0.02)
    assert dt.ar > stream_map.ar and dt.great_window < stream_map.great_window


def test_jump_map_has_no_streams(jump_map):
    assert jump_map.longest_stream == 0
    assert all(o.aim_demand >= 0 for o in jump_map.objects)


def test_simulation_is_deterministic(stream_map):
    a = run(stream_map, skills(50), seed="x")
    b = run(stream_map, skills(50), seed="x")
    assert (a.passed, a.n300, a.n100, a.misses) == (b.passed, b.n300, b.n100, b.misses)


def test_counts_add_up(stream_map):
    a = run(stream_map, skills(60))
    assert a.n300 + a.n100 + a.n50 + a.misses == len(stream_map.objects)
    assert 0 <= a.accuracy <= 100


def test_strong_player_cruises_weak_tapper_fails_streams(stream_map):
    strong = [run(stream_map, skills(90), seed=f"s{k}") for k in range(5)]
    assert all(a.passed for a in strong)
    assert sum(a.accuracy for a in strong) / 5 > 95

    weak = skills(90, **{k: 15.0 for k in TAPPING})
    attempts = [run(stream_map, weak, seed=f"w{k}") for k in range(5)]
    assert not any(a.passed for a in attempts)
    failed = attempts[0]
    assert 0 < failed.fail_progress < 1
    assert failed.grade == "F"
    assert any("BPM stream" in m for m in failed.key_moments)
    assert max(failed.miss_causes, key=failed.miss_causes.get) == "tapping"


def test_no_fail_finishes_with_a_terrible_score(stream_map):
    weak = skills(90, **{k: 15.0 for k in TAPPING})
    a = run(stream_map, weak, mods="NF")
    assert a.passed
    assert a.misses > len(stream_map.objects) * 0.3
    assert a.accuracy < 70


def test_more_skill_means_better_accuracy(jump_map):
    def mean_acc(level):
        return sum(run(jump_map, skills(level), seed=f"a{level}{k}").accuracy for k in range(8)) / 8

    assert mean_acc(30) < mean_acc(60) < mean_acc(95)


def test_bad_day_hurts(stream_map):
    sk = skills(55)
    good = play.DayModifiers(form=1.5)
    bad = play.DayModifiers(form=-1.5, fatigue=90, tilt=4)
    good_misses = sum(run(stream_map, sk, day=good, seed=f"d{k}", mods="NF").misses for k in range(6))
    bad_misses = sum(run(stream_map, sk, day=bad, seed=f"d{k}", mods="NF").misses for k in range(6))
    assert bad_misses > good_misses


def test_grades():
    assert play.grade(100, 0, 0, 0) == "SS"
    assert play.grade(95, 5, 0, 0) == "S"
    assert play.grade(95, 4, 0, 1) == "A"
    assert play.grade(50, 50, 0, 0) == "D"


def test_training_targets_follow_map_content(stream_map, jump_map):
    streams = play.training_targets(stream_map, "", len(stream_map.objects))
    assert streams["deathstream"] == 1.0 or "deathstream" in streams
    jumps = play.training_targets(jump_map, "HD", len(jump_map.objects))
    assert "snap_aim" in jumps and "hidden" in jumps
    assert "deathstream" not in jumps


def test_assessment_reflects_skill_gap(stream_map):
    easy = play.assess(stream_map, skills(90), "", play.DayModifiers(), "e", runs=8)
    hard = play.assess(stream_map, skills(90, **{k: 15.0 for k in TAPPING}), "", play.DayModifiers(), "h", runs=8)
    assert easy.pass_rate > hard.pass_rate
    assert hard.weakest == "tapping"
    assert hard.peak_ratios["tapping"] > 1.2


# --- API -------------------------------------------------------------------------------


def _player(client, start="2016-10-15", seed=1):
    return client.post("/api/players", json={"name": "U", "start_date": start, "seed": seed}).json()


def test_session_plays_maps_records_passes_and_advances_a_day(client):
    pid = _player(client)["id"]
    resp = client.post(
        f"/api/players/{pid}/sessions",
        json={"plays": [{"beatmap_id": FIXTURE_BEATMAP_ID, "attempts": 3}, {"beatmap_id": STREAM_BEATMAP_ID}]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["date"] == "2016-10-15"
    assert data["player"]["in_game_date"] == "2016-10-16"
    assert len(data["plays"]) == 2
    first = data["plays"][0]
    assert len(first["attempts"]) == 3
    assert len(first["attempts"][0]["timeline"]) == play.TIMELINE_BUCKETS
    assert data["hours"] > 0
    assert data["training"]

    # A fresh career (skills ~10) can't pass 240 BPM deathstreams.
    stream = data["plays"][1]
    assert stream["attempts"][0]["passed"] is False
    assert stream["score"] is None

    passes = [p for p in data["plays"] if p["score"]]
    profile = client.get(f"/api/players/{pid}").json()
    assert profile["play_count"] == sum(1 for p in data["plays"] for a in p["attempts"] if a["passed"])
    assert len(profile["top_plays"]) == len(passes)


def test_session_validation(client, monkeypatch):
    monkeypatch.setattr(sessions, "MAX_SESSION_HOURS", 1.0)
    pid = _player(client, start="2015-01-01")["id"]
    future = client.post(f"/api/players/{pid}/sessions", json={"plays": [{"beatmap_id": 2001}]})
    assert future.status_code == 409
    too_long = client.post(
        f"/api/players/{pid}/sessions", json={"plays": [{"beatmap_id": FIXTURE_BEATMAP_ID, "attempts": 10}] * 20}
    )
    assert too_long.status_code == 422
    assert client.get(f"/api/players/{pid}").json()["in_game_date"] == "2015-01-01"


def test_assess_endpoint(client):
    pid = _player(client)["id"]
    resp = client.get(f"/api/players/{pid}/assess/{STREAM_BEATMAP_ID}", params={"mods": "HD"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["mods"] == "HD"
    assert data["map"]["longest_stream"] == 32
    assert 0 <= data["pass_rate"] <= 1
    assert data["weakest"] in ("aim", "tapping", "reading")


def test_unloadable_maps_are_skipped_not_fatal(client, monkeypatch):
    from app.services import osu_files
    pid = _player(client)["id"]
    real = osu_files.get_osu_file

    def flaky(beatmap_id):
        if beatmap_id == 424242:
            raise osu_files.BeatmapNotFound("gone")
        return real(beatmap_id)

    monkeypatch.setattr(osu_files, "get_osu_file", flaky)
    from tests.conftest import FakeMirror
    monkeypatch.setattr(FakeMirror, "get_set_for_beatmap",
                        lambda self, bid: {424242: make_set(77, date(2010, 1, 1), [424242])}.get(bid)
                        or {FIXTURE_BEATMAP_ID: make_set(501, date(2010, 1, 1), [FIXTURE_BEATMAP_ID])}.get(bid))
    resp = client.post(f"/api/players/{pid}/sessions",
                       json={"plays": [{"beatmap_id": 424242}, {"beatmap_id": FIXTURE_BEATMAP_ID}]})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["plays"]) == 1
    only_bad = client.post(f"/api/players/{pid}/sessions", json={"plays": [{"beatmap_id": 424242}]})
    assert only_bad.status_code == 404
