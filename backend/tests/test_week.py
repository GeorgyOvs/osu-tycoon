import math

from app.db import SessionLocal
from app.models import Player
from app.engine import simulation
from tests.conftest import seed_pool_maps

WEEK = [
    {"type": "train", "drill": "tech_maps", "hours": 2},
    {"type": "train", "drill": "ranked_pack_grind", "hours": 3},
    {"type": "session", "preset": "farm", "hours": 2},
    {"type": "train", "drill": "watch_replays", "hours": 2},
    {"type": "rest"},
    {"type": "session", "preset": "push", "hours": 3},
    {"type": "rest", "physio": True},
]


def _career(client, start="2016-10-17"):
    pid = client.post("/api/players", json={"name": "Week", "country": "RU", "start_date": start, "seed": 8,
                                             "age": 16}).json()["id"]
    with SessionLocal() as db:
        seed_pool_maps(db, n=40)
    return pid


def test_a_planned_week_is_lived_day_by_day(client):
    pid = _career(client)
    resp = client.post(f"/api/players/{pid}/week", json={"days": WEEK})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["start_date"] == "2016-10-17" and data["end_date"] == "2016-10-24"
    assert [d["type"] for d in data["days"]] == [d["type"] for d in WEEK]
    assert all(d["ok"] for d in data["days"]), data["days"]
    assert data["deltas"] and data["stopped_early"] is None
    assert math.isfinite(data["money_change"])  # physio paid, allowance earned


def test_refused_days_become_rest_and_injuries_force_rest(client):
    pid = _career(client)
    plan = [{"type": "train", "drill": "tech_maps", "hours": 12}, {"type": "train", "drill": "tech_maps", "hours": 2}]
    data = client.post(f"/api/players/{pid}/week", json={"days": plan}).json()
    assert not data["days"][0]["ok"] and "rested instead" in data["days"][0]["summary"]
    assert data["end_date"] == "2016-10-19"

    with SessionLocal() as db:
        player = db.get(Player, pid)
        player.injury = simulation.SEVERE_RSI
        from datetime import timedelta
        player.injury_until = player.in_game_date + timedelta(days=30)
        db.commit()
    data = client.post(f"/api/players/{pid}/week", json={"days": WEEK[:3]}).json()
    assert all(d["summary"].startswith("forced rest") for d in data["days"])


def test_the_week_stops_for_a_match(client):
    pid = _career(client, start="2016-02-01")
    listing = client.get(f"/api/players/{pid}/tournaments").json()
    cup = next(t for t in listing["tournaments"] if t["name"] == "6 Digit Spring Cup 2016")
    client.post(f"/api/players/{pid}/rest", json={"days": 15})
    client.post(f"/api/players/{pid}/tournaments/{cup['id']}/register")
    client.post(f"/api/players/{pid}/rest", json={"days": 20})  # a few days before the start
    data = client.post(f"/api/players/{pid}/week", json={"days": [{"type": "rest"}] * 14}).json()
    assert data["stopped_early"] and "match" in data["stopped_early"]
    assert data["end_date"] == cup["start_date"]
