import pytest

from app.db import SessionLocal
from app.services import map_hints
from tests.conftest import seed_pool_maps

EASY, HARD = 5001, 5019  # seed_pool_maps: levels 1 and 19 of 20 (jump maps)


@pytest.fixture
def pid(client):
    pid = client.post("/api/players", json=dict(name="Reader", country="RU", start_date="2016-01-01", seed=8, age=17)).json()["id"]
    with SessionLocal() as db:
        seed_pool_maps(db)
    map_hints.analyse.cache_clear()
    map_hints._PERSONAL.clear()
    return pid


def hint(client, pid, bid, mods="", lang="en"):
    r = client.get(f"/api/players/{pid}/maps/{bid}/hint", params={"mods": mods, "lang": lang})
    assert r.status_code == 200, r.text
    return r.json()


def test_requirements_grow_with_difficulty_and_comfort_needs_more_than_passing(pid):
    easy, hard = map_hints.analyse(EASY, ""), map_hints.analyse(HARD, "")
    for read in (easy, hard):
        for k in map_hints.DIMS:
            assert read.comfort[k] >= read.passing[k], k
    assert hard.comfort["aim"] > easy.comfort["aim"] + 10
    assert hard.stars > easy.stars


def test_hint_card_shape_and_verdicts(client, pid):
    out = hint(client, pid, HARD)
    assert [d["key"] for d in out["dims"]] == ["aim", "tapping", "reading", "stamina"]
    assert 1 <= len(out["main_skills"]) <= 3 and out["main_skills"][0]["key"] == "aim"
    for d in out["dims"]:
        assert d["verdict"] in ("comfortable", "passable", "over")
        assert d["need_comfort"][0] <= d["need_comfort"][1] and d["need_pass"][0] <= d["need_pass"][1]
    aim = out["dims"][0]
    assert aim["verdict"] == "over"  # a brand-new player can't handle the hardest jump map
    assert out["precision"] == "rough" and out["notes"]  # a newcomer gets a vague read
    assert hint(client, pid, HARD) == out  # deterministic and cached
    easy = hint(client, pid, EASY)
    assert easy["dims"][0]["need_comfort"][1] < aim["need_comfort"][1]


def test_experience_sharpens_the_read(client, pid, monkeypatch):
    monkeypatch.setattr(map_hints, "experience", lambda db, player: 0.05)
    rough = hint(client, pid, HARD, "HR")
    map_hints._PERSONAL.clear()
    monkeypatch.setattr(map_hints, "experience", lambda db, player: 0.95)
    sharp = hint(client, pid, HARD, "HR")
    width = lambda h: sum(d["need_comfort"][1] - d["need_comfort"][0] for d in h["dims"])
    assert width(sharp) < width(rough) / 3
    assert sharp["precision"] == "sharp" and rough["precision"] == "rough"
    assert any("AR" in n for n in sharp["notes"])  # the veteran notices HR pushes the AR up
    assert any(ch.isdigit() for s in sharp["main_skills"] for ch in s["detail"])  # numbers, not vague words


def test_slot_mods_and_language(client, pid):
    tb = hint(client, pid, EASY, "TB")
    assert tb["mods"] == "NM"
    assert hint(client, pid, EASY, "NM")["dims"] == tb["dims"]
    ru = hint(client, pid, EASY, "HD", "ru")
    assert ru["dims"][0]["label"] == "Аим" and any("а" <= c.lower() <= "я" for c in ru["precision_label"])
    assert client.get(f"/api/players/{pid}/maps/{EASY}/hint", params={"mods": "ZZ"}).status_code == 422


def test_precision_bands():
    assert map_hints.precision(0.1) == "rough" and map_hints.precision(0.5) == "decent" and map_hints.precision(0.8) == "sharp"


def test_every_map_names_what_it_tests_and_trivial_dims_are_easy(client, pid):
    mid = hint(client, pid, 5010)
    assert mid["main_skills"]
    reading = next(d for d in mid["dims"] if d["key"] == "reading")
    assert reading["verdict"] == "comfortable"  # AR9 jump map asks nothing special of reading
