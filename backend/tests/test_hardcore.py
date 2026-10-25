from datetime import date

from app.db import SessionLocal
from app.engine import simulation
from app.engine.training import DRILLS
from app.models import Player
from app.services import legacy, story


def new_player(client, **extra):
    body = dict(name="Iron", country="RU", start_date="2016-03-01", seed=12, age=17, **extra)
    r = client.post("/api/players", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_hardcore_flag_shows_up_as_a_trait_and_in_the_build(client):
    p = new_player(client, hardcore=True, realistic_economy=True)
    assert p["character_build"]["hardcore"] is True and p["character_build"]["economy"] == "realistic"
    assert "Хардкор" in p["traits"] and "Реалистичная экономика" in p["traits"]
    plain = new_player(client)
    assert "hardcore" not in plain["character_build"]


def test_hardcore_careers_need_a_typed_confirmation_to_delete(client):
    p = new_player(client, hardcore=True)
    assert client.delete(f"/api/players/{p['id']}").status_code == 409
    assert client.delete(f"/api/players/{p['id']}", params={"confirm": "wrong"}).status_code == 409
    assert client.delete(f"/api/players/{p['id']}", params={"confirm": "Iron"}).status_code == 204
    normal = new_player(client)
    assert client.delete(f"/api/players/{normal['id']}").status_code == 204


def test_injuries_are_harsher():
    def career(hard):
        p = simulation.new_career("T", "RU", date(2016, 1, 1), 5, date(2000, 1, 1))
        if hard:
            p.character_build = {"hardcore": True}
        return p

    plan = simulation.DayPlan(DRILLS["jump_farm"], 4)
    normal, hard = career(False), career(True)
    attrs_n, attrs_h = ({a.key: a for a in p.attributes} for p in (normal, hard))
    assert simulation._risk_multiplier(hard, attrs_h, plan) == 1.5 * simulation._risk_multiplier(normal, attrs_n, plan)


def test_months_in_the_red_end_a_hardcore_career(client):
    p = new_player(client, hardcore=True)
    pid = p["id"]
    with SessionLocal() as db:
        db.get(Player, pid).money = -1000.0
        db.commit()
    for _ in range(8):
        r = client.post(f"/api/players/{pid}/rest", json={"days": 14, "physio": False})
        assert r.status_code == 200
    out = client.get(f"/api/players/{pid}/legacy").json()
    assert out["status"]["retired"] and out["status"]["reason"] == "bankrupt" and out["status"]["hardcore"]
    assert any("hardcore" in line for line in out["epilogue"]["lines"])


def test_the_same_debt_does_not_end_a_normal_career(client):
    p = new_player(client)
    with SessionLocal() as db:
        db.get(Player, p["id"]).money = -1000.0
        db.commit()
    for _ in range(8):
        client.post(f"/api/players/{p['id']}/rest", json={"days": 14, "physio": False})
    assert client.get(f"/api/players/{p['id']}/legacy").json()["status"]["retired"] is False


def test_career_ending_injury_retires_a_hardcore_player():
    with SessionLocal() as db:
        player = simulation.new_career("T", "RU", date(2016, 1, 1), 5, date(2000, 1, 1))
        player.character_build = {"hardcore": True}
        db.add(player)
        db.flush()
        legacy.tick(db, player, [])
        for a in player.attributes:
            if a.key == "hand_stamina":
                a.cap -= legacy.FATAL_CAP_LOSS + 1
        player.in_game_date = date(2016, 1, 5)
        news: list = []
        legacy.tick(db, player, news)
        assert story.get(player, "retired")["reason"] == "injury"
        assert any(n.type == "CAREER_END" for n in news)
        db.rollback()
