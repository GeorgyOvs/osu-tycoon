from app.db import SessionLocal
from app.models import Npc, Player
from app.services import duels
from tests.conftest import seed_pool_maps


def _career(client, seed=40, skill=None):
    pid = client.post("/api/players", json={"name": "Duelist", "country": "RU", "start_date": "2016-10-17",
                                             "seed": seed, "age": 17}).json()["id"]
    with SessionLocal() as db:
        seed_pool_maps(db, n=60)
        if skill is not None:
            player = db.get(Player, pid)
            for a in player.attributes:
                a.base = float(skill)
        db.commit()
    return pid


def _npc_near(pid, overall_range=(20, 60)):
    with SessionLocal() as db:
        npc = (db.query(Npc).filter(Npc.player_id == pid, Npc.status == "active", Npc.rank.isnot(None),
                                    Npc.overall.between(*overall_range)).order_by(Npc.rank.desc()).first())
        return npc.id, npc.name


def test_a_full_bo5_with_your_bans(client):
    pid = _career(client, skill=45)
    npc_id, name = _npc_near(pid)
    with SessionLocal() as db:  # make them reachable for a friendly regardless of rank
        db.get(Player, pid).global_rank = db.get(Npc, npc_id).rank
        db.commit()
    drawn = client.post(f"/api/players/{pid}/duels", json={"npc_id": npc_id, "best_of": 5, "bans_per_side": 1})
    assert drawn.status_code == 200, drawn.text
    d = drawn.json()
    assert d["status"] == "pending" and d["opponent"] == name
    assert [s["slot"] for s in d["pool"]] == duels.pool_layout(5)
    assert all(s["beatmap_id"] for s in d["pool"])

    played = client.post(f"/api/players/{pid}/duels/{d['id']}/play", json={"bans": ["DT3"], "picks": ["NM1"]}).json()
    assert played["status"] == "played"
    assert max(played["score_user"], played["score_npc"]) == 3
    assert played["won"] == (played["score_user"] == 3)
    bans = next(m["bans"] for m in played["maps"] if "bans" in m)
    assert bans["a"] == ["DT3"]
    assert client.post(f"/api/players/{pid}/duels/{d['id']}/play").status_code == 409  # already played
    assert client.get(f"/api/players/{pid}/duels").json()[0]["id"] == d["id"]
    events = client.get(f"/api/st/careers/{pid}/events", params={"limit": 50}).json()
    assert any(e["type"] == "DUEL_RESULT" for e in events)


def test_bo1_pool_and_daily_limit(client):
    pid = _career(client, skill=45)
    npc_id, _ = _npc_near(pid)
    with SessionLocal() as db:
        db.get(Player, pid).global_rank = db.get(Npc, npc_id).rank
        db.commit()
    for i in range(duels.MAX_DUELS_PER_DAY):
        d = client.post(f"/api/players/{pid}/duels", json={"npc_id": npc_id, "best_of": 1, "bans_per_side": 2}).json()
        assert len(d["pool"]) == 5
        played = client.post(f"/api/players/{pid}/duels/{d['id']}/play").json()
        assert played["score_user"] + played["score_npc"] == 1
    tired = client.post(f"/api/players/{pid}/duels", json={"npc_id": npc_id, "best_of": 1})
    assert tired.status_code == 409


def test_legends_decline_randoms_and_challenges_expire(client):
    pid = _career(client)
    with SessionLocal() as db:
        legend = db.query(Npc).filter_by(player_id=pid, kind="legend", status="active").first()
        legend_id = legend.id
    resp = client.post(f"/api/players/{pid}/duels", json={"npc_id": legend_id, "best_of": 3})
    assert resp.status_code == 409 and "declined" in resp.json()["detail"]
    assert client.get(f"/api/players/{pid}/irc", params={"channel": f"DM:{legend.name}"}).json()
    assert client.post(f"/api/players/{pid}/duels", json={"npc_id": legend_id, "best_of": 4}).status_code == 422

    npc_id, _ = _npc_near(pid, (24, 48))
    with SessionLocal() as db:
        db.get(Player, pid).global_rank = db.get(Npc, npc_id).rank
        db.commit()
    d = client.post(f"/api/players/{pid}/duels", json={"npc_id": npc_id, "best_of": 3}).json()
    client.post(f"/api/players/{pid}/rest", json={"days": 1})
    assert client.post(f"/api/players/{pid}/duels/{d['id']}/play").status_code == 409  # expired overnight


def test_skill_decides_most_duels(client):
    strong = _career(client, seed=41, skill=85)
    npc_id, _ = _npc_near(strong, (15, 35))
    wins = 0
    for day in range(4):
        with SessionLocal() as db:
            db.get(Player, strong).global_rank = db.get(Npc, npc_id).rank
            db.commit()
        d = client.post(f"/api/players/{strong}/duels", json={"npc_id": npc_id, "best_of": 3}).json()
        wins += client.post(f"/api/players/{strong}/duels/{d['id']}/play").json()["won"]
        client.post(f"/api/players/{strong}/rest", json={"days": 1})
    assert wins >= 3
