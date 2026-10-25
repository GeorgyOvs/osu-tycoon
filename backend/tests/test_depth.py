from datetime import timedelta

import pytest

from app.db import SessionLocal
from app.engine import gear
from app.models import Player
from app.services import condition, familiarity, life
from tests.conftest import STREAM_BEATMAP_ID


def _career(client, start="2016-10-15", age=15, occupation=None, seed=6):
    body = {"name": "Depth", "country": "RU", "start_date": start, "seed": seed, "age": age}
    if occupation:
        body["occupation"] = occupation
    resp = client.post("/api/players", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- 1. map familiarity ---------------------------------------------------------------------


def test_familiarity_builds_with_replays_and_fades(client):
    pid = _career(client)["id"]
    with SessionLocal() as db:
        player = db.get(Player, pid)
        assert familiarity.level(db, player, 42) == 0
        for _ in range(10):
            familiarity.record_attempt(db, player, 42, 1.0)
        known = familiarity.level(db, player, 42)
        assert 0.7 < known < 0.85
        player.in_game_date += timedelta(days=45)
        assert familiarity.level(db, player, 42) == pytest.approx(known * familiarity.DAILY_RETENTION**45)


def test_familiar_maps_assess_better(client):
    pid = _career(client)["id"]
    fresh = client.get(f"/api/players/{pid}/assess/{STREAM_BEATMAP_ID}").json()
    with SessionLocal() as db:
        player = db.get(Player, pid)
        for _ in range(25):
            familiarity.record_attempt(db, player, STREAM_BEATMAP_ID, 1.0)
        db.commit()
    known = client.get(f"/api/players/{pid}/assess/{STREAM_BEATMAP_ID}").json()
    assert known["familiarity"] > 0.9
    assert known["peak_ratios"]["tapping"] < fresh["peak_ratios"]["tapping"]


# --- 2. gear and money ----------------------------------------------------------------------


def test_starter_kit_shop_and_monitor_cap(client):
    pid = _career(client, start="2014-03-01")["id"]
    shop = client.get(f"/api/players/{pid}/shop").json()
    items = {i["key"]: i for i in shop["items"]}
    assert all(items[k]["owned"] and items[k]["equipped"] for k in gear.STARTER_KIT)
    assert shop["money"] == 100 and shop["effects"]["ar_cap"] == 60
    assert not items["wooting_60he"]["available"]  # 2022 hardware

    assert client.post(f"/api/players/{pid}/shop/hz_144/buy").status_code == 409  # too expensive
    with SessionLocal() as db:
        db.get(Player, pid).money = 1000
        db.commit()
    bought = client.post(f"/api/players/{pid}/shop/hz_144/buy").json()
    assert bought["effects"]["ar_cap"] == 95 and bought["money"] == 720
    with SessionLocal() as db:
        player = db.get(Player, pid)
        for a in player.attributes:
            if a.key == "high_ar_reaction":
                a.base = 90
        assert condition.play_skills(db, player)["high_ar_reaction"] <= 95
        condition.equip(db, player, "lcd_60")
        assert condition.play_skills(db, player)["high_ar_reaction"] <= 60


def test_physio_costs_money(client):
    pid = _career(client)["id"]
    assert client.post(f"/api/players/{pid}/rest", json={"days": 2, "physio": True}).status_code == 200
    profile = client.get(f"/api/players/{pid}").json()
    allowance = life.WEEKLY_INCOME["school"]  # the two days include a Sunday
    assert profile["life"]["money"] == 100 - 2 * condition.PHYSIO_COST_PER_DAY + allowance
    assert client.post(f"/api/players/{pid}/rest", json={"days": 30, "physio": True}).status_code == 409


# --- 3. life ---------------------------------------------------------------------------------


def test_free_time_limits_and_sleep_debt(client):
    pid = _career(client, start="2016-10-17")["id"]  # a Monday in term time
    too_much = client.post(f"/api/players/{pid}/train", json={"drill": "tech_maps", "hours_per_day": 10, "days": 1})
    assert too_much.status_code == 422
    late = client.post(f"/api/players/{pid}/train", json={"drill": "tech_maps", "hours_per_day": 7, "days": 1}).json()
    assert any(e["type"] == "SLEEP_DEBT" for e in late["events"])


def test_income_age_and_milestones(client):
    p = _career(client, start="2016-06-01", age=17.95)
    assert p["life"]["occupation"] == "school" and p["life"]["age"] == pytest.approx(17.9, abs=0.1)
    resp = client.post(f"/api/players/{p['id']}/rest", json={"days": 30}).json()
    assert any(e["type"] == "BIRTHDAY" for e in resp["events"])
    after = client.get(f"/api/players/{p['id']}").json()["life"]
    assert after["occupation"] == "university"
    assert after["money"] > 100  # weekly allowance

    worker = _career(client, age=30, occupation="work", seed=8)
    with SessionLocal() as db:
        old, young = db.get(Player, worker["id"]), db.get(Player, p["id"])
        assert life.learning_multiplier(old) < life.learning_multiplier(young)
        assert life.reaction_multiplier(old) < 1.0


def test_occupation_changes(client):
    kid = _career(client, age=14)["id"]
    assert client.post(f"/api/players/{kid}/occupation", json={"occupation": "pro"}).status_code == 409
    adult = _career(client, age=20, seed=9)["id"]
    resp = client.post(f"/api/players/{adult}/occupation", json={"occupation": "pro"}).json()
    assert resp["life"]["free_hours_today"] == 14


# --- 4. playstyle ----------------------------------------------------------------------------


def test_switching_to_tablet_needs_one_and_takes_time(client):
    pid = _career(client, start="2014-03-01")["id"]
    assert client.post(f"/api/players/{pid}/playstyle", json={"input_device": "tablet"}).status_code == 409
    with SessionLocal() as db:
        player = db.get(Player, pid)
        player.money = 500
        condition.buy(db, player, "wacom_ctl480")
        before = condition.play_skills(db, player)["flow_aim"]
        db.commit()
    switched = client.post(f"/api/players/{pid}/playstyle", json={"input_device": "tablet"}).json()
    assert switched["life"]["input_device"] == "tablet"
    assert switched["life"]["style_adaptation"] == pytest.approx(condition.SWITCH_DEVICE)
    with SessionLocal() as db:
        player = db.get(Player, pid)
        assert condition.play_skills(db, player)["flow_aim"] < before  # awkward at first
        condition.progress_adaptation(player, 200)
        assert player.style_adaptation > 0.8


def test_singletap_has_a_burst_ceiling(client):
    pid = _career(client)["id"]
    with SessionLocal() as db:
        player = db.get(Player, pid)
        for a in player.attributes:
            if a.key in ("burst", "deathstream", "low_mid_bpm"):
                a.base = 90
        alt = condition.play_skills(db, player)
        player.tap_style = "singletap"
        single = condition.play_skills(db, player)
        assert single["burst"] <= condition.SINGLETAP_CAPS["burst"] < alt["burst"]
        assert single["low_mid_bpm"] > alt["low_mid_bpm"]


def test_gender_is_role_play_only_and_young_starts_have_less_time(client):
    a = _career(client, start="2016-10-17", seed=30, age=7)
    b = client.post("/api/players", json={"name": "G", "country": "RU", "start_date": "2016-10-17", "seed": 30,
                                          "age": 7, "gender": "female"}).json()
    assert b["life"]["gender"] == "female" and b["life"]["pronouns"] == "she/her"
    assert a["life"]["pronouns"] == "they/them"
    assert a["attributes"] == b["attributes"] and a["overall"] == b["overall"]  # same seed, no mechanical effect
    assert b["life"]["free_hours_today"] == life.CHILD_FREE_HOURS[0]  # a 7-year-old on a school day
    assert client.post("/api/players", json={"name": "x", "start_date": "2016-01-01", "age": 6}).status_code == 422



def test_gear_follows_the_calendar(client):
    from datetime import date

    pid = _career(client, start="2010-06-01")["id"]
    items = {i["key"]: i for i in client.get(f"/api/players/{pid}/shop").json()["items"]}
    assert items["crt"]["available"] and items["mx518"]["available"]
    assert not items["wacom_ctl480"]["available"] and not items["hz_144"]["available"]
    assert items["hz_120"]["price"] < items["hz_120"]["launch_price"]  # a year old: cheaper
    with SessionLocal() as db:
        player = db.get(Player, pid)
        player.money = 2000
        player.in_game_date = date(2015, 3, 1)
        db.commit()
    assert client.post(f"/api/players/{pid}/shop/crt/buy").status_code == 409  # discontinued in 2010
    item = gear.CATALOG["hz_144"]
    assert item.price_on(date(2013, 7, 1)) == 280 and item.price_on(date(2030, 1, 1)) == 168
    assert gear.CATALOG["wooting_60he"].is_new(date(2022, 3, 1))


def test_user_bans_are_honoured_in_every_pool_and_stage():
    import random

    from app.engine import match

    def run(pool_names, first_to, bans_per_side, wanted):
        pool = [match.Slot(n, 6.0, beatmap_id=i + 1) for i, n in enumerate(pool_names)]
        out = match.run_match(pool, first_to, lambda s: 0.0, lambda s, d: (500, 400, {}), random.Random(1),
                              bans_per_side=bans_per_side, prefs={"a": {"bans": wanted}})
        return out

    for pool_names in (match.SMALL_POOL, match.BIG_POOL):
        for first_to in (5, 6, 7):
            for per_side in (1, 2):
                out = run(pool_names, first_to, per_side, ["DT1", "HR1"])
                spare = len(pool_names) - 1 - (2 * first_to - 2)  # maps that may be banned and still leave a full match
                if spare <= 0:
                    assert not out.bans["a"] and not out.bans["b"]
                    continue
                assert out.bans["a"][0] == "DT1"  # the chosen slot is banned first, not the AI's pick
                if per_side == 2 and spare >= 3:
                    assert out.bans["a"][:2] == ["DT1", "HR1"]
                banned = set(out.bans["a"]) | set(out.bans["b"])
                assert not banned & {m.slot for m in out.maps}  # banned maps are never played


def test_equal_map_scores_are_not_awarded_to_side_a_by_default():
    import random

    from app.engine import match

    def play(slot, decisive):
        players = [{"side": "a", "accuracy": 98.0, "misses": 0}, {"side": "b", "accuracy": 98.54, "misses": 0}]
        return 1000, 1000, {"players": players}

    pool = [match.Slot(n, 6.0, beatmap_id=i + 1) for i, n in enumerate(match.SMALL_POOL)]
    out = match.run_match(pool, 3, lambda s: 0.0, play, random.Random(5))
    assert all(m.detail["tie"] == "accuracy" and m.winner == "b" for m in out.maps)  # higher accuracy decides
    assert out.winner == "b" and out.score_a == 0

    def identical(slot, decisive):
        return 500, 500, {"players": [{"side": "a", "accuracy": 98.5, "misses": 0}, {"side": "b", "accuracy": 98.5, "misses": 0}]}

    wins = {"a": 0, "b": 0}
    for seed in range(60):
        out = match.run_match(pool, 1, lambda s: 0.0, identical, random.Random(seed))
        assert out.maps[0].detail["tie"] == "sudden_death" and out.maps[0].detail["winner"] == out.maps[0].winner
        wins[out.maps[0].winner] += 1
    assert 15 <= wins["a"] <= 45  # a fair coin, not 'a always'
