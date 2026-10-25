from datetime import date, timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import LifeEvent, Player, Tournament
from app.services import notifications
from tests.conftest import FIXTURE_BEATMAP_ID, seed_pool_maps


def career(client, start="2016-01-01", **extra):
    body = dict(name="Notif", country="RU", start_date=start, seed=7, age=17, **extra)
    return client.post("/api/players", json=body).json()["id"]


def feed(client, pid, lang="en"):
    r = client.get(f"/api/players/{pid}/notifications", params={"lang": lang})
    assert r.status_code == 200, r.text
    return r.json()


def test_open_registrations_are_announced_once_with_a_register_action(client):
    pid = career(client)
    client.post(f"/api/players/{pid}/scores", json={"beatmap_id": FIXTURE_BEATMAP_ID, "accuracy": 97})
    with SessionLocal() as db:
        player = db.get(Player, pid)
        rank = player.global_rank
        today = player.in_game_date
        t = Tournament(player_id=pid, template="test", name="Test Open", tier="open", rank_min=1, rank_max=10_000_000,
                       size=32, team_size=1, registration_opens=today - timedelta(days=2), start_date=today + timedelta(days=10),
                       base_stars=5.0, status="upcoming", user_registered=False, pools={}, winner_entry_id=None)
        db.add(t)
        db.commit()
        tid = t.id
    assert rank
    items = feed(client, pid)
    regs = [i for i in items if i["kind"] == "registration" and i["action"]["tournament_id"] == tid]
    assert [i["id"] for i in regs] == [f"reg:{tid}:open"]
    assert regs[0]["action"]["type"] == "register" and regs[0]["tab"] == "tournaments"
    assert len({i["id"] for i in items}) == len(items)  # stable, unique ids
    assert feed(client, pid) == items  # nothing changes between two polls

    client.post(f"/api/players/{pid}/rest", json={"days": 8, "physio": False})
    closing = [i for i in feed(client, pid) if i["id"] == f"reg:{tid}:closing"]
    assert closing, "a reminder a few days before registration closes"

    assert client.post(f"/api/players/{pid}/tournaments/{tid}/register").status_code == 200
    assert not [i for i in feed(client, pid) if i["kind"] == "registration" and i["action"]["tournament_id"] == tid]


def test_top_plays_and_pending_decisions_show_up(client):
    pid = career(client)
    client.post(f"/api/players/{pid}/scores", json={"beatmap_id": FIXTURE_BEATMAP_ID, "accuracy": 98})
    with SessionLocal() as db:
        db.add(LifeEvent(player_id=pid, key="friends_hangout", category="family", title="Friends invite you out", body="b",
                         created_on=date(2016, 1, 1), expires_on=date(2016, 1, 8), status="pending", options=[], data={}))
        db.commit()
    items = feed(client, pid)
    kinds = {i["kind"] for i in items}
    assert {"top_play", "decision"} <= kinds
    ru = feed(client, pid, "ru")
    assert any(i["message"].startswith("Нужно решение") for i in ru)
    assert any(i["message"].startswith("Новый топ-плей") for i in ru)


def test_ineligible_and_owc_tournaments_are_not_offered():
    with SessionLocal() as db:
        from app.engine import simulation

        player = simulation.new_career("T", "RU", date(2016, 3, 1), 3, date(1999, 1, 1))
        db.add(player)
        db.flush()
        today = player.in_game_date
        for name, tier, lo, hi in (("OWC", "owc", 1, 10**7), ("Top 500", "major", 1, 500)):
            db.add(Tournament(player_id=player.id, template=name, name=name, tier=tier, rank_min=lo, rank_max=hi, size=32,
                              team_size=1, registration_opens=today - timedelta(days=1), start_date=today + timedelta(days=9),
                              base_stars=5.0, status="upcoming", user_registered=False, pools={}, winner_entry_id=None))
        db.flush()
        assert notifications.registrations(db, player) == []
        db.rollback()


def test_session_history_remembers_the_preset_for_play_again(client):
    pid = career(client, start="2016-10-15")
    with SessionLocal() as db:
        seed_pool_maps(db)
        player = db.get(Player, pid)
        for a in player.attributes:
            a.base = 40.0
        db.commit()
    auto = client.post(f"/api/players/{pid}/sessions/auto", json={"preset": "farm", "hours": 0.5})
    assert auto.status_code == 200, auto.text
    history = client.get(f"/api/players/{pid}/sessions/history").json()
    assert history[0]["preset"] == "farm" and history[0]["hours"] == 0.5 and history[0]["stream"] is False
    plays = [{"beatmap_id": p["beatmap"]["beatmap_id"], "mods": "" if p["mods"] == "NM" else p["mods"],
              "attempts": len(p["attempts"])} for p in history[0]["result"]["plays"]]
    again = client.post(f"/api/players/{pid}/sessions", json={"plays": plays})
    assert again.status_code == 200, again.text
    assert [p["beatmap"]["beatmap_id"] for p in again.json()["plays"]] == [p["beatmap_id"] for p in plays]
    assert client.get(f"/api/players/{pid}/sessions/history").json()[0]["preset"] is None  # a manual replay
