from datetime import date, timedelta

import httpx
import pytest

from app.db import SessionLocal
from app.models import SyncState
from app.services import beatmap_index, mirror
from tests.conftest import FIXTURE_BEATMAP_ID, make_set

RAW_SET = {
    "id": 39804, "artist": "xi", "title": "FREEDOM DiVE", "creator": "Nakagawa-Kanon",
    "status": "approved", "ranked_date": "2012-06-23T16:42:35Z", "play_count": 5, "favourite_count": 2,
    "bpm": 222.22,
    "beatmaps": [
        {"id": 129891, "mode_int": 0, "convert": False, "version": "FOUR DIMENSIONS", "difficulty_rating": 7.8,
         "ar": 9, "cs": 4, "accuracy": 8, "drain": 6, "bpm": 222.22, "total_length": 258, "hit_length": 258,
         "max_combo": 2385, "count_circles": 1646, "count_sliders": 335, "playcount": 1, "passcount": 1},
        {"id": 1, "mode_int": 1, "convert": False, "version": "taiko"},
        {"id": 2, "mode_int": 0, "convert": True, "version": "convert"},
    ],
}


def test_parse_set_keeps_only_standard_difficulties():
    data = mirror.parse_set(RAW_SET)
    assert data.ranked_date == date(2012, 6, 23)
    assert [b.id for b in data.beatmaps] == [129891]
    assert data.beatmaps[0].od == 8 and data.beatmaps[0].stars == 7.8


def test_mirror_client_search_params_and_errors():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(request.url.params)
        seen["path"] = request.url.path
        return httpx.Response(200, json=[RAW_SET])

    client = mirror.MirrorClient(
        httpx.Client(base_url="https://mirror.test/api", transport=httpx.MockTransport(handler))
    )
    page = client.search_page(mirror.STATUS_RANKED, 200)
    assert page[0].id == 39804
    assert seen["path"] == "/api/v2/search"
    assert seen["sort"] == "ranked_date:asc" and seen["offset"] == "200" and seen["status"] == "1"

    broken = mirror.MirrorClient(
        httpx.Client(
            base_url="https://mirror.test/api",
            transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom")),
        )
    )
    with pytest.raises(mirror.MirrorError):
        broken.search_page(1, 0)


class PagedMirror:
    """250 ranked sets one day apart from 2008-01-01, plus 30 approved ones."""

    def __init__(self):
        start = date(2008, 1, 1)
        self.data = {
            mirror.STATUS_RANKED: [
                make_set(10_000 + i, start + timedelta(days=i), [100_000 + i]) for i in range(250)
            ],
            mirror.STATUS_APPROVED: [
                make_set(20_000 + i, start + timedelta(days=3 * i), [200_000 + i], status="approved")
                for i in range(30)
            ],
        }
        self.calls = []

    def search_page(self, status, offset):
        self.calls.append((status, offset))
        return self.data[status][offset : offset + mirror.PAGE_SIZE]


def test_sync_crawls_only_up_to_target_and_resumes():
    fake = PagedMirror()
    with SessionLocal() as db:
        assert beatmap_index.synced_until(db) is None
        beatmap_index.sync_until(db, fake, date(2008, 2, 15))  # day 45: the first ranked page is enough
        assert beatmap_index.synced_until(db) >= date(2008, 2, 15)
        assert (mirror.STATUS_RANKED, 100) not in fake.calls
        assert db.get(SyncState, mirror.STATUS_APPROVED).exhausted

        beatmap_index.sync_until(db, fake, date(2008, 6, 1))  # day 152: needs the second page
        assert (mirror.STATUS_RANKED, 100) in fake.calls
        assert fake.calls.count((mirror.STATUS_RANKED, 0)) == 1  # resumed, not restarted

        beatmap_index.sync_until(db, fake, date(2030, 1, 1))
        assert db.get(SyncState, mirror.STATUS_RANKED).exhausted
        assert beatmap_index.synced_until(db) == date.max


def _seed_index(db):
    for data in [
        make_set(1, date(2009, 5, 1), [11, 12], stars=[2.0, 4.5], title="Old Song", plays=50),
        make_set(2, date(2013, 5, 1), [21, 22], stars=[5.0, 6.5], title="Mid Song", plays=500),
        make_set(3, date(2018, 5, 1), [31], stars=[7.0], title="New Song", plays=5000),
        make_set(4, date(2011, 1, 1), [41], status="graveyard"),
    ]:
        beatmap_index.upsert_set(db, data)
    db.commit()


def test_search_respects_in_game_date_and_filters():
    with SessionLocal() as db:
        _seed_index(db)
        total, results = beatmap_index.search(db, date(2014, 1, 1))
        assert total == 2
        # newest first; the graveyard set was never indexed
        assert [s.title for s, _ in results] == ["Mid Song", "Old Song"]

        total, results = beatmap_index.search(db, date(2020, 1, 1), min_stars=4, max_stars=6)
        assert {s.id: [b.id for b in d] for s, d in results} == {2: [21], 1: [12]}

        _, results = beatmap_index.search(db, date(2020, 1, 1), query="mid")
        assert [s.id for s, _ in results] == [2]
        _, results = beatmap_index.search(db, date(2020, 1, 1), sort="plays")
        assert [s.id for s, _ in results] == [3, 2, 1]
        _, results = beatmap_index.search(db, date(2020, 1, 1), sort="stars_asc")
        assert [s.id for s, _ in results] == [1, 2, 3]


def test_search_endpoint_requests_sync_when_index_is_behind(client, no_network):
    with SessionLocal() as db:
        _seed_index(db)
    resp = client.get("/api/beatmaps", params={"before": "2014-01-01", "sort": "plays"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["complete"] is False
    assert date(2014, 1, 1) in no_network.requests
    assert [s["id"] for s in data["results"]] == [2, 1]
    assert data["results"][0]["preview_url"] == "https://b.ppy.sh/preview/2.mp3"


def _player(client, start="2016-10-15"):
    return client.post("/api/players", json={"name": "U", "start_date": start}).json()["id"]


def test_cannot_submit_maps_from_the_future_or_unranked(client):
    pid = _player(client, start="2015-01-01")
    future = client.post(f"/api/players/{pid}/scores", json={"beatmap_id": 2001, "accuracy": 99})
    assert future.status_code == 409
    assert "2020-01-01" in future.json()["detail"]

    graveyard = client.post(f"/api/players/{pid}/scores", json={"beatmap_id": 3001, "accuracy": 99})
    assert graveyard.status_code == 422

    missing = client.post(f"/api/players/{pid}/scores", json={"beatmap_id": 999999, "accuracy": 99})
    assert missing.status_code == 404

    ok = client.post(f"/api/players/{pid}/scores", json={"beatmap_id": FIXTURE_BEATMAP_ID, "accuracy": 99})
    assert ok.status_code == 200, ok.text


def test_calendar_actions_request_index_sync(client, no_network):
    pid = _player(client)
    client.post(f"/api/players/{pid}/rest", json={"days": 3})
    assert no_network.requests[-1] == date(2016, 10, 18)
