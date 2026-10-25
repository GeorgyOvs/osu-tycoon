from sqlalchemy import select

from app.db import SessionLocal
from app.models import Npc
from tests.conftest import seed_pool_maps


def career(client, start="2016-06-01"):
    pid = client.post("/api/players", json=dict(name="Seeker", country="RU", start_date=start, seed=8, age=17)).json()["id"]
    with SessionLocal() as db:
        seed_pool_maps(db)
    return pid


def npc_id(pid, name):
    with SessionLocal() as db:
        return db.scalar(select(Npc.id).where(Npc.player_id == pid, Npc.name == name))


def test_search_finds_players_and_maps(client):
    pid = career(client)
    out = client.get(f"/api/players/{pid}/search", params={"q": "cookie"}).json()
    names = [p["name"] for p in out["players"]]
    assert "Cookiezi" in names and names.index("Cookiezi") <= 2
    assert client.get(f"/api/players/{pid}/search", params={"q": "chocomint"}).json()["players"][0]["name"] == "Cookiezi"  # alias
    maps = client.get(f"/api/players/{pid}/search", params={"q": "artist"}).json()["maps"]
    assert maps and maps[0]["diffs"] and all(m["ranked_date"] <= "2016-06-01" for m in maps)
    assert client.get(f"/api/players/{pid}/search", params={"q": "x"}).json() == {"players": [], "maps": []}


def test_npc_profile_history_follows_the_curve(client):
    pid = career(client)
    nid = npc_id(pid, "Cookiezi")
    page = client.get(f"/api/players/{pid}/npcs/{nid}/osu-profile").json()
    assert page["kind"] == "legend" and page["name"] == "Cookiezi" and len(page["history"]) >= 20
    assert page["history"][-1]["rank"] == page["global_rank"]
    ranked = [h["rank"] for h in page["history"] if h["rank"]]
    assert page["peak_rank"] == min(ranked + ([page["peak_rank"]] if page["peak_rank"] else []))
    assert set(page["composites"]) == {"aim", "tapping", "reading", "technical", "mentality", "physical"}
    assert page["relationship"]["rival"] is None or "heat" in page["relationship"]["rival"]
    again = client.get(f"/api/players/{pid}/npcs/{nid}/osu-profile").json()
    assert again["history"] == page["history"]  # deterministic, nothing stored


def test_npc_top_plays_come_from_their_board_scores(client):
    pid = career(client)
    client.get(f"/api/players/{pid}/beatmaps/1001/leaderboard")
    board = client.get(f"/api/players/{pid}/beatmaps/1001/leaderboard").json()
    top = next(e for e in board["entries"] if e["npc_id"])
    page = client.get(f"/api/players/{pid}/npcs/{top['npc_id']}/osu-profile").json()
    assert any(p["beatmap_id"] == 1001 for p in page["top_plays"])


def test_compare_and_name_lookup(client):
    pid = career(client)
    client.post(f"/api/players/{pid}/scores", json={"beatmap_id": 1001, "accuracy": 97})
    client.post(f"/api/players/{pid}/rest", json={"days": 3, "physio": False})
    nid = npc_id(pid, "Cookiezi")
    out = client.get(f"/api/players/{pid}/npcs/{nid}/compare").json()
    assert out["you"]["name"] == "Seeker" and out["them"]["name"] == "Cookiezi"
    assert out["you"]["history"] and out["them"]["history"]
    assert out["them"]["history"][0]["date"] >= out["you"]["history"][0]["date"]  # aligned to your career
    assert client.get(f"/api/players/{pid}/npc-by-name/Cookiezi").json()["id"] == nid
    assert client.get(f"/api/players/{pid}/npc-by-name/nobody").status_code == 404
    assert client.get(f"/api/players/{pid}/npcs/999999/osu-profile").status_code == 404
