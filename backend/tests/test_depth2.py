from datetime import date

import pytest

from app.db import SessionLocal
from app.engine import pp_history
from app.models import Npc, Player, Rival
from app.services import media, rivals, streaming
from tests.conftest import FIXTURE_BEATMAP_ID, seed_pool_maps


def _career(client, start="2016-10-15", seed=12, **extra):
    body = {"name": "Deep", "country": "RU", "start_date": start, "seed": seed, "age": 19, **extra}
    resp = client.post("/api/players", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- 5. pp history -------------------------------------------------------------------------


def test_eras_follow_the_official_timeline():
    assert pp_history.era_for(date(2010, 1, 1)).key == "ranked_score"
    assert pp_history.era_for(date(2013, 1, 1)).key == "ppv1"
    assert pp_history.era_for(date(2014, 1, 27)).key == "ppv2"
    assert pp_history.era_for(date(2021, 12, 1)).key == "ppv2_2021_11"
    assert pp_history.era_for(date(2024, 11, 1)).key == "ppv2_2024_10"


def test_combo_scaling_and_ppv1_decay():
    old = pp_history.era_for(date(2016, 1, 1))
    new = pp_history.era_for(date(2025, 1, 1))
    choke = pp_history.adjust(300, 150, 150, 50, combo=500, map_max_combo=1000, era=old)
    assert choke < pp_history.adjust(300, 150, 150, 50, combo=1000, map_max_combo=1000, era=old)
    assert pp_history.adjust(300, 150, 150, 50, combo=500, map_max_combo=1000, era=new) == pytest.approx(300)
    v1 = pp_history.era_for(date(2013, 1, 1))
    fresh = pp_history.adjust(300, 150, 150, 50, 1000, 1000, v1, age_days=0)
    year_old = pp_history.adjust(300, 150, 150, 50, 1000, 1000, v1, age_days=365)
    assert year_old == pytest.approx(fresh * 0.5, rel=0.01)


def test_rework_reprices_scores_and_makes_news(client):
    pid = _career(client, start="2024-10-10")
    resp = client.post(f"/api/players/{pid}/scores",
                       json={"beatmap_id": FIXTURE_BEATMAP_ID, "accuracy": 97, "misses": 3, "combo": 150})
    assert resp.status_code == 200, resp.text
    before = client.get(f"/api/players/{pid}").json()
    assert before["pp_system"]["key"] == "ppv2_2021_11"
    events = client.post(f"/api/players/{pid}/rest", json={"days": 25}).json()["events"]
    assert any(e["type"] == "WORLD_PP_SYSTEM_CHANGE" for e in events)
    after = client.get(f"/api/players/{pid}").json()
    assert after["pp_system"]["key"] == "ppv2_2024_10"
    assert after["total_pp"] > before["total_pp"]  # the choke stops being punished by combo scaling
    forum = client.get(f"/api/players/{pid}/forum", params={"kind": "rework"}).json()
    assert forum and "MEGATHREAD" in forum[0]["title"]


# --- 6. rivals ---------------------------------------------------------------------------------


def test_rivals_are_near_your_rank_and_take_things_personally(client):
    pid = _career(client)
    client.post(f"/api/players/{pid}/scores", json={"beatmap_id": FIXTURE_BEATMAP_ID, "accuracy": 98})
    listed = client.get(f"/api/players/{pid}/rivals").json()
    assert 1 <= len(listed) <= rivals.MAX_RIVALS
    me = client.get(f"/api/players/{pid}").json()["global_rank"]
    assert all(me / rivals.RANK_WINDOW <= r["rank"] <= me * rivals.RANK_WINDOW for r in listed)
    dm_channels = [c for c in client.get(f"/api/players/{pid}/irc/channels").json() if c.startswith("DM:")]
    assert dm_channels

    with SessionLocal() as db:
        player = db.get(Player, pid)
        npc_id = listed[0]["npc_id"]
        heat = db.query(Rival).filter_by(player_id=pid, npc_id=npc_id).one().heat
        rivals.on_snipe(db, player, npc_id, user_sniped=True)
        rival = db.query(Rival).filter_by(player_id=pid, npc_id=npc_id).one()
        assert rival.heat == heat + rivals.HEAT_SNIPE and rival.record["snipes_for"] == 1


def test_overtaking_a_heated_rival_reaches_sillytavern(client):
    pid = _career(client)
    with SessionLocal() as db:
        player = db.get(Player, pid)
        npc = db.query(Npc).filter(Npc.player_id == pid, Npc.rank > 50).first()
        db.add(Rival(player_id=pid, npc_id=npc.id, since=player.in_game_date, heat=80, active=True, record={}))
        db.flush()  # sessions don't autoflush
        player.global_rank = npc.rank - 1  # we just passed them
        rivals.weekly(db, player, rank_before=npc.rank + 10)
        db.commit()
    events = client.get(f"/api/st/careers/{pid}/events", params={"limit": 50}).json()
    overtake = next(e for e in events if e["type"] == "RIVAL_OVERTAKE")
    assert overtake["thread"] is None and overtake["payload"]["data"]["user_passed_rival"] is True


# --- 7. streaming --------------------------------------------------------------------------


def test_streaming_needs_twitch_and_pays_off(client):
    early = _career(client, start="2010-05-01", seed=13)
    with SessionLocal() as db:
        seed_pool_maps(db)
    resp = client.post(f"/api/players/{early}/sessions/auto", json={"preset": "farm", "hours": 1, "stream": True})
    assert resp.status_code == 409

    pid = _career(client, seed=14)
    resp = client.post(f"/api/players/{pid}/sessions/auto", json={"preset": "farm", "hours": 1, "stream": True})
    assert resp.status_code == 200, resp.text
    stream = next(e for e in resp.json()["events"] if e["type"] == "STREAM")
    assert stream["data"]["followers"] > 0
    life = client.get(f"/api/players/{pid}").json()["life"]
    assert life["followers"] == stream["data"]["followers"]
    assert client.get(f"/api/players/{pid}/irc", params={"channel": streaming.TWITCH_CHANNEL}).json()


# --- 8. replays ---------------------------------------------------------------------------


def test_watching_replays_is_easy_on_the_hands(client):
    pid = _career(client)
    drills = {d["key"]: d for d in client.get(f"/api/players/{pid}/drills").json()}
    assert drills["watch_replays"]["available"] and not drills["watch_replays"]["sets_scores"]
    before = client.get(f"/api/players/{pid}").json()
    after = client.post(f"/api/players/{pid}/train",
                        json={"drill": "watch_replays", "hours_per_day": 3, "days": 3}).json()
    assert after["player"]["conditions"]["fatigue"] <= before["conditions"]["fatigue"] + 1
    assert after["player"]["conditions"]["motivation"] >= before["conditions"]["motivation"]
    assert "rhythm_reading" in after["deltas"] and "hand_stamina" not in after["deltas"]
