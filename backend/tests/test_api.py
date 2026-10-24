import pytest

from tests.conftest import FIXTURE_BEATMAP_ID, FIXTURE_SET_ID


def _create_player(client, **overrides):
    body = {"name": "User", "country": "ru", "start_date": "2016-10-15", **overrides}
    resp = client.post("/api/players", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_pp_calculate_endpoint(client):
    resp = client.post(
        "/api/pp/calculate", json={"beatmap_id": FIXTURE_BEATMAP_ID, "mods": "hddt", "accuracy": 98}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["mods"] == "HDDT"
    assert data["pp"] > 0
    assert data["beatmap"]["title"] == "Test Song"
    assert data["beatmap"]["beatmapset_id"] == FIXTURE_SET_ID
    assert data["beatmap"]["preview_url"] == f"https://b.ppy.sh/preview/{FIXTURE_SET_ID}.mp3"


def test_pp_calculate_rejects_bad_mods_and_combo(client):
    bad_mods = client.post("/api/pp/calculate", json={"beatmap_id": FIXTURE_BEATMAP_ID, "mods": "EZHR"})
    assert bad_mods.status_code == 422
    bad_combo = client.post("/api/pp/calculate", json={"beatmap_id": FIXTURE_BEATMAP_ID, "combo": 9999})
    assert bad_combo.status_code == 422


def test_create_and_get_player(client):
    created = _create_player(client)
    assert created["country"] == "RU"
    assert created["in_game_date"] == "2016-10-15"
    assert created["total_pp"] == 0
    assert created["global_rank"] is None

    fetched = client.get(f"/api/players/{created['id']}").json()
    assert fetched["name"] == "User"
    assert client.get("/api/players").json()[0]["id"] == created["id"]


def test_start_date_out_of_range(client):
    resp = client.post("/api/players", json={"name": "x", "start_date": "2005-01-01"})
    assert resp.status_code == 422


def test_score_submission_updates_profile(client):
    pid = _create_player(client)["id"]

    first = client.post(
        f"/api/players/{pid}/scores", json={"beatmap_id": FIXTURE_BEATMAP_ID, "accuracy": 97}
    ).json()
    assert first["is_new_top_play"] is True
    assert first["top_play_position"] == 1
    assert first["pp_gained"] == pytest.approx(first["score"]["pp"])
    assert first["player"]["global_rank"] is not None
    assert first["player"]["previous_rank"] is None

    # A worse score on the same map is stored but doesn't count.
    worse = client.post(
        f"/api/players/{pid}/scores",
        json={"beatmap_id": FIXTURE_BEATMAP_ID, "accuracy": 90, "misses": 3},
    ).json()
    assert worse["is_new_top_play"] is False
    assert worse["pp_gained"] == pytest.approx(0)

    # A second map is weighted at 0.95 behind the better play.
    second = client.post(
        f"/api/players/{pid}/scores",
        json={"beatmap_id": FIXTURE_BEATMAP_ID + 1, "mods": "HD", "accuracy": 99},
    ).json()
    assert second["is_new_top_play"] is True

    profile = client.get(f"/api/players/{pid}").json()
    assert profile["play_count"] == 3
    assert len(profile["top_plays"]) == 2
    top = sorted((p["pp"] for p in profile["top_plays"]), reverse=True)
    assert profile["total_pp"] == pytest.approx(top[0] + top[1] * 0.95)
    assert profile["previous_rank"] == first["player"]["global_rank"]
    assert profile["global_rank"] <= profile["previous_rank"]


def test_submit_to_missing_player(client):
    resp = client.post("/api/players/999/scores", json={"beatmap_id": FIXTURE_BEATMAP_ID, "accuracy": 99})
    assert resp.status_code == 404


def test_new_career_has_attribute_hierarchy(client):
    p = _create_player(client, seed=42)
    assert len(p["attributes"]) == 6
    assert sum(len(g["subs"]) for g in p["attributes"]) == 21
    assert p["era"] == "farm"
    assert p["injury"]["state"] == "healthy"
    again = _create_player(client, seed=42)
    assert again["attributes"] == p["attributes"]


def test_drills_reflect_era(client):
    pid = _create_player(client, start_date="2009-06-01")["id"]
    drills = {d["key"]: d for d in client.get(f"/api/players/{pid}/drills").json()}
    assert drills["ranked_pack_grind"]["available"] is True
    assert drills["jump_farm"]["available"] is False

    resp = client.post(f"/api/players/{pid}/train", json={"drill": "jump_farm", "hours_per_day": 4, "days": 3})
    assert resp.status_code == 409
    resp = client.post(f"/api/players/{pid}/train", json={"drill": "nope", "hours_per_day": 4, "days": 3})
    assert resp.status_code == 422


def test_train_and_rest_advance_calendar(client):
    pid = _create_player(client)["id"]
    trained = client.post(
        f"/api/players/{pid}/train", json={"drill": "jump_farm", "hours_per_day": 4, "days": 7}
    )
    assert trained.status_code == 200, trained.text
    data = trained.json()
    assert data["start_date"] == "2016-10-15"
    assert data["end_date"] == "2016-10-22"
    assert data["deltas"]["snap_aim"] > 0
    assert data["player"]["in_game_date"] == "2016-10-22"

    rested = client.post(f"/api/players/{pid}/rest", json={"days": 20, "physio": False}).json()
    assert rested["end_date"] == "2016-11-11"
    assert any(e["type"] == "RUST" for e in rested["events"])
    assert client.get(f"/api/players/{pid}").json()["in_game_date"] == "2016-11-11"
