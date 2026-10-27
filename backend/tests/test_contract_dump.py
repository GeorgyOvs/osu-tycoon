"""Dumps real responses for the tycoon client's contract test (osu.Game.Tests/Resources/Tycoon in the fork).

Skipped unless CONTRACT_DUMP_DIR is set:  CONTRACT_DUMP_DIR=... python -m pytest tests/test_contract_dump.py
The fork's TestTycoonContract then parses every file with lazer's own response classes.
"""
import json
import os
import random
from pathlib import Path

import pytest

from tests.test_tournaments import _cup, _register_and_reach_start
from tests.test_tournaments import _career as _tour_career

OUT = os.environ.get("CONTRACT_DUMP_DIR")


@pytest.mark.skipif(not OUT, reason="set CONTRACT_DUMP_DIR to dump responses for the client contract test")
def test_dump_client_contract(client):
    from app.db import SessionLocal
    from app.models import Beatmap
    from tests.conftest import FIXTURE_BEATMAP_ID, seed_pool_maps

    out = Path(OUT)
    out.mkdir(parents=True, exist_ok=True)

    def save(name, resp):
        assert resp.status_code == 200, (name, resp.status_code, resp.text[:300])
        (out / f"{name}.json").write_text(json.dumps(resp.json(), ensure_ascii=False, indent=1), encoding="utf-8")
        return resp.json()

    pid = _tour_career(client)
    with SessionLocal() as db:
        seed_pool_maps(db, n=60)
    cup = _cup(client, pid)
    token = client.post("/oauth/token", data={"username": "Tour", "password": "x", "grant_type": "password"})
    save("oauth_token", token)
    h = {"Authorization": f"Bearer {token.json()['access_token']}"}

    # a career score on the fixture map so the board has the user's row
    client.put("/api/client/active-player", json={"player_id": pid})
    client.post("/api/client/scores", json={
        "client_score_id": "a" * 32, "beatmap_id": FIXTURE_BEATMAP_ID, "beatmap_md5": "b" * 32, "artist": "A",
        "title": "T", "version": "N", "mods": ["HD"], "great": 190, "ok": 8, "meh": 1, "miss": 1, "max_combo": 150,
        "accuracy": 0.97, "total_score": 900000, "status": "passed", "progress": 1.0,
        "played_at": "2026-10-25T12:00:00Z"})

    me = save("me", client.get("/api/v2/me/osu", headers=h))
    board = save("beatmap_scores", client.get(f"/api/v2/beatmaps/{FIXTURE_BEATMAP_ID}/scores?type=global&mode=osu", headers=h))
    npc_id = next(s["user_id"] for s in board["scores"] if s["user_id"] > 1_000_000)
    save("user_npc", client.get(f"/api/v2/users/{npc_id}/osu?key=id", headers=h))
    save("user_scores_best", client.get(f"/api/v2/users/{npc_id}/scores/best?mode=osu&limit=5", headers=h))
    save("user_scores_best_me", client.get(f"/api/v2/users/{me['id']}/scores/best?mode=osu&limit=5", headers=h))
    save("rankings", client.get("/api/v2/rankings/osu/performance?page=1", headers=h))
    save("rankings_country", client.get("/api/v2/rankings/osu/country?page=1", headers=h))
    search = save("beatmapsets_search", client.get("/api/v2/beatmapsets/search?m=0&s=leaderboard", headers=h))
    set_id = search["beatmapsets"][0]["id"]
    save("beatmapset", client.get(f"/api/v2/beatmapsets/{set_id}", headers=h))
    with SessionLocal() as db:
        b = db.get(Beatmap, search["beatmapsets"][0]["beatmaps"][0]["id"])
        b.checksum = "c" * 32
        db.commit()
    save("beatmap_lookup", client.get(f"/api/v2/beatmaps/lookup?checksum={'c' * 32}", headers=h))
    tok = save("solo_token", client.post(f"/api/v2/beatmaps/{FIXTURE_BEATMAP_ID}/solo/scores", headers=h))
    save("solo_submit", client.put(f"/api/v2/beatmaps/{FIXTURE_BEATMAP_ID}/solo/scores/{tok['id']}", headers=h,
                                   json={"rank": "A", "total_score": 900000, "accuracy": 0.97, "passed": True}))
    save("friends", client.get("/api/v2/friends", headers=h))

    # career screens
    save("tycoon_career", client.get("/api/v2/tycoon/career", headers=h))
    save("tycoon_date", client.get("/api/v2/tycoon/date", headers=h))
    save("tycoon_world", client.get("/api/v2/tycoon/world", headers=h))
    save("tycoon_life", client.get("/api/v2/tycoon/life", headers=h))
    save("tycoon_forum", client.get("/api/v2/tycoon/forum", headers=h))
    save("tycoon_tournaments", client.get("/api/v2/tycoon/tournaments", headers=h))
    save("tycoon_bracket", client.get(f"/api/v2/tycoon/tournaments/{cup['id']}/bracket", headers=h))
    save("tycoon_rest", client.post("/api/v2/tycoon/rest", headers=h, json={"days": 1}))
    _register_and_reach_start(client, pid, cup)
    save("tycoon_tournaments_pending", client.get("/api/v2/tycoon/tournaments", headers=h))
    d = save("tycoon_draft", client.post("/api/v2/tycoon/draft/hand", headers=h, json={"on": True}))
    rng = random.Random(1)
    while not d["awaiting"]:
        d = client.post("/api/v2/tycoon/draft/act", headers=h, json={"slot": rng.choice(d["legal"])}).json()
    (out / "tycoon_draft_awaiting.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    client.post("/api/v2/tycoon/draft/hand", headers=h, json={"on": False})
    client.post("/api/v2/tycoon/draft/auto", headers=h)
    watch = save("tycoon_watch", client.get("/api/v2/tycoon/watch", headers=h))
    item = next(x for x in watch if x["watchable"])
    save("tycoon_watch_map", client.get(f"/api/v2/tycoon/watch/{item['kind']}/{item['id']}/0", headers=h))
    save("assist", client.get("/api/client/assist"))
    save("character_play", client.get(f"/api/client/character-play?beatmap_id={FIXTURE_BEATMAP_ID}&mods=HD"))
    save("character_play_series", client.post(f"/api/client/character-play?beatmap_id={FIXTURE_BEATMAP_ID}&mods=HD&attempts=2"))
