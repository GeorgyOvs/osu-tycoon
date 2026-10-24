import random
from collections import Counter
from datetime import date, timedelta

import pytest

from app.db import SessionLocal
from app.engine import bracket, match, world
from app.engine.world_data import LEGENDS
from app.models import Npc, Tournament
from app.services import ranking, world_service
from tests.conftest import seed_pool_maps as _seed_pool_maps

COOKIEZI = world.LEGENDS_BY_NAME["Cookiezi"]
RRTYUI = world.LEGENDS_BY_NAME["rrtyui"]


# --- engine -------------------------------------------------------------------------------


def test_legend_careers_follow_history():
    assert world.legend_status(COOKIEZI, date(2008, 1, 1)) == "not_started"
    assert world.legend_status(COOKIEZI, date(2012, 6, 1)) == "active"
    assert world.legend_status(COOKIEZI, date(2014, 6, 1)) == "inactive"
    assert world.legend_status(COOKIEZI, date(2016, 6, 1)) == "active"
    assert world.legend_status(RRTYUI, date(2016, 1, 1)) == "retired"
    assert world.legend_curve(COOKIEZI, date(2013, 1, 1)) == pytest.approx(99, abs=0.5)
    assert world.legend_curve(COOKIEZI, date(2021, 1, 1)) < 90


def test_rivalry_delays_a_legends_decline():
    on = date(2021, 1, 1)
    assert world.legend_curve(COOKIEZI, on, shift_weeks=104) > world.legend_curve(COOKIEZI, on)
    # before the peak nothing changes
    assert world.legend_curve(COOKIEZI, date(2011, 1, 1), 104) == world.legend_curve(COOKIEZI, date(2011, 1, 1))


def test_procedural_careers_are_seeded_and_shaped():
    a, b = world.generate_procedural(7, 50), world.generate_procedural(7, 50)
    assert [c.name for c in a] == [c.name for c in b]
    assert len({c.name for c in a}) == 50
    c = a[0]
    assert world.procedural_curve(c, c.join_date - timedelta(days=1)) is None
    peak_day = c.join_date + timedelta(days=int((c.ramp_years + c.prime_years / 2) * 365))
    late = c.join_date + timedelta(days=int((c.ramp_years + c.prime_years + 3) * 365))
    assert world.procedural_curve(c, peak_day) == pytest.approx(c.peak)
    assert world.procedural_curve(c, late) < c.peak


def test_pp_and_overall_are_inverse_and_era_relative():
    on = date(2016, 6, 1)
    assert world.overall_for_pp(world.pp_for_overall(80, on), on) == pytest.approx(80)
    # the same rating is worth more relative to a weaker era
    old, new = date(2010, 6, 1), date(2024, 6, 1)
    assert world.pp_for_overall(90, old) / ranking.top_pp(old) > world.pp_for_overall(90, new) / ranking.top_pp(new)


def _sources_are_earlier(specs):
    order = {s.key: s.order for s in specs}
    for s in specs:
        for src in (s.source_a, s.source_b):
            kind, ref = src.split(":")
            if kind != "seed":
                assert order[ref] < s.order, (s.key, src)


@pytest.mark.parametrize("size", [4, 8, 16, 32])
def test_double_elimination_layout(size):
    specs = bracket.double_elimination(size)
    assert len(specs) == 2 * size - 2
    _sources_are_earlier(specs)
    seeds = [int(src.split(":")[1]) for s in specs for src in (s.source_a, s.source_b) if src.startswith("seed")]
    assert sorted(seeds) == list(range(1, size + 1))


def test_double_elimination_everyone_loses_twice_except_champion():
    specs = bracket.double_elimination(16)
    rng = random.Random(1)
    winners, losers, losses = {}, {}, Counter()

    def resolve(src):
        kind, ref = src.split(":")
        return int(ref) if kind == "seed" else (winners if kind == "winner" else losers)[ref]

    for s in specs:
        a, b = resolve(s.source_a), resolve(s.source_b)
        w, l = (a, b) if rng.random() < 0.5 else (b, a)
        winners[s.key], losers[s.key] = w, l
        losses[l] += 1
    champion = winners["GF"]
    assert losses[champion] <= 1
    assert sum(1 for p in range(1, 17) if p != champion and losses[p] == 2) >= 14


def test_light_match_favours_the_stronger_side():
    strong = world.composites(95, {})
    weak = world.composites(75, {})
    pool = match.pool_layout(1, 6.0)
    wins = 0
    for k in range(40):
        outcome = match.light_match(strong, weak, 0, 0, pool, 5, random.Random(k))
        assert max(outcome.score_a, outcome.score_b) == 5
        wins += outcome.winner == "a"
    assert wins >= 34


def test_tiebreaker_is_played_at_match_point():
    pool = match.pool_layout(1, 6.0)
    flip = iter([True, False] * 20)

    def play(slot, decisive):
        return (1, 0, {}) if next(flip) else (0, 1, {})

    outcome = match.run_match(pool, 3, lambda s: 0.0, play, random.Random(0))
    assert outcome.maps[-1].slot == "TB"
    assert len(outcome.maps) == 5


# --- persisted world ------------------------------------------------------------------------


def _create(client, start="2014-01-01", seed=5):
    return client.post("/api/players", json={"name": "Tester", "country": "RU", "start_date": start, "seed": seed}).json()


def test_world_is_created_with_the_career(client):
    pid = _create(client)["id"]
    with SessionLocal() as db:
        npcs = db.query(Npc).filter_by(player_id=pid).all()
        assert sum(1 for n in npcs if n.kind == "legend") == len(LEGENDS)
        assert sum(1 for n in npcs if n.kind == "procedural") == world.PROCEDURAL_COUNT
        assert db.query(Tournament).filter_by(player_id=pid).count() > 10

    board = client.get(f"/api/players/{pid}/leaderboard", params={"limit": 10}).json()
    ranks = [r["rank"] for r in board["rows"]]
    assert ranks == sorted(ranks) and ranks[0] == 1
    assert any(r["kind"] == "legend" for r in board["rows"][:5])
    npc_id = next(r["npc_id"] for r in board["rows"] if r["npc_id"])
    scout = client.get(f"/api/players/{pid}/npcs/{npc_id}")
    assert scout.status_code == 200, scout.text
    profile = scout.json()
    assert profile["pp_potential"] > 0 and profile["tournament_strength"] > 0
    assert len(profile["best_score_types"]) == 2
    assert profile["peaks"] and profile["weaknesses"]
    assert "summary" in profile["match_stats"]


def test_world_moves_while_you_rest(client):
    pid = _create(client)["id"]
    events = []
    for _ in range(8):
        events += client.post(f"/api/players/{pid}/rest", json={"days": 30}).json()["events"]
    world_events = [e for e in events if e["type"].startswith("WORLD_")]
    assert any(e["type"] == "WORLD_TOURNAMENT_WINNER" for e in world_events)
    news = client.get(f"/api/players/{pid}/news").json()
    assert len(news) >= len(world_events) > 0

    listing = client.get(f"/api/players/{pid}/tournaments").json()
    finished = [t for t in listing["tournaments"] if t["status"] == "finished"]
    assert finished and all(t["winner"] for t in finished)
    detail = client.get(f"/api/players/{pid}/tournaments/{finished[0]['id']}").json()
    assert sum(1 for e in detail["entries"] if e["placement"] == "1st") == 1
    assert all(m["winner"] for m in detail["matches"])


def test_register_play_a_match_and_move_on(client):
    pid = _create(client, start="2016-02-01", seed=11)["id"]
    with SessionLocal() as db:
        _seed_pool_maps(db)

    listing = client.get(f"/api/players/{pid}/tournaments").json()
    cup = next(t for t in listing["tournaments"] if t["name"] == "6 Digit Spring Cup 2016")
    assert cup["eligible"] and not cup["can_register"]  # registration opens 4 weeks before
    early = client.post(f"/api/players/{pid}/tournaments/{cup['id']}/register")
    assert early.status_code == 409

    client.post(f"/api/players/{pid}/rest", json={"days": 15})
    reg = client.post(f"/api/players/{pid}/tournaments/{cup['id']}/register")
    assert reg.status_code == 200, reg.text
    assert reg.json()["user_registered"]

    # A long rest stops on match day...
    rested = client.post(f"/api/players/{pid}/rest", json={"days": 60}).json()
    assert rested["end_date"] == cup["start_date"]
    listing = client.get(f"/api/players/{pid}/tournaments").json()
    pending = listing["pending_match"]
    assert pending and pending["is_user_match"] and pending["due"] == cup["start_date"]
    # ...and nothing else can happen until the match is played.
    assert client.post(f"/api/players/{pid}/rest", json={"days": 1}).status_code == 409

    played = client.post(f"/api/players/{pid}/tournaments/{cup['id']}/matches/{pending['id']}/play")
    assert played.status_code == 200, played.text
    detail = played.json()
    m = next(x for x in detail["matches"] if x["id"] == pending["id"])
    assert m["winner"] is not None
    assert max(m["score_a"], m["score_b"]) == m["first_to"]
    picks = [x for x in m["maps"] if "slot" in x]
    assert len(picks) == m["score_a"] + m["score_b"]
    assert all(p["players"] and p["title"] for p in picks)
    # other first-round matches were resolved as well
    first_round = [x for x in detail["matches"] if x["week"] == 1]
    assert all(x["winner"] for x in first_round)

    assert client.post(f"/api/players/{pid}/rest", json={"days": 1}).status_code == 200


def test_owc_needs_no_registration(client):
    pid = _create(client)["id"]
    listing = client.get(f"/api/players/{pid}/tournaments").json()
    with SessionLocal() as db:
        owc = db.query(Tournament).filter_by(player_id=pid, tier="owc").first()
    resp = client.post(f"/api/players/{pid}/tournaments/{owc.id}/register")
    assert resp.status_code == 422
    assert listing["date"] == "2014-01-01"


def test_one_person_is_one_legend():
    names = [legend.name for legend in LEGENDS]
    aliases = [a for legend in LEGENDS for a in legend.aliases]
    assert len(set(names + aliases)) == len(names) + len(aliases)
    assert "chocomint" in world.LEGENDS_BY_NAME["Cookiezi"].aliases
    generated = {c.name for c in world.generate_procedural(1, 400)}
    assert not generated & world.RESERVED_NAMES
