from app.services import profile_stats
from tests.conftest import FIXTURE_BEATMAP_ID


def test_level_curve_matches_osu():
    assert profile_stats.level(0)[0] == 1
    assert profile_stats.level(int(profile_stats.score_for_level(50)) + 1)[0] == 50
    lvl, progress = profile_stats.level(int(profile_stats.score_for_level(100) + 10))
    assert lvl == 100 and 0 <= progress < 0.01


def test_osu_profile_page(client):
    pid = client.post("/api/players", json=dict(name="Prof", country="RU", start_date="2016-01-01", seed=3, age=17)).json()["id"]
    empty = client.get(f"/api/players/{pid}/osu-profile").json()
    assert empty["joined"] == "2016-01-01" and empty["global_rank"] is None and empty["level"] == 1
    for acc in (100, 97):
        client.post(f"/api/players/{pid}/scores", json={"beatmap_id": FIXTURE_BEATMAP_ID, "accuracy": acc, "mods": "HD"})
    client.post(f"/api/players/{pid}/scores", json={"beatmap_id": FIXTURE_BEATMAP_ID + 1, "accuracy": 99, "misses": 0})
    client.post(f"/api/players/{pid}/rest", json={"days": 3, "physio": False})
    page = client.get(f"/api/players/{pid}/osu-profile").json()
    assert page["global_rank"] and page["country_rank"] and page["country_rank"] <= page["global_rank"]
    assert page["ranked_score"] > 0 and page["total_score"] >= page["ranked_score"]
    assert page["grades"]["XH"] == 1  # the 100% HD play is a silver SS; the worse replay doesn't count
    assert page["peak_rank"] and len(page["history"]) >= 2 and page["history"][-1]["pp"] > 0
    r = client.put(f"/api/players/{pid}/me", json={"text": "hi, i click circles"})
    assert r.json()["me"] == "hi, i click circles"
