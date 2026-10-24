from datetime import date, timedelta

from app.db import SessionLocal
from app.models import Player, Tournament
from app.services import familiarity, tournaments
from tests.conftest import seed_pool_maps


def _career(client, start="2016-02-01", seed=21):
    pid = client.post("/api/players", json={"name": "Tour", "country": "RU", "start_date": start, "seed": seed,
                                             "age": 17}).json()["id"]
    with SessionLocal() as db:
        seed_pool_maps(db)
    return pid


def _cup(client, pid, name="6 Digit Spring Cup 2016"):
    listing = client.get(f"/api/players/{pid}/tournaments").json()
    return next(t for t in listing["tournaments"] if t["name"] == name)


def _register_and_reach_start(client, pid, cup):
    client.post(f"/api/players/{pid}/rest", json={"days": 15})
    assert client.post(f"/api/players/{pid}/tournaments/{cup['id']}/register").status_code == 200
    client.post(f"/api/players/{pid}/rest", json={"days": 60})  # stops on match day


def test_bws_counts_badges_from_2019():
    with SessionLocal() as db:
        player = Player(global_rank=5000, badges=[{"name": "x"}, {"name": "y"}])
        early = Tournament(tier="open", start_date=date(2017, 5, 1), rank_min=1000, rank_max=9999)
        late = Tournament(tier="open", start_date=date(2020, 5, 1), rank_min=1000, rank_max=9999)
        assert tournaments.seeding_rank(player, early) == 5000
        bws = tournaments.seeding_rank(player, late)
        assert bws < 5000  # badges push you up...
        player.badges = [{"name": str(i)} for i in range(7)]  # 5000 -> ~520
        assert not tournaments.eligible(player, late)  # ...out of rank-restricted events
        db.rollback()


def test_pool_is_released_a_week_early_and_can_be_practised(client):
    pid = _career(client)
    cup = _cup(client, pid)
    client.post(f"/api/players/{pid}/rest", json={"days": 15})
    client.post(f"/api/players/{pid}/tournaments/{cup['id']}/register")
    detail = client.get(f"/api/players/{pid}/tournaments/{cup['id']}").json()
    assert not any(s.get("beatmap_id") for s in detail["pools"].get("1", []))

    start = date.fromisoformat(cup["start_date"])
    now = date.fromisoformat(client.get(f"/api/players/{pid}").json()["in_game_date"])
    client.post(f"/api/players/{pid}/rest", json={"days": (start - timedelta(days=7) - now).days})
    detail = client.get(f"/api/players/{pid}/tournaments/{cup['id']}").json()
    pool = detail["pools"]["1"]
    assert all(s["beatmap_id"] for s in pool)

    resp = client.post(f"/api/players/{pid}/sessions/pool",
                       json={"tournament_id": cup["id"], "week": 1, "hours": 1})
    assert resp.status_code == 200, resp.text
    played_mods = {p["mods"] for p in resp.json()["plays"]}
    assert {"HD", "HR", "DT"} <= played_mods
    with SessionLocal() as db:
        player = db.get(Player, pid)
        assert all(familiarity.level(db, player, s["beatmap_id"]) > 0 for s in pool)


def test_qualifiers_decide_the_seeds(client):
    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    detail = client.get(f"/api/players/{pid}/tournaments/{cup['id']}").json()
    quals = detail["pools"]["qualifiers"]
    assert len(quals) == 32
    scores = [q["score"] for q in quals]
    assert scores == sorted(scores, reverse=True)
    seeds = {e["name"]: e["seed"] for e in detail["entries"]}
    assert all(seeds[q["name"]] == q["seed"] for q in quals)
    news = client.get(f"/api/players/{pid}/news").json()
    assert any(n["type"] == "QUALIFIERS" for n in news)


def test_your_bans_are_respected(client):
    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    pending = client.get(f"/api/players/{pid}/tournaments").json()["pending_match"]
    played = client.post(f"/api/players/{pid}/tournaments/{cup['id']}/matches/{pending['id']}/play",
                         json={"bans": ["DT3"], "picks": ["NM1", "HD1"]})
    assert played.status_code == 200, played.text
    m = next(x for x in played.json()["matches"] if x["id"] == pending["id"])
    bans = next(x["bans"] for x in m["maps"] if "bans" in x)
    user_side = "a" if next(e for e in played.json()["entries"] if e["id"] == m["entry_a"])["includes_user"] else "b"
    assert bans[user_side] == ["DT3"]
    assert all(x["slot"] != "DT3" for x in m["maps"] if "slot" in x)


def test_winning_a_badge_tournament_awards_a_badge(client):
    pid = _career(client, start="2016-03-15")
    with SessionLocal() as db:
        player = db.get(Player, pid)
        t = db.query(Tournament).filter_by(player_id=pid, tier="open").first()
        t.user_registered = True
        tournaments.start(db, player, t, [])
        gf = next(m for m in t.matches if m.key == "GF")
        user_entry = next(e for e in t.entries if e.includes_user)
        other = next(e for e in t.entries if not e.includes_user)
        gf.entry_a, gf.entry_b = user_entry.id, other.id
        tournaments._finish_match(db, player, t, gf, "a", player.in_game_date, [])
        assert player.badges and player.badges[0]["name"] == t.name
        assert player.money > 100  # first prize
        db.rollback()



def test_vanished_pool_maps_are_replaced_before_the_match(client, monkeypatch):
    from app.services import osu_files
    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    detail = client.get(f"/api/players/{pid}/tournaments/{cup['id']}").json()
    gone = detail["pools"]["1"][0]["beatmap_id"]
    real = osu_files.get_osu_file

    def flaky(beatmap_id):
        if beatmap_id == gone:
            raise osu_files.BeatmapNotFound("gone from osu.ppy.sh")
        return real(beatmap_id)

    monkeypatch.setattr(osu_files, "get_osu_file", flaky)
    osu_files._MEMORY.pop(gone, None)
    pending = client.get(f"/api/players/{pid}/tournaments").json()["pending_match"]
    played = client.post(f"/api/players/{pid}/tournaments/{cup['id']}/matches/{pending['id']}/play")
    assert played.status_code == 200, played.text
    assert all(s["beatmap_id"] != gone for s in played.json()["pools"]["1"])



def test_injured_on_match_day_forfeits_instead_of_freezing(client):
    from datetime import timedelta

    from app.engine import simulation

    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    with SessionLocal() as db:
        player = db.get(Player, pid)
        player.injury = simulation.SEVERE_RSI
        player.injury_until = player.in_game_date + timedelta(days=40)
        db.commit()
    resp = client.post(f"/api/players/{pid}/rest", json={"days": 3})
    assert resp.status_code == 200, resp.text  # the calendar moves on
    news = client.get(f"/api/players/{pid}/news").json()
    assert any(n["type"] == "FORFEIT" for n in news)


def test_withdrawing_from_a_match(client):
    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    pending = client.get(f"/api/players/{pid}/tournaments").json()["pending_match"]
    resp = client.post(f"/api/players/{pid}/tournaments/{cup['id']}/matches/{pending['id']}/forfeit")
    assert resp.status_code == 200, resp.text
    m = next(x for x in resp.json()["matches"] if x["id"] == pending["id"])
    assert max(m["score_a"], m["score_b"]) == m["first_to"] and min(m["score_a"], m["score_b"]) == 0
