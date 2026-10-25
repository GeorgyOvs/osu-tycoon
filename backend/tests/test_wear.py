import pytest

from app.db import SessionLocal
from app.engine import life_events as LE
from app.engine import network, wear
from app.models import Player
from app.services import condition, setup, story


def new_player(client, seed=4, country="RU", start="2014-03-01", **extra):
    body = dict(name="Wear", country=country, start_date=start, seed=seed, age=17, **extra)
    return client.post("/api/players", json=body).json()["id"]


def get_setup(client, pid):
    r = client.get(f"/api/players/{pid}/setup")
    assert r.status_code == 200, r.text
    return r.json()


def by_cat(data):
    return {w["category"]: w for w in data["wear"]}


def test_wear_and_network_curves():
    mults = [wear.wear_multiplier(w / 10) for w in range(11)]
    assert mults == sorted(mults, reverse=True) and mults[0] == 1.0 and 0.94 < mults[-1] < 0.96
    assert wear.comfort_multiplier(1.0) > wear.comfort_multiplier(0.0)
    assert network.ping("EU", "AS", 2014) == network.ping("AS", "EU", 2014) > network.ping("EU", "EU", 2014)
    assert network.ping("EU", "AS", 2022) < network.ping("EU", "AS", 2014)  # regional servers and better routing
    assert network.ping("EU", "NA", 2014, isp_level=2) < network.ping("EU", "NA", 2014)
    assert network.pressure_factor(20) == 1.0 and 1.0 < network.pressure_factor(200) <= 1.2
    assert network.region("RU") == "EU" and network.region("KR") == "AS" and network.region("XX") == "EU"


def test_hours_wear_out_gear_and_settle_settings(client):
    pid = new_player(client)
    fresh = get_setup(client, pid)
    assert all(w["wear"] == 0 for w in fresh["wear"])
    for _ in range(6):
        client.post(f"/api/players/{pid}/train", json={"drill": "ranked_pack_grind", "hours_per_day": 5, "days": 5})
    worn = get_setup(client, pid)
    rows = by_cat(worn)
    assert rows["mouse"]["wear"] > 0.08 and rows["keyboard"]["wear"] > 0.08 and rows["tablet"]["wear"] == 0
    assert rows["mouse"]["penalty"] > 0 and rows["mouse"]["active"] and not rows["tablet"]["active"]
    assert worn["comfort"] > fresh["comfort"]


def test_worn_gear_lowers_play_skills(client):
    pid = new_player(client)
    with SessionLocal() as db:
        player = db.get(Player, pid)
        before = condition.play_skills(db, player)
        story.put(player, "wear", {"mouse": 1.0, "keyboard": 1.0})
        after = condition.play_skills(db, player)
    assert after["snap_aim"] < before["snap_aim"] and after["burst"] < before["burst"]
    assert after["rsi_resistance"] == before["rsi_resistance"]  # only aim and tapping suffer


def test_maintain_and_replace(client):
    pid = new_player(client)
    with SessionLocal() as db:
        player = db.get(Player, pid)
        story.put(player, "wear", {"mouse": 0.8})
        player.money = 100
        db.commit()
    r = client.post(f"/api/players/{pid}/setup/maintain", json={"category": "mouse"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert by_cat(data)["mouse"]["wear"] == pytest.approx(0.8 - wear.SERVICE_REMOVES) and data["money"] == 100 - wear.SERVICE_COST["mouse"]
    r = client.post(f"/api/players/{pid}/setup/replace", json={"category": "mouse"})
    assert r.status_code == 200 and by_cat(r.json())["mouse"]["wear"] == 0
    assert client.post(f"/api/players/{pid}/setup/maintain", json={"category": "chair"}).status_code == 422
    with SessionLocal() as db:
        player = db.get(Player, pid)
        player.money = 1
        db.commit()
    assert client.post(f"/api/players/{pid}/setup/maintain", json={"category": "keyboard"}).status_code == 409


def test_changing_gear_costs_comfort_and_buying_resets_wear(client):
    pid = new_player(client)
    with SessionLocal() as db:
        player = db.get(Player, pid)
        story.put(player, "comfort", 0.9)
        story.put(player, "wear", {"mouse": 0.7})
        player.money = 1000
        db.commit()
    shop = client.get(f"/api/players/{pid}/shop").json()["items"]
    mouse = next(i for i in shop if i["category"] == "mouse" and i["available"] and not i["owned"])
    assert client.post(f"/api/players/{pid}/shop/{mouse['key']}/buy").status_code == 200
    data = get_setup(client, pid)
    assert by_cat(data)["mouse"]["wear"] == 0
    assert data["comfort"] == pytest.approx(0.9 * wear.COMFORT_AFTER_GEAR_CHANGE, abs=0.01)


def test_isp_upgrades_cut_the_lobby_ping(client):
    pid = new_player(client, country="BR", start="2012-01-01")
    with SessionLocal() as db:
        player = db.get(Player, pid)
        player.money = 500
        db.commit()
    first = get_setup(client, pid)["network"]
    assert first["region"] == "SA" and first["isp_level"] == 0 and first["isp_price"]
    second = client.post(f"/api/players/{pid}/setup/isp").json()["network"]
    assert second["isp_level"] == 1 and second["lobby_ping"] < first["lobby_ping"]
    client.post(f"/api/players/{pid}/setup/isp")
    assert client.post(f"/api/players/{pid}/setup/isp").status_code == 409  # maxed out


def test_distance_makes_lobbies_less_useful(client):
    from app.engine.training import DRILLS
    from app.routers.career import _lobby_drill

    near = new_player(client, country="DE", start="2013-01-01")
    far = new_player(client, country="BR", start="2013-01-01", seed=5)
    with SessionLocal() as db:
        near_eff = _lobby_drill(db.get(Player, near), DRILLS["multiplayer_lobbies"]).efficiency(db.get(Player, near).in_game_date)
        far_eff = _lobby_drill(db.get(Player, far), DRILLS["multiplayer_lobbies"]).efficiency(db.get(Player, far).in_game_date)
    assert far_eff < near_eff <= DRILLS["multiplayer_lobbies"].efficiency(__import__("datetime").date(2013, 1, 1))


def test_peripheral_wear_event_needs_worn_gear():
    template = LE.BY_KEY["peripheral_wear"]
    base = dict(on=None, age=16, occupation="school", rank=None, money=0, followers=0, fatigue=0, motivation=70,
                injury="healthy", era="farm", year=2016, month=1, device="mouse", rival=None, in_exams=False,
                in_holidays=False, birthday=False, stuck=None, streaming=True)
    assert not template.when(LE.Ctx(**base, wear=0.05))
    assert template.when(LE.Ctx(**base, wear=0.5))
