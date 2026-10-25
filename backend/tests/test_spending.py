from datetime import date

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.engine import spending as S
from app.models import Player, Team, TeamMember, Tournament
from app.services import life, spending, story


def career(client, start="2014-03-03", age=20, occupation=None, **extra):
    body = dict(name="Buyer", country="DE", start_date=start, seed=5, age=age, **extra)
    if occupation:
        body["occupation"] = occupation
    return client.post("/api/players", json=body).json()["id"]


def money(pid, amount):
    with SessionLocal() as db:
        db.get(Player, pid).money = amount
        db.commit()


def shop(client, pid, lang="en"):
    r = client.get(f"/api/players/{pid}/spending", params={"lang": lang})
    assert r.status_code == 200, r.text
    return r.json()


def card(client, pid, key, lang="en"):
    return next(i for c in shop(client, pid, lang)["categories"] for i in c["items"] if i["key"] == key)


def buy(client, pid, key, **body):
    return client.post(f"/api/players/{pid}/spending/{key}/buy", json=body)


def test_catalogue_is_complete_and_bilingual():
    assert len(S.CATALOG) >= 25
    assert {i.category for i in S.CATALOG} == set(S.CATEGORIES)
    for i in S.CATALOG:
        assert all(i.name) and all(i.desc) and all(i.perk), i.key
        assert i.kind in ("one_off", "timed", "sub", "owned") and i.price >= 0
        if i.kind in ("timed", "sub", "owned") and not i.handler:
            assert i.mods, i.key
    assert {c.kind for c in S.CATALOG} == {"one_off", "timed", "sub", "owned"}


def test_prices_follow_the_era_and_your_means():
    item = S.BY_KEY["gym"]
    assert S.era_factor(date(2008, 1, 1)) == 1.0 and 1.55 <= S.era_factor(date(2024, 12, 1)) <= 1.6
    student = S.price_on(item, date(2014, 1, 1), "school")
    pro = S.price_on(item, date(2014, 1, 1), "pro")
    assert pro > 2.5 * student
    assert S.price_on(item, date(2023, 1, 1), "work") > S.price_on(item, date(2009, 1, 1), "work")
    lan = S.BY_KEY["lan_trip"]
    assert S.price_on(lan, date(2014, 1, 1), "work", "OC") > S.price_on(lan, date(2014, 1, 1), "work", "EU")


def test_shop_lists_status_reasons_and_translations(client):
    pid = career(client, start="2009-03-03")
    en, ru = card(client, pid, "psychologist"), card(client, pid, "psychologist", "ru")
    assert en["status"] == "locked" and "2011" in en["reason"] and "2011" in ru["reason"] and en["name"] != ru["name"]
    assert card(client, pid, "supporter")["status"] == "available"
    assert [c["key"] for c in card(client, pid, "coach_session")["choices"]] and card(client, pid, "gym")["kind"] == "sub"
    assert card(client, pid, "stream_kit")["status"] == "locked"  # streaming doesn't exist


def test_buying_needs_money_and_charges_the_ledger(client):
    pid = career(client, start="2014-03-03", occupation="work")
    money(pid, 5)
    r = buy(client, pid, "massage")
    assert r.status_code == 409 and "costs" in r.json()["detail"]
    money(pid, 500)
    r = buy(client, pid, "massage")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["price"] > 0 and out["applied"].get("fatigue") is not None
    with SessionLocal() as db:
        p = db.get(Player, pid)
        assert round(p.money, 2) == round(500 - out["price"], 2)
        assert story.get(p, "ledger")["2014-03"]["services"] == -out["price"]
    assert card(client, pid, "massage")["status"] == "cooldown" and buy(client, pid, "massage").status_code == 409


def test_coach_session_boosts_learning_in_the_chosen_group_only(client):
    pid = career(client, start="2014-03-03", occupation="work")
    money(pid, 900)
    assert buy(client, pid, "coach_session").status_code == 422  # a group must be chosen
    assert buy(client, pid, "coach_session", choice="aim").status_code == 200
    assert buy(client, pid, "coach_session", choice="aim").status_code == 409  # no stacking while it runs
    with SessionLocal() as db:
        p = db.get(Player, pid)
        assert story.mod_product(p, "learn_aim") == pytest.approx(1.4)
        assert story.mod_product(p, "learn_reading") == 1.0
    def gain(buyer_choice):
        other = career(client, start="2014-03-03", occupation="work")  # same seed: identical talent and daily noise
        money(other, 900)
        if buyer_choice:
            assert buy(client, other, "coach_session", choice=buyer_choice).status_code == 200
        r = client.post(f"/api/players/{other}/train", json={"drill": "tech_maps", "hours_per_day": 3, "days": 5})
        assert r.status_code == 200, r.text
        return r.json()["deltas"]

    coached, plain, wrong = gain("technical"), gain(None), gain("aim")
    assert coached["slider_velocity"] > 1.25 * plain["slider_velocity"]
    assert wrong["slider_velocity"] == pytest.approx(plain["slider_velocity"], rel=0.02)  # a coach for another group does nothing


def test_subscriptions_pay_monthly_and_cancel_when_you_cannot(client):
    pid = career(client, start="2014-03-03", occupation="work")
    money(pid, 1000)
    assert buy(client, pid, "gym").status_code == 200
    first = shop(client, pid)
    assert first["subscriptions"][0]["key"] == "gym" and first["monthly_total"] == first["subscriptions"][0]["price"]
    with SessionLocal() as db:
        p = db.get(Player, pid)
        assert story.mod_product(p, "injury") == pytest.approx(0.85) and story.mod_product(p, "recovery") == pytest.approx(1.12)
    client.post(f"/api/players/{pid}/rest", json={"days": 40, "physio": False})
    after = shop(client, pid)
    assert after["subscriptions"][0]["months"] >= 2
    with SessionLocal() as db:
        assert story.get(db.get(Player, pid), "ledger")
    # now the money runs out
    money(pid, -5000)
    client.post(f"/api/players/{pid}/rest", json={"days": 35, "physio": False})
    assert shop(client, pid)["subscriptions"] == []
    with SessionLocal() as db:
        assert story.mod_product(db.get(Player, pid), "injury") == 1.0  # the perks left with the subscription


def test_cancel_removes_the_perks(client):
    pid = career(client, start="2014-03-03", occupation="work")
    money(pid, 500)
    buy(client, pid, "gym")
    assert client.post(f"/api/players/{pid}/spending/gym/cancel").status_code == 200
    assert client.post(f"/api/players/{pid}/spending/gym/cancel").status_code == 404
    with SessionLocal() as db:
        assert story.mod_product(db.get(Player, pid), "injury") == 1.0


def test_owned_perks_are_forever_and_stack_with_limits(client):
    pid = career(client, start="2014-03-03", occupation="work")
    money(pid, 3000)
    for key in ("wrist_rest", "ups", "eye_care", "headphones"):
        assert buy(client, pid, key).status_code == 200
    assert buy(client, pid, "wrist_rest").status_code == 409
    with SessionLocal() as db:
        p = db.get(Player, pid)
        assert story.mod_product(p, "injury") == pytest.approx(0.92)
        assert story.skill_multipliers(p)["visual_endurance"] == pytest.approx(1.08)
    client.post(f"/api/players/{pid}/rest", json={"days": 400, "physio": False})
    with SessionLocal() as db:
        assert story.mod_product(db.get(Player, pid), "injury") == pytest.approx(0.92)
    for key in ("gym", "meal_plan"):
        buy(client, pid, key)
    with SessionLocal() as db:
        assert story.mod_product(db.get(Player, pid), "recovery") <= 1.35


def test_perks_reach_the_simulation(client):
    from app.engine import simulation
    from app.services import condition

    pid = career(client, start="2014-03-03", occupation="work")
    money(pid, 3000)
    with SessionLocal() as db:
        p = db.get(Player, pid)
        before = condition.play_skills(db, p)["visual_endurance"]
        risk_before = simulation._risk_multiplier(p, {a.key: a for a in p.attributes}, simulation.DayPlan())
    buy(client, pid, "eye_care")
    buy(client, pid, "wrist_rest")
    with SessionLocal() as db:
        p = db.get(Player, pid)
        assert condition.play_skills(db, p)["visual_endurance"] > before * 1.07
        assert simulation._risk_multiplier(p, {a.key: a for a in p.attributes}, simulation.DayPlan()) < risk_before * 0.95


def test_health_items_heal_and_the_vacation_takes_you_off_the_computer(client):
    pid = career(client, start="2014-03-03", occupation="work")
    money(pid, 2000)
    with SessionLocal() as db:
        p = db.get(Player, pid)
        p.injury, p.fatigue = "minor_strain", 60.0
        db.commit()
    assert buy(client, pid, "massage").json()["extra"].get("healed") is True
    with SessionLocal() as db:
        p = db.get(Player, pid)
        assert p.injury == "healthy" and p.fatigue <= 35
    assert buy(client, pid, "vacation").status_code == 200
    with SessionLocal() as db:
        p = db.get(Player, pid)
        assert life.forced_rest(p, p.in_game_date) is not None
    r = client.post(f"/api/players/{pid}/train", json={"drill": "ranked_pack_grind", "hours_per_day": 2, "days": 1})
    assert r.status_code in (409, 422)


def test_insurance_makes_physio_cheaper(client):
    from app.services import condition

    pid = career(client, start="2014-03-03", occupation="work", age=24)
    money(pid, 1000)
    with SessionLocal() as db:
        p = db.get(Player, pid)
        m0 = p.money
        condition.pay_physio(p, 10)
        full = m0 - p.money
        db.rollback()
    buy(client, pid, "medical_insurance")
    with SessionLocal() as db:
        p = db.get(Player, pid)
        m0 = p.money
        condition.pay_physio(p, 10)
        assert m0 - p.money == pytest.approx(0.4 * full)
        db.rollback()


def test_maintenance_consumables_reduce_wear(client):
    pid = career(client, start="2014-03-03", occupation="work")
    money(pid, 500)
    with SessionLocal() as db:
        p = db.get(Player, pid)
        story.put(p, "wear", {"mouse": 0.6, "keyboard": 0.7})
        db.commit()
    assert buy(client, pid, "skates").status_code == 200
    assert buy(client, pid, "switches").status_code == 200
    with SessionLocal() as db:
        wear = story.get(db.get(Player, pid), "wear")
        assert wear["mouse"] == pytest.approx(0.35) and wear["keyboard"] == pytest.approx(0.2)


def test_internet_plan_uses_the_existing_upgrade(client):
    pid = career(client, start="2014-03-03", occupation="work")
    money(pid, 800)
    a = card(client, pid, "internet_plan")
    assert a["price"] > 0 and buy(client, pid, "internet_plan").status_code == 200
    with SessionLocal() as db:
        assert story.get(db.get(Player, pid), "isp_level") == 1
    assert buy(client, pid, "internet_plan").status_code == 200
    assert card(client, pid, "internet_plan")["status"] == "owned"  # maxed out after two levels


def test_coffee_boosts_now_and_crashes_tomorrow(client):
    pid = career(client, start="2014-03-03", occupation="work")
    money(pid, 100)
    assert buy(client, pid, "coffee").status_code == 200
    with SessionLocal() as db:
        p = db.get(Player, pid)
        assert story.mod_product(p, "play") > 1.0
        crash_day = date.fromisoformat("2014-03-04")
        assert story.mod_product(p, "play", crash_day) < 1.0 and story.mod_product(p, "recovery", crash_day) < 1.0


def test_requirements_team_tournament_streaming_rank(client):
    pid = career(client, start="2014-03-03", occupation="work")
    money(pid, 3000)
    assert buy(client, pid, "bootcamp").status_code == 409  # no team
    assert buy(client, pid, "lan_trip").status_code == 409  # nothing registered
    assert buy(client, pid, "agent").status_code == 409  # unranked
    assert "followers" in card(client, pid, "clip_editor")["reason"].lower() or card(client, pid, "clip_editor")["status"] == "locked"
    assert buy(client, pid, "host_tournament").status_code == 409  # nobody knows you yet
    with SessionLocal() as db:
        p = db.get(Player, pid)
        p.followers, p.global_rank = 400, 800
        db.commit()
    assert buy(client, pid, "agent").status_code == 200
    assert buy(client, pid, "clip_editor").status_code == 200
    with SessionLocal() as db:
        assert story.mod_product(db.get(Player, pid), "income") == pytest.approx(1.2)
        assert story.mod_product(db.get(Player, pid), "followers_mult") == pytest.approx(1.25)


def test_hosting_a_tournament_makes_news_and_reputation(client):
    from app.models import ForumThread
    from app.services import integrity

    pid = career(client, start="2014-03-03", occupation="work")
    money(pid, 3000)
    with SessionLocal() as db:
        p = db.get(Player, pid)
        p.followers = 100
        before = integrity.reputation(p)
        db.commit()
    out = buy(client, pid, "host_tournament").json()
    assert out["applied"]["followers"] == 60
    with SessionLocal() as db:
        p = db.get(Player, pid)
        assert integrity.reputation(p) > before
        assert db.query(ForumThread).filter_by(player_id=pid, kind="news").count() >= 1
        assert story.get(p, "spend_stats")["tournaments_hosted"] == 1
    assert buy(client, pid, "host_tournament").status_code == 409  # cooldown


def test_lan_trip_for_a_registered_tournament_and_bootcamp_with_a_team(client):
    pid = career(client, start="2014-03-03", occupation="work")
    money(pid, 5000)
    with SessionLocal() as db:
        p = db.get(Player, pid)
        t = db.scalars(select(Tournament).where(Tournament.player_id == pid, Tournament.tier == "open")
                       .order_by(Tournament.start_date)).first()
        t.user_registered = True
        t.start_date = date(2014, 3, 20)
        team = Team(player_id=pid, name="Squad", tag="SQD", founded_on=date(2014, 1, 1), status="active", chemistry=40)
        team.members = [TeamMember(npc_id=1, joined_on=date(2014, 1, 1)), TeamMember(npc_id=2, joined_on=date(2014, 1, 1))]
        db.add(team)
        db.commit()
    lan = buy(client, pid, "lan_trip")
    assert lan.status_code == 200, lan.text
    assert lan.json()["extra"]["tournament_id"]
    assert buy(client, pid, "lan_trip").status_code == 409  # same tournament, and on cooldown
    camp = buy(client, pid, "bootcamp")
    assert camp.status_code == 200, camp.text
    with SessionLocal() as db:
        assert db.query(Team).filter_by(player_id=pid).one().chemistry == pytest.approx(48)
        p = db.get(Player, pid)
        assert story.skill_multipliers(p)["clutch"] > 1.05
        stats = story.get(p, "spend_stats")
        assert stats["lan_visits"] == 1


def test_spending_achievements(client):
    pid = career(client, start="2014-03-03", occupation="work")
    money(pid, 2000)
    buy(client, pid, "coach_session", choice="reading")
    client.post(f"/api/players/{pid}/rest", json={"days": 3, "physio": False})
    legacy = client.get(f"/api/players/{pid}/legacy").json()
    assert "coaching_sessions_1" in [a["key"] for a in legacy["achievements"]["unlocked"]]


def test_subscription_months_unlock_the_routine_medal():
    from app.engine import achievements as AC

    medal = AC.BY_KEY["sub_months_max_12"]
    assert not medal.unlocked(AC.Snapshot(sub_months_max=11)) and medal.unlocked(AC.Snapshot(sub_months_max=12))
