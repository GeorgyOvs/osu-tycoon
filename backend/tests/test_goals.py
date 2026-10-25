import random
from datetime import date

import pytest

from app.db import SessionLocal
from app.engine import goals as G
from app.models import Player, StoryArc
from app.services import goals as goals_service
from tests.conftest import FIXTURE_BEATMAP_ID


def new_player(client, seed=5, **extra):
    body = dict(name="Gal", country="RU", start_date="2016-03-01", seed=seed, age=16, **extra)
    r = client.post("/api/players", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def get_goals(client, pid, lang="en"):
    r = client.get(f"/api/players/{pid}/goals", params={"lang": lang})
    assert r.status_code == 200, r.text
    return r.json()


def test_new_career_gets_three_distinct_goals(client):
    pid = new_player(client)
    out = get_goals(client, pid)
    assert len(out["active"]) == 3
    assert len({g["key"] for g in out["active"]}) == 3
    assert "first_plays" in {g["key"] for g in out["active"]}
    assert all(0 <= g["progress"] <= 1 and g["deadline"] and g["title"] for g in out["active"])
    assert get_goals(client, pid) == out  # stable between looks


def test_russian_goal_text_is_complete(client):
    pid = new_player(client, seed=9)
    for g in get_goals(client, pid, "ru")["active"]:
        assert "{" not in g["title"] + g["description"]
        assert any("а" <= ch.lower() <= "я" for ch in g["title"])


def test_scoring_completes_first_plays_and_pays_the_reward(client):
    pid = new_player(client)
    before = client.get(f"/api/players/{pid}").json()
    for _ in range(3):
        r = client.post(f"/api/players/{pid}/scores", json={"beatmap_id": FIXTURE_BEATMAP_ID, "accuracy": 96})
        assert r.status_code == 200, r.text
    client.post(f"/api/players/{pid}/rest", json={"days": 1, "physio": False})
    out = get_goals(client, pid)
    done = [g for g in out["finished"] if g["key"] == "first_plays" and g["status"] == "done"]
    assert done and done[0]["reward"]["money"] > 0
    after = client.get(f"/api/players/{pid}").json()
    assert after["life"]["money"] > before["life"]["money"]
    assert len(out["active"]) == 3  # replaced


def test_dropping_a_goal_proposes_a_replacement(client):
    pid = new_player(client)
    first = get_goals(client, pid)["active"]
    r = client.post(f"/api/players/{pid}/goals/{first[0]['id']}/drop")
    assert r.status_code == 200
    out = r.json()
    assert first[0]["id"] not in {g["id"] for g in out["active"]}
    assert len(out["active"]) == 3
    assert client.post(f"/api/players/{pid}/goals/{first[0]['id']}/drop").status_code == 409
    assert client.post(f"/api/players/{pid}/goals/99999/drop").status_code == 404


def test_progress_is_monotone_in_rank_and_bounded():
    target = {"metric": "rank", "value": 1000, "start": 50000}
    kw = dict(total_pp=0, composites={}, followers=0, money=0, play_count=0, consecutive_days=0, best_streak=0,
              match_wins=0, owns_item=False, rival_rank=None)
    values = [G.progress(target, rank=r, **kw) for r in (None, 60000, 50000, 20000, 5000, 1500, 1000, 400)]
    assert values == sorted(values)
    assert values[0] == 0 and values[-1] == 1 and all(0 <= v <= 1 for v in values)
    assert G.next_rank_target(50000) == 25000 and G.next_rank_target(3) == 1


def test_proposals_depend_on_the_situation():
    ctx = G.GoalCtx(on=date(2016, 1, 1), rank=40000, total_pp=1500, pp_era=True, composites={"aim": 30, "tapping": 28, "reading": 20, "technical": 15, "mentality": 40, "physical": 50},
                    followers=0, money=50, play_count=40, streaming=False, consecutive_days=0, rival_name="Mrekk",
                    rival_rank=30000, item=("mx518", "Logitech MX518", 50.0), user_in_tournaments=True)
    seen = {G.propose(ctx, random.Random(i)).key for i in range(200)}
    assert {"rank", "pp", "group", "overtake_rival", "buy_gear", "match_wins"} <= seen
    assert "followers" not in seen and "first_plays" not in seen


def test_comeback_arc_follows_a_severe_injury():
    with SessionLocal() as db:
        from app.engine import simulation

        player = simulation.new_career("T", "RU", date(2016, 3, 1), 4, date(2000, 1, 1))
        player.global_rank = 12000
        db.add(player)
        db.flush()
        player.injury = simulation.SEVERE_RSI
        goals_service.tick(db, player, [])
        arcs = list(db.query(StoryArc).filter_by(player_id=player.id))
        assert [a.key for a in arcs] == ["comeback"]
        player.injury = simulation.HEALTHY
        player.in_game_date = date(2016, 6, 1)
        goals_service.tick(db, player, [])
        assert arcs[0].data["returned"] is True
        player.in_game_date = date(2016, 7, 1)
        player.global_rank = 9000
        goals_service.tick(db, player, [])
        assert arcs[0].status == "resolved"
        text = goals_service.present_arc(arcs[0], "ru")
        assert len(text["chapters"]) == 3 and "{" not in "".join(c["text"] for c in text["chapters"])
        assert text["title"] == "Возвращение"
        db.rollback()
