from app.db import SessionLocal
from app.engine import achievements as AC
from app.models import Player
from app.services import legacy, story
from tests.conftest import FIXTURE_BEATMAP_ID as B


def new_player(client, seed=6, age=17, **extra):
    body = dict(name="Leg", country="RU", start_date="2016-03-01", seed=seed, age=age, **extra)
    r = client.post("/api/players", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def rest(client, pid, days=1):
    assert client.post(f"/api/players/{pid}/rest", json={"days": days, "physio": False}).status_code == 200


def get(client, pid, lang="en"):
    r = client.get(f"/api/players/{pid}/legacy", params={"lang": lang})
    assert r.status_code == 200, r.text
    return r.json()


def test_catalogue_is_big_bilingual_and_consistent():
    assert len(AC.CATALOG) >= 40
    for a in AC.CATALOG:
        assert all(a.name) and all(a.desc) and "{" not in "".join(a.name + a.desc)
        assert a.rarity in AC.RARITY_POINTS and a.category in AC.CATEGORY_LABELS
    snap = AC.Snapshot(best_rank=800, play_count=30)
    keys = {a.key for a in AC.CATALOG if a.unlocked(snap)}
    assert {"best_rank_1000", "best_rank_5000", "play_count_25"} <= keys and "best_rank_500" not in keys
    ranks = [AC.BY_KEY[f"best_rank_{n}"].progress(AC.Snapshot(best_rank=r)) for n, r in ((100, 5000), (100, 500), (100, 150))]
    assert ranks == sorted(ranks) and 0 < ranks[0] < 1


def test_every_achievement_name_has_a_russian_translation():
    import pathlib

    text = pathlib.Path(__file__).resolve().parents[2].joinpath("frontend/src/i18n.ru.legacy.ts").read_text(encoding="utf-8")
    missing = [a.name[0] for a in AC.CATALOG if f"'{a.name[0]}'" not in text and f'"{a.name[0]}"' not in text]
    assert not missing


def test_scores_unlock_achievements_and_update_records(client):
    pid = new_player(client)
    assert get(client, pid)["achievements"]["unlocked_count"] == 0
    client.post(f"/api/players/{pid}/scores", json={"beatmap_id": B, "accuracy": 98})
    rest(client, pid)
    out = get(client, pid)
    keys = {a["key"] for a in out["achievements"]["unlocked"]}
    assert "play_count_1" in keys
    assert any(r["key"] == "peak_pp" for r in out["records"])
    assert out["achievements"]["next"] and all(0 <= n["progress"] <= 1 for n in out["achievements"]["next"])
    assert out["score"] > 0 and out["status"]["retired"] is False
    ru = get(client, pid, "ru")
    assert any(a["name"] == "Плеев: 1" for a in ru["achievements"]["unlocked"])
    news = client.get(f"/api/players/{pid}/news").json()
    assert not any(n["type"] == "ACHIEVEMENT" for n in news)  # a common medal stays out of the news


def test_retirement_writes_an_epilogue_and_freezes_training(client):
    pid = new_player(client)
    client.post(f"/api/players/{pid}/scores", json={"beatmap_id": B, "accuracy": 97})
    r = client.post(f"/api/players/{pid}/retire")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"]["retired"] and out["epilogue"]["lines"] and out["epilogue"]["score"] >= 0
    ru = get(client, pid, "ru")["epilogue"]["lines"]
    assert any("плеев" in line for line in ru)
    assert client.post(f"/api/players/{pid}/retire").status_code == 409
    assert client.post(f"/api/players/{pid}/train", json={"drill": "ranked_pack_grind", "hours_per_day": 2, "days": 1}).status_code == 409
    rest(client, pid, 3)  # the calendar still turns
    hall = client.get("/api/hall-of-fame").json()
    assert [h["id"] for h in hall] == [pid] and hall[0]["reason"] == "manual"
    threads = client.get(f"/api/players/{pid}/forum").json()
    assert any("retired" in t["title"] for t in threads)


def test_records_survive_between_ticks():
    with SessionLocal() as db:
        from datetime import date

        from app.engine import simulation

        p = simulation.new_career("R", "RU", date(2016, 1, 1), 3, date(2000, 1, 1))
        db.add(p)
        db.flush()
        p.global_rank, p.total_pp = 900, 1500.0
        legacy.tick(db, p, [])
        p.global_rank, p.total_pp = 4000, 900.0
        p.in_game_date = date(2016, 2, 1)
        legacy.tick(db, p, [])
        rec = story.get(p, "records")
        assert rec["best_rank"] == 900 and rec["peak_pp"] == 1500.0
        assert "best_rank_1000" in story.get(p, "achievements")
        db.rollback()
