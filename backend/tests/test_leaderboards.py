import json
import random
from datetime import date, timedelta

import pytest

from app.db import SessionLocal
from app.engine import leaderboard as lb
from app.engine import scoring, world
from app.models import MapBoard, Player, Score, StEvent
from app.services import leaderboards, media
from tests.conftest import FIXTURE_BEATMAP_ID

MAP = FIXTURE_BEATMAP_ID


# --- engine -------------------------------------------------------------------------------


def test_score_v1_rewards_combo_and_mods():
    fc = scoring.score_v1(500, 0, 0, 0, 600, 600, 4, "")
    one_miss = scoring.score_v1(499, 0, 0, 1, 300, 600, 4, "")
    assert fc > one_miss * 1.5  # a mid-map miss roughly halves the combo bonus
    assert scoring.score_v1(500, 0, 0, 0, 600, 600, 4, "HDHR") > fc
    assert scoring.score_v1(500, 0, 0, 0, 600, 600, 4, "NF") < fc
    # an accuracy drop costs far less than a combo break
    assert scoring.score_v1(480, 20, 0, 0, 600, 600, 4, "") > one_miss


def test_counts_from_accuracy_reproduce_it():
    n300, n100, n50 = scoring.counts_from_accuracy(1000, 97.5, 3)
    assert n300 + n100 + n50 == 997
    acc = 100 * (300 * n300 + 100 * n100 + 50 * n50) / 300000
    assert acc == pytest.approx(97.5, abs=0.1)


def _facts(stars=5.0, ar=9.0):
    opts = lb.MOD_OPTIONS
    mult = {"": 1.0, "HD": 1.04, "HR": 1.08, "DT": 1.45, "HDHR": 1.12, "HDDT": 1.5}
    return lb.MapFacts(
        n_objects=800, max_combo=1000, aim_share=0.5, stars={m: stars * mult[m] for m in opts},
        ar={m: min(11, ar + (1.4 if "DT" in m else 0) + (0.9 if "HR" in m else 0)) for m in opts},
        od={m: 8.0 + (1.5 if "HR" in m else 0) for m in opts}, difficulty={m: 4 for m in opts},
    )


def test_estimates_scale_with_skill():
    facts = _facts(stars=5.0)
    weak = lb.estimate_best(world.composites(25, {}), facts, date(2016, 1, 1), 5, random.Random(1))
    mid = lb.estimate_best(world.composites(60, {}), facts, date(2016, 1, 1), 5, random.Random(1))
    top = lb.estimate_best(world.composites(98, {}), facts, date(2016, 1, 1), 5, random.Random(1))
    assert weak is None  # can't pass a 5* map
    assert mid is not None and top is not None and top.score > mid.score


def test_era_meta_blocks_hddt_on_high_ar_before_2013():
    facts = _facts(stars=2.5, ar=9.5)
    comps = world.composites(98, {})
    early = {lb.estimate_best(comps, facts, date(2011, 6, 1), 3, random.Random(k)).mods for k in range(60)}
    late = {lb.estimate_best(comps, facts, date(2018, 6, 1), 3, random.Random(k)).mods for k in range(60)}
    assert "HDDT" not in early
    assert "HDDT" in late or "DT" in late


# --- boards ------------------------------------------------------------------------------------


def _career(client, start="2016-10-15"):
    return client.post("/api/players", json={"name": "Tester", "country": "RU", "start_date": start, "seed": 9}).json()["id"]


def _board(client, pid):
    resp = client.get(f"/api/players/{pid}/beatmaps/{MAP}/leaderboard")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_board_is_simulated_sorted_and_stable(client):
    pid = _career(client)
    first = _board(client, pid)
    entries = first["entries"]
    assert len(entries) >= 10
    scores = [e["score"] for e in entries]
    assert scores == sorted(scores, reverse=True)
    assert all(date.fromisoformat(e["set_on"]) <= date(2016, 10, 15) for e in entries)
    assert all(date.fromisoformat(e["set_on"]) >= date(2010, 1, 1) for e in entries)  # ranked 2010
    assert first["user_rank"] is None
    assert _board(client, pid)["entries"] == entries  # same day, same names


def test_board_only_moves_forward(client):
    pid = _career(client)
    before = {e["name"]: e["score"] for e in _board(client, pid)["entries"]}
    client.post(f"/api/players/{pid}/rest", json={"days": 30})
    client.post(f"/api/players/{pid}/rest", json={"days": 30})
    after = {e["name"]: e["score"] for e in _board(client, pid)["entries"]}
    for name, score in before.items():
        if name in after:
            assert after[name] >= score


def test_user_snipes_first_place(client, monkeypatch):
    monkeypatch.setattr(media, "POPULAR_MAP_PLAYS", 0)  # treat the fixture map as famous
    pid = _career(client)
    top = _board(client, pid)["entries"][0]
    resp = client.post(f"/api/players/{pid}/scores",
                       json={"beatmap_id": MAP, "mods": "HDHR", "accuracy": 100, "misses": 0})
    assert resp.status_code == 200, resp.text
    board = _board(client, pid)
    assert board["user_rank"] == 1
    events = client.get(f"/api/st/careers/{pid}/events", params={"limit": 50}).json()
    snipe = next(e for e in events if e["type"] == "SNIPE_FIRST_PLACE")
    assert snipe["payload"]["data"]["sniped_player"] == top["name"]
    with SessionLocal() as db:
        assert db.get(MapBoard, (pid, MAP)).user_first


def test_npcs_can_take_first_place_back(client):
    pid = _career(client, start="2010-06-01")
    _board(client, pid)
    with SessionLocal() as db:
        player = db.get(Player, pid)
        # a weak first score that happens to be #1 (pretend nobody else had played yet)
        db.add(Score(player_id=pid, beatmap_id=MAP, beatmapset_id=None, artist="a", title="t", difficulty_name="d",
                     mods="", accuracy=70.0, max_combo=50, misses=40, stars=4.0, pp=10.0, score_value=1,
                     played_on=player.in_game_date))
        db.flush()
        db.get(MapBoard, (pid, MAP)).user_first = True
        player.in_game_date += timedelta(days=365)
        board, snipes = leaderboards.ensure_board(db, player, MAP)
        assert snipes and not board.user_first
        db.rollback()


def test_anchor_scores_need_a_source_and_respect_dates(client, tmp_path, monkeypatch):
    anchor = {"beatmap_id": MAP, "player": "RealLegend", "country": "JP", "mods": "HD", "score": 10**9,
              "accuracy": 99.9, "max_combo": 600, "misses": 0, "date": "2018-01-01", "source": "https://example.org/a"}
    path = tmp_path / "anchors.json"
    path.write_text(json.dumps([anchor]))
    monkeypatch.setattr(leaderboards, "ANCHOR_FILE", path)
    leaderboards.anchors.cache_clear()
    try:
        pid = _career(client)
        assert all(e["kind"] != "anchor" for e in _board(client, pid)["entries"])  # 2016: not yet set
        late = _career(client, start="2019-01-01")
        top = _board(client, late)["entries"][0]
        assert top["kind"] == "anchor" and top["source"] == "https://example.org/a"

        path.write_text(json.dumps([{**anchor, "source": ""}]))
        leaderboards.anchors.cache_clear()
        with pytest.raises(ValueError):
            leaderboards.anchors()
    finally:
        leaderboards.anchors.cache_clear()
