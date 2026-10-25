from datetime import date

import pytest

from app.db import SessionLocal
from app.engine import simulation
from app.models import Player
from app.services import economy, story


def new_player(client, **extra):
    body = dict(name="Eco", country="RU", start_date="2016-03-01", seed=8, age=extra.pop("age", 17), **extra)
    r = client.post("/api/players", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def rest(client, pid, days):
    r = client.post(f"/api/players/{pid}/rest", json={"days": days, "physio": False})
    assert r.status_code == 200, r.text
    return r.json()


def money(client, pid):
    return client.get(f"/api/players/{pid}").json()["life"]["money"]


def budget(client, pid):
    return client.get(f"/api/players/{pid}/legacy").json()["budget"]


def test_simple_economy_keeps_the_original_balance_but_still_has_a_ledger(client):
    pid = new_player(client)
    before = money(client, pid)
    rest(client, pid, 14)
    b = budget(client, pid)
    cats = {}
    for m in b["months"]:
        for k, v in m["categories"].items():
            cats[k] = cats.get(k, 0) + v
    assert b["realistic"] is False and cats["salary"] == 20  # two Sundays at $10, as before
    assert money(client, pid) == pytest.approx(before + sum(cats.values()))  # everything that moved is in the ledger


def test_realistic_economy_charges_living_costs_and_taxes(client):
    pid = new_player(client, age=25, occupation="work", realistic_economy=True)
    before = money(client, pid)
    rest(client, pid, 7)
    cats = {}
    for m in budget(client, pid)["months"]:
        for k, v in m["categories"].items():
            cats[k] = cats.get(k, 0) + v
    assert cats["tax"] == pytest.approx(-72) and cats["living"] == -120 and cats["salary"] == 360
    assert money(client, pid) - before == pytest.approx(sum(cats.values()))  # salary after tax, minus living costs


def test_university_pays_tuition_and_pro_runs_a_runway(client):
    uni = new_player(client, age=19, realistic_economy=True)
    assert client.get(f"/api/players/{uni}").json()["life"]["occupation"] == "university"
    rest(client, uni, 7)
    cats = budget(client, uni)["months"][-1]["categories"]
    assert cats["tuition"] == -18 and cats["living"] == -30
    runway = budget(client, uni)["runway"]
    assert runway["weekly_burn"] == pytest.approx(-32.0, abs=0.1) or runway["weekly_burn"] < 0  # a student nets money
    assert runway["weeks_left_pro"] is not None and runway["weeks_left_pro"] > 0


def test_winnings_are_taxed_only_in_realistic_careers():
    with SessionLocal() as db:
        simple = simulation.new_career("A", "RU", date(2016, 1, 1), 1, date(2000, 1, 1))
        real = simulation.new_career("B", "RU", date(2016, 1, 1), 1, date(2000, 1, 1))
        real.character_build = {"economy": "realistic"}
        for p in (simple, real):
            db.add(p)
        db.flush()
        a = economy.earn(simple, 1000, "prize", date(2016, 1, 1))
        b = economy.earn(real, 1000, "prize", date(2016, 1, 1))
        assert a == 1000 and b == 850
        assert story.get(real, "ledger")["2016-01"]["tax"] == -150
        db.rollback()


def test_loans_have_limits_interest_and_repayment(client):
    pid = new_player(client, age=25, occupation="work", realistic_economy=True)
    assert client.post(f"/api/players/{pid}/economy/loan", json={"amount": 100000}).status_code == 409
    b = client.post(f"/api/players/{pid}/economy/loan", json={"amount": 300}).json()
    assert b["loan"] == 300
    rest(client, pid, 40)  # a month boundary passes: the loan grows and a statement is written
    b = budget(client, pid)
    assert b["loan"] > 300
    owed = b["loan"]
    done = client.post(f"/api/players/{pid}/economy/repay", json={"amount": owed}).json()
    assert done["loan"] == 0
    with SessionLocal() as db:
        assert story.get(db.get(Player, pid), "loans_repaid") == 1
    assert client.post(f"/api/players/{pid}/economy/repay", json={"amount": 5}).status_code == 409
    simple = new_player(client)
    assert client.post(f"/api/players/{simple}/economy/loan", json={"amount": 50}).status_code == 409


def test_monthly_statement_reaches_the_activity_log(client):
    pid = new_player(client, age=25, occupation="work", realistic_economy=True)
    out = rest(client, pid, 40)
    assert any(e["type"] == "BUDGET" and e["message"].startswith("Monthly statement") for e in out["events"])
