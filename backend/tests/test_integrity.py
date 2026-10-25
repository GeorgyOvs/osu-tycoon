import random
from datetime import date

import pytest

from app.db import SessionLocal
from app.engine import integrity as I
from app.models import ForumThread, Npc, Player, Score, WorldEvent
from app.services import integrity, story


def new_player(client, seed=6, start="2014-03-01", **extra):
    body = dict(name="Clean", country="RU", start_date=start, seed=seed, age=18, **extra)
    return client.post("/api/players", json=body).json()["id"]


def overview(client, pid, lang="en"):
    r = client.get(f"/api/players/{pid}/integrity", params={"lang": lang})
    assert r.status_code == 200, r.text
    return r.json()


def open_case(pid, kind="great_play", **detail):
    with SessionLocal() as db:
        player = db.get(Player, pid)
        case = integrity._open_case(db, player, {"kind": kind, "level": 0.5, **detail}, player.in_game_date)
        db.commit()
        return case["id"]


def test_fresh_career_has_neutral_reputation(client):
    pid = new_player(client)
    data = overview(client, pid)
    assert data["reputation"] == I.REPUTATION_START and data["open"] == [] and data["restricted_until"] is None
    assert data["effects"]["sponsor"] == pytest.approx(1.0) and data["suspicion"]["level"] == 0


def test_reputation_hook_clamps_logs_and_drives_effects():
    assert I.sponsor_factor(0) < I.sponsor_factor(60) == 1.0 < I.sponsor_factor(100)
    assert I.follower_factor(0) < I.follower_factor(100)
    with SessionLocal() as db:
        from app.engine import simulation

        player = simulation.new_career("T", "RU", date(2014, 3, 1), 3, date(1996, 1, 1))
        assert integrity.adjust_reputation(player, 80, "test") == pytest.approx(40)
        assert integrity.reputation(player) == 100
        assert integrity.adjust_reputation(player, -250, "test") == pytest.approx(-100)
        assert integrity.reputation(player) == 0
        assert len(story.get(player, "integrity")["log"]) == 2
    assert I.label(5, "en") == "Disgraced" and I.label(95, "ru") == "Любимец сообщества"


def test_suspicion_sees_rank_jumps_and_implausible_plays(client):
    pid = new_player(client)
    with SessionLocal() as db:
        player = db.get(Player, pid)
        story.put(player, "rank_hist", [["2014-01-01", 90000], ["2014-02-20", 30000]])
        player.global_rank = 4000
        db.add(Score(player_id=pid, beatmap_id=1, artist="A", title="T", difficulty_name="X", mods="", accuracy=99.5,
                     max_combo=500, misses=0, stars=9.0, pp=500, played_on=player.in_game_date))
        db.flush()
        level, factors = integrity.suspicion(db, player)
    kinds = {f["kind"] for f in factors}
    assert {"rank_jump", "great_play"} <= kinds and level > 0.5


def test_a_case_can_be_answered_once_and_costs_or_pays(client):
    outcomes = set()
    for seed in range(10, 22):
        pid = new_player(client, seed=seed)
        cid = open_case(pid, play="A - T [X]", pp=500)
        data = overview(client, pid)
        assert [c["id"] for c in data["open"]] == [cid] and {o["key"] for o in data["open"][0]["options"]} == set(I.RESPONSES)
        r = client.post(f"/api/players/{pid}/integrity/cases/{cid}/respond", json={"choice": "replay"})
        assert r.status_code == 200, r.text
        done = r.json()["history"][0]
        assert done["response"] == "replay" and done["status"] == "cleared" or done["outcome"]
        outcomes.add(done["outcome"])
        assert client.post(f"/api/players/{pid}/integrity/cases/{cid}/respond", json={"choice": "replay"}).status_code == 409
        assert client.post(f"/api/players/{pid}/integrity/cases/99/respond", json={"choice": "replay"}).status_code == 404
    assert len(outcomes) == 2  # both the vindication and the lingering doubts occur across seeds


def test_bad_responses_and_streaming_before_twitch(client):
    pid = new_player(client, start="2010-03-01")
    cid = open_case(pid)
    assert client.post(f"/api/players/{pid}/integrity/cases/{cid}/respond", json={"choice": "dance"}).status_code == 422
    assert client.post(f"/api/players/{pid}/integrity/cases/{cid}/respond", json={"choice": "stream"}).status_code == 409


def test_ignored_cases_expire_into_ignoring(client):
    pid = new_player(client)
    cid = open_case(pid)
    for _ in range(3):
        client.post(f"/api/players/{pid}/rest", json={"days": 4, "physio": False})
    data = overview(client, pid)
    assert data["open"] == []
    case = next(c for c in data["history"] if c["id"] == cid)
    assert case["auto"] and case["response"] == "ignore" and case["rep_delta"] < 0


def test_restriction_blocks_ranked_scores_until_the_review_ends(client):
    from tests.conftest import FIXTURE_BEATMAP_ID

    pid = new_player(client)
    with SessionLocal() as db:
        player = db.get(Player, pid)
        st = dict(story.get(player, "integrity", {}))
        st["restricted_until"] = "2014-03-08"
        story.put(player, "integrity", st)
        db.commit()
    assert overview(client, pid)["restricted_until"] == "2014-03-08"
    r = client.post(f"/api/players/{pid}/scores", json={"beatmap_id": FIXTURE_BEATMAP_ID, "accuracy": 97})
    assert r.status_code == 409 and "restricted" in r.json()["detail"]
    client.post(f"/api/players/{pid}/rest", json={"days": 9, "physio": False})
    data = overview(client, pid)
    assert data["restricted_until"] is None and data["reputation"] > 55
    news = client.get(f"/api/players/{pid}/news").json()
    assert any(n["type"] == "RESTRICTION_LIFTED" for n in news)
    assert client.post(f"/api/players/{pid}/scores", json={"beatmap_id": FIXTURE_BEATMAP_ID, "accuracy": 97}).status_code == 200


def test_suspicious_careers_get_accused_over_time(client):
    from datetime import timedelta

    pid = new_player(client, seed=3)
    with SessionLocal() as db:
        player = db.get(Player, pid)
        opened = False
        for _ in range(30):
            player.in_game_date += timedelta(days=7)
            player.global_rank = 2500
            story.put(player, "rank_hist", [[(player.in_game_date - timedelta(days=30)).isoformat(), 80000]])
            integrity.tick(db, player, [])
            if integrity._state(player).get("cases"):
                opened = True
                break
        assert opened
        case = integrity._state(player)["cases"][0]
        assert case["kind"] == "rank_jump" and case["detail"]["to_rank"] == 2500
        # the random life event must not pile on top of the real case
        assert story.get(player, "event_last")["cheat_accusation"] == case["opened"]


def test_world_scandals_restrict_npcs_and_start_a_thread(client):
    pid = new_player(client)
    client.get(f"/api/players/{pid}/leaderboard")
    with SessionLocal() as db:
        player = db.get(Player, pid)

        class Always(random.Random):
            def random(self):
                return 0.0

        news: list = []
        integrity._maybe_npc_scandal(db, player, date(2014, 3, 8), 1, Always(1), news)
        db.commit()
        assert news and news[0].type == "NPC_RESTRICTED"
        npc = db.get(Npc, news[0].data["npc_id"])
        assert npc.status == "hiatus" and npc.away_until > date(2014, 3, 8) and npc.story.get("restricted")
        assert db.query(WorldEvent).filter_by(player_id=pid, type="NPC_RESTRICTED").count() == 1
        assert db.query(ForumThread).filter_by(player_id=pid, kind="drama").count() >= 1


def test_russian_texts_are_complete(client):
    pid = new_player(client)
    open_case(pid, "rank_jump", from_rank=40000, to_rank=9000)
    data = overview(client, pid, "ru")
    case = data["open"][0]
    assert "{" not in case["title"] + case["body"] and "40000" in case["body"]
    assert all(any("а" <= ch.lower() <= "я" for ch in o["label"]) for o in case["options"])
