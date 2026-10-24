"""A two-year career on a scripted routine, checking invariants every step.

Catches the bugs that only show up after many calendar actions: drifting values, crashes in rare
branches (injuries, era changes, tournaments, rivals), runaway news.
"""

import math
from collections import Counter

import pytest

from app.db import SessionLocal
from app.models import Player
from tests.conftest import seed_pool_maps

ROUTINE = [
    ("train", {"drill": "ranked_pack_grind", "hours_per_day": 3, "days": 5}),
    ("session", {"preset": "farm", "hours": 3}),
    ("train", {"drill": "tech_maps", "hours_per_day": 2, "days": 3}),
    ("session", {"preset": "push", "hours": 2}),
    ("train", {"drill": "watch_replays", "hours_per_day": 2, "days": 2}),
    ("rest", {"days": 2}),
    ("train", {"drill": "jump_farm", "hours_per_day": 4, "days": 5}),
    ("rest", {"days": 3, "physio": True}),
]


def _check_invariants(profile: dict) -> None:
    for group in profile["attributes"]:
        assert 1 <= group["value"] <= 115, group
        for sub in group["subs"]:
            assert 1 <= sub["value"] <= 115 and sub["cap"] <= 115, sub
            assert 0 <= sub["rust"] <= 5 and sub["plateau"] >= 0
    c = profile["conditions"]
    assert 0 <= c["fatigue"] <= 100 and 0 <= c["motivation"] <= 100 and 0 <= c["morale"] <= 100
    assert -2.5 <= profile["form"] <= 2.5
    life = profile["life"]
    assert math.isfinite(life["money"]) and life["followers"] >= 0
    assert 0 <= life["style_adaptation"] <= 1
    assert profile["total_pp"] >= 0 and math.isfinite(profile["total_pp"])


@pytest.mark.slow
def test_two_year_career_stays_sane(client):
    pid = client.post("/api/players", json={"name": "Marathon", "country": "PL", "start_date": "2015-09-01",
                                             "seed": 99, "age": 16}).json()["id"]
    with SessionLocal() as db:
        seed_pool_maps(db, n=60)
        db.get(Player, pid).money = 2000  # enough for physio along the way

    statuses = Counter()
    profile = client.get(f"/api/players/{pid}").json()
    step = 0
    while profile["in_game_date"] < "2017-09-01" and step < 400:
        kind, body = ROUTINE[step % len(ROUTINE)]
        step += 1
        listing = client.get(f"/api/players/{pid}/tournaments").json()
        if listing["pending_match"] and listing["pending_match"]["due"] <= listing["date"]:
            m = listing["pending_match"]
            resp = client.post(f"/api/players/{pid}/tournaments/{listing['pending_tournament_id']}/matches/{m['id']}/play")
            statuses[f"match {resp.status_code}"] += 1
            assert resp.status_code == 200, resp.text
        else:
            for t in listing["tournaments"]:
                if t["can_register"]:
                    client.post(f"/api/players/{pid}/tournaments/{t['id']}/register")
            if kind == "train":
                resp = client.post(f"/api/players/{pid}/train", json=body)
            elif kind == "session":
                resp = client.post(f"/api/players/{pid}/sessions/auto", json=body)
            else:
                resp = client.post(f"/api/players/{pid}/rest", json=body)
            statuses[f"{kind} {resp.status_code}"] += 1
            # 409/422 are legitimate refusals (hiatus, free time, match day); anything else is a bug.
            assert resp.status_code in (200, 409, 422), resp.text
        profile = client.get(f"/api/players/{pid}").json()
        _check_invariants(profile)

    assert profile["in_game_date"] >= "2017-09-01", statuses
    assert profile["overall"] > 20  # two years of practice should show
    assert profile["play_count"] > 20, statuses
    news = client.get(f"/api/players/{pid}/news", params={"limit": 200}).json()
    assert len(news) > 20
    threads = client.get(f"/api/players/{pid}/forum", params={"limit": 100}).json()
    # The beginner rarely makes the front page; fictional NPC record posts now share the feed.
    assert sum(1 for t in threads if t["kind"] == "scorepost" and t["title"].startswith('Marathon |')) <= 3
    from app.models import WorldEvent, MapScore
    with SessionLocal() as db:
        records = db.query(WorldEvent).filter_by(player_id=pid, type='NPC_SCORE_RECORD').all()
        assert records
        for record in records:
            saved = db.get(MapScore, record.data['score_id'])
            assert saved is not None and saved.beatmap_id == record.data['beatmap_id']
            assert saved.set_on == record.date and saved.record
