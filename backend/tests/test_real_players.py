import json
from datetime import date

import httpx

from app.db import SessionLocal
from app.engine import world
from app.models import Npc
from app.services import world_service
from app.services.ranking import estimate_global_rank
from app.tools import import_real_players as imp

USER = {
    "id": 7, "username": "RealOne", "previous_usernames": ["OldName"], "country_code": "PL",
    "join_date": "2015-03-02T10:00:00+00:00",
    "statistics": {"global_rank": 120, "pp": 12000.5},
    "rank_highest": {"rank": 15, "updated_at": "2019-05-01T00:00:00+00:00"},
}


def test_importer_reads_rankings_and_profiles(monkeypatch):
    monkeypatch.setattr(imp, "REQUEST_DELAY", 0)

    def handler(request: httpx.Request):
        if request.url.path.endswith("/rankings/osu/performance"):
            page = int(request.url.params["cursor[page]"])
            return httpx.Response(200, json={"ranking": [{"user": {"id": 7}}] if page == 1 else []})
        if request.url.path.endswith("/users/7/osu"):
            return httpx.Response(200, json=USER)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ids = imp.top_user_ids(client, 5)
    assert ids == [7]
    rec = imp.fetch(client, ids)[0]
    assert rec == {"id": 7, "name": "RealOne", "previous_names": ["OldName"], "country": "PL",
                   "join_date": "2015-03-02", "current_rank": 120, "current_pp": 12000.5,
                   "highest_rank": 15, "highest_rank_date": "2019-05-01"}


def test_real_career_follows_the_anchors():
    rec = imp.player_record(USER)
    c = world.real_career(rec, date(2026, 10, 1), 1)
    assert c.join_date == date(2015, 3, 2)
    assert world.procedural_curve(c, date(2014, 1, 1)) is None  # not on osu! yet
    def rank_on(d):
        return estimate_global_rank(world.pp_for_overall(world.procedural_curve(c, d), d), d)

    assert rank_on(date(2016, 1, 1)) > rank_on(date(2019, 5, 1))
    assert 10 <= rank_on(date(2019, 5, 1)) <= 22  # highest rank 15 in May 2019
    assert 80 <= rank_on(date(2026, 10, 1)) <= 170  # rank 120 when fetched


def test_real_players_join_the_world(client, tmp_path, monkeypatch):
    records = [imp.player_record(USER), {**imp.player_record(USER), "id": 8, "name": "someone",
                                         "previous_names": ["mrekk"]}]  # an alias of a legend
    path = tmp_path / "real.json"
    path.write_text(json.dumps({"fetched": "2026-10-01", "players": records}))
    monkeypatch.setattr(world_service, "REAL_PLAYERS_FILE", path)
    world_service._real_player_records.cache_clear()
    try:
        pid = client.post("/api/players", json={"name": "U", "start_date": "2016-01-01", "seed": 3}).json()["id"]
        with SessionLocal() as db:
            reals = db.query(Npc).filter_by(player_id=pid, kind="real").all()
            assert [n.name for n in reals] == ["RealOne"]  # the legend's alias was skipped
            assert db.query(Npc).filter_by(player_id=pid, kind="procedural").count() == world.PROCEDURAL_WITH_REAL
    finally:
        world_service._real_player_records.cache_clear()
