import random

from app.db import SessionLocal
from app.models import Player
from app.services import autoplay
from tests.conftest import seed_pool_maps


def _career(client, start="2016-10-15", skill=None):
    pid = client.post("/api/players", json={"name": "Auto", "country": "RU", "start_date": start, "seed": 4}).json()["id"]
    with SessionLocal() as db:
        seed_pool_maps(db)
        if skill is not None:
            player = db.get(Player, pid)
            for a in player.attributes:
                a.base = float(skill)
            db.commit()
    return pid


def test_presets_respect_the_era(client):
    pid = _career(client, start="2010-03-01")
    presets = {p["key"]: p for p in client.get(f"/api/players/{pid}/presets").json()}
    assert presets["farm"]["available"]
    assert not presets["doubletime"]["available"]  # DT practice isn't a thing in 2010
    assert client.post(f"/api/players/{pid}/sessions/auto", json={"preset": "doubletime", "hours": 1}).status_code == 409
    assert client.post(f"/api/players/{pid}/sessions/auto", json={"preset": "nope", "hours": 1}).status_code == 422


def test_warmup_picks_easier_maps_than_push(client):
    pid = _career(client, skill=60)
    with SessionLocal() as db:
        player = db.get(Player, pid)

        def mean_stars(key):
            maps = autoplay.select_maps(db, player, autoplay.PRESETS[key], 6, random.Random(1))
            return sum(m.stars for m in maps) / len(maps)

        assert mean_stars("warmup") < mean_stars("farm") < mean_stars("push")


def test_auto_session_fills_the_hours_and_trains(client):
    pid = _career(client, skill=40)
    resp = client.post(f"/api/players/{pid}/sessions/auto", json={"preset": "farm", "hours": 1.5})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["plays"]) >= 3
    # Planned from the index lengths (~1.5h); the fixture .osu files are much shorter than that.
    assert sum(len(p["attempts"]) for p in data["plays"]) >= 6
    assert data["player"]["in_game_date"] == "2016-10-16"
    assert data["deltas"]  # an hour and a half of playing moves your skills
    assert all(p["mods"] == "NM" for p in data["plays"])
    hd = client.post(f"/api/players/{pid}/sessions/auto", json={"preset": "hidden", "hours": 0.5}).json()
    assert all(p["mods"] == "HD" for p in hd["plays"])


def test_map_playing_drills_set_real_scores(client):
    pid = _career(client, skill=40)
    trained = client.post(f"/api/players/{pid}/train",
                          json={"drill": "ranked_pack_grind", "hours_per_day": 4, "days": 3}).json()
    assert trained["days"] == 3
    assert trained["scores"], "ranked pack grinding should set scores"
    profile = client.get(f"/api/players/{pid}").json()
    assert profile["play_count"] >= len(trained["scores"])

    practice = client.post(f"/api/players/{pid}/train",
                           json={"drill": "stream_practice", "hours_per_day": 3, "days": 2}).json()
    assert practice["scores"] == []  # unranked practice maps don't give pp
