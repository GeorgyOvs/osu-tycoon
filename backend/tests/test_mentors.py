from datetime import date

import pytest

from app.db import SessionLocal
from app.engine import mentors as M
from app.models import Npc, Player
from app.services import mentors as svc


def new_player(client, seed=6, start="2014-03-01", age=16, **extra):
    r = client.post("/api/players", json=dict(name="Stu", country="RU", start_date=start, seed=seed, age=age, **extra))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def overview(client, pid):
    r = client.get(f"/api/players/{pid}/mentor")
    assert r.status_code == 200, r.text
    return r.json()


def accept_one(client, pid, tries=40):
    for _ in range(tries):
        cands = overview(client, pid)["candidates"]
        for c in cands:
            if c["blocked"] is None:
                r = client.post(f"/api/players/{pid}/mentor/ask", json={"npc_id": c["npc_id"]}).json()
                if r["accepted"]:
                    return r
        client.post(f"/api/players/{pid}/rest", json={"days": 15, "physio": False})
    pytest.fail("nobody agreed to mentor in 40 tries")


def test_acceptance_rules():
    base = dict(motivation=80, same_country=True, followers=0, gap=15, rival_heat=None)
    assert M.acceptance_chance(**{**base, "rival_heat": 60}) == 0.0
    assert M.acceptance_chance(**base) > M.acceptance_chance(**{**base, "same_country": False})
    assert M.acceptance_chance(**base) > M.acceptance_chance(**{**base, "gap": 40})
    assert M.acceptance_chance(**base) > M.acceptance_chance(**{**base, "motivation": 10})
    assert 0.05 <= M.acceptance_chance(**{**base, "gap": 500}) <= 0.85
    assert M.boost_for(100) > M.boost_for(0) and M.boost_for(1000) <= 1.5


def test_candidates_are_stronger_and_era_gated(client):
    pid = new_player(client)
    out = overview(client, pid)
    assert out["available"] and out["candidates"] and out["mentor"] is None
    assert all(c["overall"] > 0 and 0 <= c["chance"] <= 100 and c["focus"] in M.GROUP_LABELS for c in out["candidates"])
    old = new_player(client, start="2007-10-01")
    o = overview(client, old)
    assert not o["available"] and o["candidates"] == []
    assert client.post(f"/api/players/{old}/mentor/ask", json={"npc_id": 1}).status_code == 409


def test_ask_session_and_end(client):
    pid = new_player(client)
    res = accept_one(client, pid)
    assert res["mentor"]["group"] in M.GROUP_LABELS
    assert client.post(f"/api/players/{pid}/mentor/ask", json={"npc_id": res["mentor"]["npc_id"]}).status_code == 409
    r = client.post(f"/api/players/{pid}/mentor/session", json={"hours": 2})
    assert r.status_code == 200, r.text
    out = r.json()
    group = res["mentor"]["group"]
    assert out["mentor"]["sessions"] == 1 and out["mentor"]["bond"] > 30
    assert out["action"]["days"] == 1 and out["action"]["deltas"]
    assert out["mentor"]["boost_until"] > out["action"]["start_date"]
    after = overview(client, pid)
    assert after["mentor"]["boost_active"] and after["log"]
    ended = client.post(f"/api/players/{pid}/mentor/end").json()
    assert ended["mentor"] is None
    assert client.post(f"/api/players/{pid}/mentor/end").status_code == 409
    assert group


def test_mentor_boost_speeds_up_the_focus_group():
    from app.engine import attributes as A
    from app.engine import simulation as S
    from app.engine.training import DRILLS

    def gain(boost):
        p = S.new_career("T", "RU", date(2016, 1, 1), 5)
        p.story_state = {"mentor": {"group": "aim", "boost": boost, "boost_until": "2099-01-01"}}
        before = {a.key: a.base for a in p.attributes}
        S.run_days(p, S.DayPlan(DRILLS["jump_farm"], 3), 5)
        return sum(a.base - before[a.key] for a in p.attributes if A.GROUP_OF[a.key] == "aim")

    assert gain(1.4) > gain(1.0) * 1.2


def test_idle_mentor_loses_interest_and_graduation(client):
    pid = new_player(client)
    accept_one(client, pid)
    for _ in range(40):
        client.post(f"/api/players/{pid}/rest", json={"days": 14, "physio": False})
        if overview(client, pid)["mentor"] is None:
            break
    out = overview(client, pid)
    assert out["mentor"] is None
    assert any("lost interest" in e["text"] or "no longer around" in e["text"] or "caught up" in e["text"] for e in out["log"])


def test_graduation_when_player_catches_up(client):
    pid = new_player(client)
    accept_one(client, pid)
    with SessionLocal() as db:
        p = db.get(Player, pid)
        npc = db.get(Npc, svc.state(p)["npc_id"])
        for a in p.attributes:
            a.base = a.cap = min(99.0, npc.overall + 5)
        db.commit()
    client.post(f"/api/players/{pid}/rest", json={"days": 2, "physio": False})
    out = overview(client, pid)
    assert out["mentor"] is None and any("caught up" in e["text"] for e in out["log"])
