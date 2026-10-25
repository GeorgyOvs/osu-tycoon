import random
from datetime import date

import pytest

from app.db import SessionLocal
from app.engine import commentary, play
from app.engine.map_analysis import analyze
from app.models import Npc, Player
from tests.conftest import FIXTURE_BEATMAP_ID, make_osu_file, make_stream_osu, seed_pool_maps
from tests.test_play import skills


@pytest.fixture(scope="module")
def stream_map():
    return analyze(make_stream_osu(2, 2, bpm=240, stream_len=32).encode())


@pytest.fixture(scope="module")
def jump_map():
    return analyze(make_osu_file(1, 1).encode())


def _run(profile, level, seed="r"):
    return play.simulate(profile, skills(level), "", play.DayModifiers(), random.Random(seed))


def _check(replay, profile):
    n = len(replay["t"])
    assert 1 <= n <= play.TIMELINE_BUCKETS
    for col in ("combo", "hp", "misses", "acc", "strain", "kind"):
        assert len(replay[col]) == n
    assert replay["t"] == sorted(replay["t"])
    assert replay["misses"] == sorted(replay["misses"])
    assert all(0 <= h <= 1 for h in replay["hp"])
    assert all(0 <= s <= 1 for s in replay["strain"])
    assert all(0 <= c <= profile.max_combo for c in replay["combo"])
    assert all(0 <= a <= 100 for a in replay["acc"])
    assert replay["moments"] == sorted(replay["moments"], key=lambda m: m["t"])


@pytest.mark.parametrize("level", [15, 45, 90])
def test_replay_invariants(stream_map, jump_map, level):
    for prof in (stream_map, jump_map):
        a = _run(prof, level)
        replay = a.replay(prof)
        _check(replay, prof)
        assert replay["misses"][-1] <= a.misses
        types = {m["type"] for m in replay["moments"]}
        if not a.passed:
            assert "fail" in types
        if a.passed and a.misses == 0:
            assert "fc" in types


def test_replay_does_not_change_the_simulation(stream_map):
    a = _run(stream_map, 40, "same")
    b = _run(stream_map, 40, "same")
    assert (a.n300, a.n100, a.misses, a.passed) == (b.n300, b.n100, b.misses, b.passed)
    assert a.replay(stream_map) == b.replay(stream_map)


def test_commentary_is_deterministic_and_timestamped(stream_map):
    a = _run(stream_map, 30)
    ctx = {"player": "Tester", "title": "A - B", "mods": "HD", "stars": 5.5, "passed": a.passed,
           "accuracy": a.accuracy, "misses": a.misses, "grade": a.grade, "choked": a.choked}
    lines = commentary.play_lines(a.replay(stream_map), ctx, date(2016, 1, 1), "seed")
    assert lines == commentary.play_lines(a.replay(stream_map), ctx, date(2016, 1, 1), "seed")
    assert lines[0]["t"] == 0 and "Tester" in lines[0]["text"]
    assert [l["t"] for l in lines] == sorted(l["t"] for l in lines)
    assert all(l["tone"] and l["who"] for l in lines)
    assert lines[-1]["t"] >= max(l["t"] for l in lines[:-1])


def test_session_attempts_carry_replay_and_commentary(client):
    pid = client.post("/api/players", json={"name": "U", "start_date": "2016-10-15", "seed": 1}).json()["id"]
    data = client.post(f"/api/players/{pid}/sessions",
                       json={"plays": [{"beatmap_id": FIXTURE_BEATMAP_ID, "attempts": 2}]}).json()
    for attempt in data["plays"][0]["attempts"]:
        assert attempt["replay"]["t"] and attempt["replay"]["moments"] is not None
        assert attempt["commentary"][0]["t"] == 0
        assert len(attempt["timeline"]) == play.TIMELINE_BUCKETS  # the old shape is untouched


def test_duel_exposes_map_replays_and_a_broadcast(client):
    pid = client.post("/api/players", json={"name": "Duelist", "country": "RU", "start_date": "2016-10-17",
                                             "seed": 40, "age": 17}).json()["id"]
    with SessionLocal() as db:
        seed_pool_maps(db, n=60)
        player = db.get(Player, pid)
        for a in player.attributes:
            a.base = 45.0
        npc = (db.query(Npc).filter(Npc.player_id == pid, Npc.status == "active", Npc.rank.isnot(None),
                                    Npc.overall.between(20, 60)).order_by(Npc.rank.desc()).first())
        player.global_rank = npc.rank
        npc_id = npc.id
        db.commit()
    d = client.post(f"/api/players/{pid}/duels", json={"npc_id": npc_id, "best_of": 3}).json()
    assert d["commentary"] is None  # nothing was played yet
    played = client.post(f"/api/players/{pid}/duels/{d['id']}/play").json()
    maps = [m for m in played["maps"] if "slot" in m]
    for m in maps:
        for p in m["players"]:
            assert p["replay"]["t"] and "passed" in p
            _check(p["replay"], type("P", (), {"max_combo": m["players"][0]["max_combo"]}))
    cast = played["commentary"]
    assert len(cast["maps"]) == len(maps) == len(cast["between"])
    assert cast["pre"] and cast["post"]
    assert any("Score:" in l["text"] for l in cast["between"][0])
    assert client.get(f"/api/players/{pid}/duels").json()[0]["commentary"]["post"]
