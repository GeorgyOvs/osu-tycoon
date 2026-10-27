from tests.conftest import FIXTURE_BEATMAP_ID

from app.db import SessionLocal
from app.models import HandDay, Player, RealPlay, Score
from app.services import hand_play


def _career(client, start="2016-10-17"):
    pid = client.post("/api/players", json={"name": "Hands", "country": "RU", "start_date": start, "seed": 3,
                                             "age": 17}).json()["id"]
    client.put("/api/client/active-player", json={"player_id": pid})
    return pid


def _play(client, n, **over):
    body = {"client_score_id": f"{n:032x}", "beatmap_id": FIXTURE_BEATMAP_ID, "beatmap_md5": "a" * 32,
            "artist": "Artist", "title": "Test Song", "version": "Normal", "mods": ["HD"],
            "great": 190, "ok": 8, "meh": 1, "miss": 1, "max_combo": 150, "accuracy": 0.9683,
            "total_score": 900000, "status": "passed", "progress": 1.0, "played_at": "2026-10-25T12:00:00Z"}
    resp = client.post("/api/client/scores", json=body | over)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_pass_becomes_a_career_score(client):
    pid = _career(client)
    play = _play(client, 1)
    assert play["career_score_id"] and play["career_note"] == "" and play["pp"] > 0
    with SessionLocal() as db:
        player = db.get(Player, pid)
        score = db.get(Score, play["career_score_id"])
        assert score.player_id == pid and score.mods == "HD" and score.beatmap_id == FIXTURE_BEATMAP_ID
        assert player.total_pp > 0
    day = client.get(f"/api/players/{pid}/hand-day").json()
    assert day["attempts"] == 1 and day["hours"] > 0 and day["blocked"] is None
    me = client.get(f"/api/players/{pid}").json()
    assert me["total_pp"] > 0


def test_fail_costs_time_but_scores_nothing(client):
    pid = _career(client)
    play = _play(client, 2, status="failed", progress=0.5)
    assert play["career_score_id"] is None
    with SessionLocal() as db:
        assert db.query(Score).filter_by(player_id=pid).count() == 0
        assert db.get(HandDay, pid).attempts == 1


def test_relax_counts(client):
    _career(client)
    play = _play(client, 3, mods=["HD", "RX"])
    assert play["career_score_id"] and play["mods"] == "HDRX"


def test_map_from_the_future_doesnt_count(client):
    pid = _career(client, start="2008-01-01")  # the fixture map is ranked in 2010
    play = _play(client, 4)
    assert play["career_score_id"] is None and "2010" in play["career_note"]
    assert client.get(f"/api/players/{pid}/hand-day").json()["attempts"] == 1  # the time was still spent


def test_finishing_the_day_moves_the_calendar(client):
    pid = _career(client)
    date_before = client.get(f"/api/players/{pid}").json()["in_game_date"]
    assert client.post(f"/api/players/{pid}/hand-day/finish").status_code == 409  # nothing played yet
    for n in range(3):
        _play(client, 10 + n)
    done = client.post(f"/api/players/{pid}/hand-day/finish").json()
    assert done["start_date"][:10] == date_before and done["end_date"][:10] > date_before
    assert client.get(f"/api/players/{pid}").json()["in_game_date"] > date_before
    assert client.get(f"/api/players/{pid}/hand-day").json()["attempts"] == 0


def test_day_closes_by_itself(client, monkeypatch):
    monkeypatch.setattr(hand_play, "AUTO_FINISH_HOURS", 0.01)
    pid = _career(client)
    date_before = client.get(f"/api/players/{pid}").json()["in_game_date"]
    _play(client, 20)
    assert client.get(f"/api/players/{pid}").json()["in_game_date"] > date_before
    assert client.get(f"/api/players/{pid}/hand-day").json()["attempts"] == 0


def test_long_day_wears_the_character_down(client):
    pid = _career(client)
    fresh = client.get("/api/client/assist").json()["condition"]
    with SessionLocal() as db:
        day = hand_play.state(db, db.get(Player, pid))
        day.seconds, day.attempts = 3.5 * 3600, 60
        db.commit()
    tired = client.get("/api/client/assist").json()["condition"]
    assert tired < fresh
