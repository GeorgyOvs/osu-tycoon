from datetime import date, timedelta

import pytest

from app.engine import psychology as P, simulation as S
from tests.conftest import FIXTURE_BEATMAP_ID


class Prof:
    def __init__(self, ar=9.0, longest_stream=0, fastest=0.0, sv=0.0):
        self.ar, self.longest_stream, self.fastest_stream_bpm, self.sv_variability = ar, longest_stream, fastest, sv


def player():
    return S.new_career("T", "RU", date(2016, 1, 1), 9)


def test_map_families():
    assert P.family(Prof(), "DT") == "dt" and P.family(Prof(), "HDHR") == "hr" and P.family(Prof(), "HD") == "hd"
    assert P.family(Prof(ar=7.5), "") == "reading"
    assert P.family(Prof(longest_stream=40, fastest=200), "") == "streams"
    assert P.family(Prof(sv=0.6), "") == "tech"
    assert P.family(Prof(), "") == "jumps"


def test_confidence_moves_with_results_and_fades():
    p, d = player(), date(2016, 1, 1)
    for _ in range(4):
        P.record_attempt(p, "jumps", True, False, 0, d)
    up = P.confidence(p, "jumps", d)
    assert 0.5 < up <= 1.0 and P.confidence(p, "streams", d) == 0.0
    assert P.confidence(p, "jumps", d + timedelta(days=21)) == pytest.approx(up / 2, rel=0.01)
    assert P.confidence(p, "jumps", d + timedelta(days=200)) < 0.01
    for _ in range(10):
        P.record_attempt(p, "jumps", False, False, 0, d)
    assert P.confidence(p, "jumps", d) < -0.5


def test_effects_are_small():
    skills = {"snap_aim": 50.0, "burst": 40.0}
    assert P.scale_skills(skills, 0.0) is skills  # neutral state is exactly the old behaviour
    assert P.scale_skills(skills, 1.0)["snap_aim"] == pytest.approx(52.0)
    assert P.scale_skills(skills, -1.0)["burst"] == pytest.approx(38.4)
    assert P.pressure_multiplier(1.0) == pytest.approx(1.15) and P.pressure_multiplier(0.0) == 1.0


def test_fear_builds_after_losses_and_is_cured_by_wins():
    p, d = player(), date(2016, 1, 1)
    P.record_match(p, [7], False, d)
    P.record_match(p, [7], False, d)
    assert P.fear(p, 7, d) == pytest.approx(0.8)
    assert P.fear(p, 8, d) == 0.0
    assert P.fear(p, 7, d + timedelta(days=30)) == pytest.approx(0.4)
    P.record_match(p, [7], True, d)
    assert P.fear(p, 7, d) == pytest.approx(0.45)
    P.record_match(p, [7], True, d)
    P.record_match(p, [7], True, d)
    assert P.fear(p, 7, d) == 0.0 and "7" not in p.story_state["mind"]["fear"]


def test_big_stage_trait_needs_history():
    p = player()
    assert P.clutch_factor(p) == 1.0
    for won in (True, True, True, True, False, True):
        P.record_decisive(p, won)
    assert 1.0 < P.clutch_factor(p) <= 1.03
    q = player()
    for won in (False,) * 6:
        P.record_decisive(q, won)
    assert 0.97 <= P.clutch_factor(q) < 1.0


def test_sessions_update_confidence_and_assess_reports_it(client):
    pid = client.post("/api/players", json=dict(name="M", country="RU", start_date="2016-01-01", seed=2, age=17)).json()["id"]
    before = client.get(f"/api/players/{pid}/assess/{FIXTURE_BEATMAP_ID}").json()
    assert before["confidence"] == 0.0 and before["family"]
    r = client.post(f"/api/players/{pid}/sessions", json={"plays": [{"beatmap_id": FIXTURE_BEATMAP_ID, "mods": "", "attempts": 4}]})
    assert r.status_code == 200, r.text
    mind = client.get(f"/api/players/{pid}/mind").json()
    assert any(v != 0 for v in mind["confidence"].values())
    after = client.get(f"/api/players/{pid}/assess/{FIXTURE_BEATMAP_ID}").json()
    assert after["confidence"] == mind["confidence"][after["family"]]
