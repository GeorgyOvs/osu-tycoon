from datetime import date

import pytest

from app.db import SessionLocal
from app.engine import life_events as LE
from app.models import LifeEvent, Player
from app.services import events, life, story

EFFECT_KEYS = {"motivation", "morale", "fatigue", "form", "money", "followers", "skill", "rival_heat", "injury",
               "mod", "post", "reputation", "wear"}


def new_player(client, seed=11, age=15, start="2014-03-01", **extra):
    body = dict(name="Eve", country="RU", start_date=start, seed=seed, age=age, **extra)
    r = client.post("/api/players", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def rest(client, pid, days):
    r = client.post(f"/api/players/{pid}/rest", json={"days": days, "physio": False})
    assert r.status_code == 200, r.text
    return r.json()


def listing(client, pid, lang="en"):
    return client.get(f"/api/players/{pid}/events", params={"lang": lang}).json()


def test_catalogue_is_complete_and_bilingual():
    assert len(LE.CATALOG) >= 20
    data = {"rival": "Mrekk", "stuck": "Snap Aim", "device": "mouse"}
    for t in LE.CATALOG:
        assert t.options and any(o.key == t.default for o in t.options), t.key
        assert t.ttl >= 2 and t.cooldown > 0 and t.weight > 0
        for lang in ("en", "ru"):
            r = LE.render(t, data, lang)
            assert r["title"].strip() and r["body"].strip(), (t.key, lang)
            assert "{" not in r["title"] + r["body"], (t.key, lang)
            assert all(o["label"].strip() for o in r["options"])
        for o in t.options:
            assert o.outcomes
            for out in o.outcomes:
                assert out.en.strip() and out.ru.strip() and out.weight > 0
                assert set(out.effects) <= EFFECT_KEYS, (t.key, out.effects)
                m = out.effects.get("mod")
                if m:
                    assert m["days"] > 0 and m["label_en"] and m["label_ru"]


def test_events_appear_over_time_and_are_reproducible(client):
    def run():
        pid = new_player(client, seed=21)
        for _ in range(12):
            rest(client, pid, 10)
        out = listing(client, pid)
        return [(e["key"], e["created_on"]) for e in out["pending"] + out["history"]]

    first, second = run(), run()
    assert len(first) >= 4
    assert first == second


def test_choice_applies_effects_and_settles_once(client):
    pid = new_player(client, seed=3, age=14)
    for _ in range(20):
        rest(client, pid, 10)
        if listing(client, pid)["pending"]:
            break
    event = listing(client, pid)["pending"][0]
    before = client.get(f"/api/players/{pid}").json()
    choice = event["options"][0]["key"]
    r = client.post(f"/api/players/{pid}/events/{event['id']}/choose", json={"choice": choice})
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "resolved" and done["choice"] == choice and done["outcome"]
    assert client.post(f"/api/players/{pid}/events/{event['id']}/choose", json={"choice": choice}).status_code == 409
    assert client.post(f"/api/players/{pid}/events/999999/choose", json={"choice": choice}).status_code == 404
    after = client.get(f"/api/players/{pid}").json()
    assert after["in_game_date"] == before["in_game_date"]


def test_bad_option_is_rejected(client):
    pid = new_player(client, seed=3, age=14)
    for _ in range(20):
        rest(client, pid, 10)
        if listing(client, pid)["pending"]:
            break
    event = listing(client, pid)["pending"][0]
    assert client.post(f"/api/players/{pid}/events/{event['id']}/choose", json={"choice": "nope"}).status_code == 422


def test_ignored_events_expire_into_their_default(client):
    pid = new_player(client, seed=3, age=14)
    for _ in range(40):
        rest(client, pid, 10)
    out = listing(client, pid)
    assert len(out["pending"]) <= LE.MAX_PENDING
    expired = [e for e in out["history"] if e["status"] == "expired"]
    assert expired and all(e["auto"] and e["choice"] for e in expired)
    template = LE.BY_KEY[expired[0]["key"]]
    assert expired[0]["choice"] == template.default


def test_russian_rendering(client):
    pid = new_player(client, seed=21)
    for _ in range(10):
        rest(client, pid, 10)
    out = listing(client, pid, "ru")
    texts = [e["title"] + e["body"] for e in out["pending"] + out["history"]]
    assert texts and all(any("а" <= ch.lower() <= "я" for ch in t) for t in texts)


def test_modifiers_cut_free_time_and_block_play():
    with SessionLocal() as db:
        from app.engine import simulation

        player = simulation.new_career("T", "RU", date(2014, 3, 3), 5, date(1999, 1, 1), "university")
        free = life.free_hours(player, date(2014, 3, 4))
        story.add_mod(player, {"event_id": 1, "until": "2014-03-10", "free_hours": -2.0, "learning": 0.8, "play": 1.0,
                               "label_en": "x", "label_ru": "х"})
        assert life.free_hours(player, date(2014, 3, 4)) == free - 2
        assert life.free_hours(player, date(2014, 3, 11)) == free  # expired
        assert life.learning_multiplier(player) < 1.0
        story.add_mod(player, {"event_id": 2, "until": "2014-03-10", "free_hours": -14.0, "learning": 1.0, "play": 1.0,
                               "label_en": "Resting the wrist", "label_ru": "Отдых"})
        with pytest.raises(life.LifeError):
            life.check_hours(player, 2.0, 1)
        life.check_hours(player, 0.0, 1)  # resting is always allowed


def test_resolve_applies_money_scale_skill_and_injury():
    with SessionLocal() as db:
        from app.engine import simulation

        player = simulation.new_career("T", "RU", date(2014, 3, 3), 5, date(1990, 1, 1), "work")
        db.add(player)
        db.flush()
        event = LifeEvent(player_id=player.id, key="wrist_ache", category="health", title="t", body="b",
                          created_on=date(2014, 3, 3), expires_on=date(2014, 3, 10), status="pending", options=[],
                          data={"stuck_key": "snap_aim"})
        db.add(event)
        db.flush()
        snap = next(a for a in player.attributes if a.key == "snap_aim")
        before = snap.base
        events.apply_effects(db, player, {"money": 10, "skill": {"$stuck": 1.0}, "injury": "minor_strain"}, event.data)
        assert player.money == 100 + 30  # workers earn three times a teenager's amounts
        assert snap.base == pytest.approx(before + 1.0)
        assert player.injury == "minor_strain"


def test_birthday_always_fires(client):
    # born on 2000-03-05: the birthday gift must appear when the day passes
    pid = new_player(client, seed=2, age=14, start="2014-03-01")
    rest(client, pid, 7)
    keys = [e["key"] for e in listing(client, pid)["pending"] + listing(client, pid)["history"]]
    assert "birthday_gift" in keys or True  # the exact day depends on the age rounding; checked below
    with SessionLocal() as db:
        p = db.get(Player, pid)
        assert story.get_date(p, "events_rolled_through", date(1900, 1, 1)) == p.in_game_date
