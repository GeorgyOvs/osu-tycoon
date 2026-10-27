from tests.conftest import FIXTURE_BEATMAP_ID


def _player(client, name="Me"):
    return client.post("/api/players", json={"name": name, "country": "RU", "start_date": "2016-10-17",
                                             "seed": 1, "age": 17}).json()["id"]


def _score(**over):
    body = {"client_score_id": "c" * 32, "beatmap_id": FIXTURE_BEATMAP_ID, "beatmap_md5": "a" * 32,
            "artist": "Artist", "title": "Test Song", "version": "Normal", "mods": ["HD", "CL"],
            "great": 190, "ok": 8, "meh": 1, "miss": 1, "max_combo": 150, "accuracy": 0.9683,
            "total_score": 900000, "status": "passed", "progress": 1.0, "played_at": "2026-10-25T12:00:00Z"}
    return body | over


def test_needs_active_player(client):
    _player(client)
    assert client.get("/api/client/active-player").json() == {"player_id": None, "name": None}
    assert client.post("/api/client/scores", json=_score()).status_code == 409


def test_pass_is_recorded_once_with_pp(client):
    pid = _player(client)
    assert client.put("/api/client/active-player", json={"player_id": pid}).json()["name"] == "Me"
    r = client.post("/api/client/scores", json=_score())
    assert r.status_code == 200
    play = r.json()
    assert play["source"] == "client" and play["mods"] == "HD"  # lazer-only CL dropped
    assert play["pp"] > 0 and abs(play["accuracy"] - 96.83) < 1e-6
    assert client.post("/api/client/scores", json=_score()).json()["id"] == play["id"]  # retry is idempotent
    assert len(client.get(f"/api/players/{pid}/real").json()) == 1


def test_fail_keeps_progress_without_pp(client):
    pid = _player(client)
    client.put("/api/client/active-player", json={"player_id": pid})
    play = client.post("/api/client/scores", json=_score(status="failed", progress=0.64)).json()
    assert play["status"] == "failed" and play["pp"] == 0 and play["progress"] == 0.64


def test_other_rulesets_rejected(client):
    pid = _player(client)
    client.put("/api/client/active-player", json={"player_id": pid})
    assert client.post("/api/client/scores", json=_score(ruleset="taiko")).status_code == 422


def _set_skill(pid, value, fatigue=0.0):
    from app.db import SessionLocal
    from app.models import Player
    with SessionLocal() as db:
        player = db.get(Player, pid)
        for a in player.attributes:
            a.base = a.cap = float(value)
            a.rust = 0.0
        player.fatigue = fatigue
        player.form = 0.0
        db.commit()


def test_assist_inactive_without_player(client):
    assert client.get("/api/client/assist").json()["active"] is False


def test_assist_follows_stats_and_fatigue(client):
    pid = _player(client)
    client.put("/api/client/active-player", json={"player_id": pid})
    _set_skill(pid, 90)
    strong = client.get("/api/client/assist").json()
    assert strong["active"] and strong["od_delta"] < 0 and strong["cs_delta"] < 0 and strong["ar_delta"] < 0
    _set_skill(pid, 10)
    weak = client.get("/api/client/assist").json()
    assert weak["od_delta"] > 0 and weak["cs_delta"] > 0 and weak["ar_delta"] > 0
    assert max(abs(weak["od_delta"]), abs(strong["od_delta"])) <= 4.0
    _set_skill(pid, 90, fatigue=80)
    tired = client.get("/api/client/assist").json()
    assert tired["condition"] < strong["condition"] and tired["hp_delta"] > strong["hp_delta"]


def test_score_keeps_applied_assist(client):
    pid = _player(client)
    client.put("/api/client/active-player", json={"player_id": pid})
    play = client.post("/api/client/scores", json=_score(mods=["HD", "CR"], assist={"od_delta": -0.5})).json()
    assert play["mods"] == "HD"
    from app.db import SessionLocal
    from app.models import RealPlay
    with SessionLocal() as db:
        assert db.get(RealPlay, play["id"]).assist == {"od_delta": -0.5}


def test_assist_settings_scale_and_magnet(client):
    pid = _player(client)
    client.put("/api/client/active-player", json={"player_id": pid})
    _set_skill(pid, 90)
    default = client.get(f"/api/players/{pid}/assist").json()
    assert default["scale"] == 1.0 and default["magnet"] is False and default["assist"]["magnet"] == 0

    doubled = client.put(f"/api/players/{pid}/assist", json={"scale": 2.0, "magnet": True}).json()
    assert abs(doubled["assist"]["cs_delta"] - 2 * default["assist"]["cs_delta"]) < 0.02
    assert doubled["assist"]["magnet"] > 0
    assert client.get("/api/client/assist").json()["magnet"] == doubled["assist"]["magnet"]  # the client sees it

    off = client.put(f"/api/players/{pid}/assist", json={"scale": 0, "magnet": True}).json()["assist"]
    assert off["od_delta"] == off["cs_delta"] == off["magnet"] == 0
    assert client.put(f"/api/players/{pid}/assist", json={"scale": 3, "magnet": False}).status_code == 422


def test_magnet_needs_strong_aim(client):
    pid = _player(client)
    _set_skill(pid, 30)
    weak = client.put(f"/api/players/{pid}/assist", json={"scale": 1, "magnet": True}).json()["assist"]
    assert weak["magnet"] == 0 and weak["cs_delta"] > 0


def test_character_play_is_read_only_and_reproducible(client):
    from app.db import SessionLocal
    from app.models import Player
    pid = _player(client)
    client.put("/api/client/active-player", json={"player_id": pid})
    _set_skill(pid, 60)
    with SessionLocal() as db:
        before = (db.get(Player, pid).fatigue, db.get(Player, pid).play_count)
    a = client.get(f"/api/client/character-play?beatmap_id={FIXTURE_BEATMAP_ID}&mods=HD,CR&seed=7").json()
    b = client.get(f"/api/client/character-play?beatmap_id={FIXTURE_BEATMAP_ID}&mods=HD,CR&seed=7").json()
    assert a == b and a["mods"] == "HD" and a["player_name"] == "Me"
    objs = a["objects"]
    assert objs and all(o["result"] in ("great", "ok", "meh", "miss") for o in objs)
    assert [o["time"] for o in objs] == sorted(o["time"] for o in objs)
    hits = sum(o["result"] != "miss" for o in objs)
    assert hits > 0 and (a["passed"] or a["fail_index"] is not None)
    with SessionLocal() as db:
        assert (db.get(Player, pid).fatigue, db.get(Player, pid).play_count) == before
    dt = client.get(f"/api/client/character-play?beatmap_id={FIXTURE_BEATMAP_ID}&mods=DT&seed=7").json()
    k = min(len(dt["objects"]), len(objs)) - 1
    assert abs(dt["objects"][k]["time"] - objs[k]["time"]) < 5  # beatmap clock, whatever the rate
    assert client.get("/api/client/character-play?beatmap_id=999999999").status_code == 404


def test_character_play_for_the_career_counts(client):
    from app.db import SessionLocal
    from app.models import HandDay, Player, Score
    pid = _player(client)
    client.put("/api/client/active-player", json={"player_id": pid})
    _set_skill(pid, 95)  # strong enough to pass the fixture map
    played = client.post(f"/api/client/character-play?beatmap_id={FIXTURE_BEATMAP_ID}&mods=HD&seed=3").json()
    assert played["counted"] and played["objects"]
    with SessionLocal() as db:
        assert db.get(HandDay, pid).attempts == 1  # it cost time in the day
        scores = db.query(Score).filter_by(player_id=pid).all()
        if played["passed"]:
            assert played["career_score_id"] == scores[0].id and played["pp"] > 0
            assert db.get(Player, pid).total_pp > 0
        else:
            assert not scores and played["career_score_id"] is None
    watched = client.get(f"/api/client/character-play?beatmap_id={FIXTURE_BEATMAP_ID}&mods=HD&seed=3").json()
    assert not watched["counted"]
    with SessionLocal() as db:
        assert db.get(HandDay, pid).attempts == 1  # watching changed nothing


def test_character_plays_a_series(client):
    from app.db import SessionLocal
    from app.models import HandDay
    pid = _player(client)
    client.put("/api/client/active-player", json={"player_id": pid})
    _set_skill(pid, 95)
    out = client.post(f"/api/client/character-play?beatmap_id={FIXTURE_BEATMAP_ID}&mods=HD&attempts=4").json()
    assert len(out["attempts"]) == 4 and out["objects"] and 0 <= out["best_index"] < 4
    assert {"tablet", "flow", "hold", "spin"} <= out["style"].keys()
    best = out["attempts"][out["best_index"]]
    assert best["passed"] == out["passed"]
    assert all(a["passed"] <= best["passed"] for a in out["attempts"])
    assert all(bool(a["objects"]) == a["passed"] for a in out["attempts"])  # every pass can be kept locally
    assert all({"sliderbreaks", "restarted"} <= a.keys() for a in out["attempts"])
    assert all(a["passed"] or a["progress"] < 1 for a in out["attempts"])
    assert not out["attempts"][0]["restarted"]  # nothing to improve on before the first pass
    with SessionLocal() as db:
        assert db.get(HandDay, pid).attempts == 4  # every attempt cost time
