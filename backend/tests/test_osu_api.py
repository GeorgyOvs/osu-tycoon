from tests.conftest import FIXTURE_BEATMAP_ID

from app.services.osu_api import NPC_ID_OFFSET

MAP = FIXTURE_BEATMAP_ID


def _career(client, name="Tester"):
    return client.post("/api/players", json={"name": name, "country": "RU", "start_date": "2016-10-15",
                                             "seed": 9}).json()["id"]


def _login(client, name="Tester", multipart=True):
    data = {"username": name, "password": "x", "grant_type": "password", "client_id": "", "scope": "*"}
    if multipart:
        resp = client.post("/oauth/token", files={k: (None, v) for k, v in data.items()})
    else:
        resp = client.post("/oauth/token", data=data)
    return resp


def _auth(client, name="Tester"):
    return {"Authorization": f"Bearer {_login(client, name).json()['access_token']}"}


def test_login_by_career_name_makes_it_active(client):
    pid = _career(client)
    _career(client, "Other")
    for multipart in (True, False):
        resp = _login(client, "tester", multipart)
        assert resp.status_code == 200 and resp.json()["token_type"] == "Bearer"
    assert client.get("/api/client/active-player").json()["player_id"] == pid
    bad = _login(client, "Nobody")
    assert bad.status_code == 401 and "Nobody" in bad.json()["hint"]
    refresh = client.post("/oauth/token", data={"grant_type": "refresh_token",
                                                "refresh_token": _login(client).json()["refresh_token"]})
    assert refresh.status_code == 200


def test_me_and_profiles(client):
    pid = _career(client)
    headers = _auth(client)
    assert client.get("/api/v2/me/osu").status_code == 401
    me = client.get("/api/v2/me/osu", headers=headers).json()
    assert me["id"] == pid and me["username"] == "Tester" and me["country_code"] == "RU"
    assert "statistics" in me and me["playmode"] == "osu"
    assert client.get(f"/api/v2/users/{pid}/osu?key=id", headers=headers).json()["username"] == "Tester"

    board = client.get(f"/api/v2/beatmaps/{MAP}/scores?type=global&mode=osu&limit=50", headers=headers).json()
    npc_score = next(s for s in board["scores"] if s["user_id"] > NPC_ID_OFFSET)
    npc = client.get(f"/api/v2/users/{npc_score['user_id']}/osu?key=id", headers=headers).json()
    assert npc["username"] == npc_score["user"]["username"]
    by_name = client.get(f"/api/v2/users/@{npc['username']}/osu?key=username", headers=headers).json()
    assert by_name["id"] == npc["id"]
    best = client.get(f"/api/v2/users/{npc['id']}/scores/best?mode=osu&limit=5", headers=headers).json()
    assert best and best[0]["beatmap_id"] == MAP and best[0]["beatmapset"]["title"]
    assert client.get(f"/api/v2/users/{NPC_ID_OFFSET + 99999}/osu", headers=headers).status_code == 404


def test_beatmap_board_shapes(client):
    _career(client)
    headers = _auth(client)
    board = client.get(f"/api/v2/beatmaps/{MAP}/scores?type=global&mode=osu&limit=50", headers=headers).json()
    scores = board["scores"]
    assert len(scores) >= 10 and board["user_score"] is None
    assert [s["total_score"] for s in scores] == sorted((s["total_score"] for s in scores), reverse=True)
    s = scores[0]
    assert s["rank"] in ("XH", "X", "SH", "S", "A", "B", "C", "D") and 0 < s["accuracy"] <= 1
    assert set(s["statistics"]) == {"great", "ok", "meh", "miss"} and s["ruleset_id"] == 0
    assert len({x["id"] for x in scores}) == len(scores)

    country = client.get(f"/api/v2/beatmaps/{MAP}/scores?type=country&mode=osu", headers=headers).json()
    assert all(x["user"]["country_code"] == "RU" for x in country["scores"])
    hd = client.get(f"/api/v2/beatmaps/{MAP}/scores?type=global&mode=osu&mods[]=HD", headers=headers).json()
    assert all([m["acronym"] for m in x["mods"]] == ["HD"] for x in hd["scores"])
    taiko = client.get(f"/api/v2/beatmaps/{MAP}/scores?type=global&mode=taiko", headers=headers).json()
    assert taiko["scores"] == []
    assert client.get("/api/v2/beatmaps/999999999/scores?type=global&mode=osu", headers=headers).json()["scores"] == []
    assert client.get("/api/v2/friends", headers=headers).json() == []


def test_submission_handshake(client):
    pid = _career(client)
    headers = _auth(client)
    token = client.post(f"/api/v2/beatmaps/{MAP}/solo/scores", headers=headers,
                        files={"ruleset_id": (None, "0"), "beatmap_hash": (None, "x")}).json()["id"]
    done = client.put(f"/api/v2/beatmaps/{MAP}/solo/scores/{token}", headers=headers,
                      json={"rank": "A", "total_score": 900000, "accuracy": 0.95, "passed": True}).json()
    assert done["id"] == token and done["user"]["id"] == pid and done["rank"] == "A"


def test_rankings(client):
    _career(client)
    headers = _auth(client)
    first = client.get("/api/v2/rankings/osu/performance?page=1", headers=headers).json()
    rows = first["ranking"]
    assert 0 < len(rows) <= 50 and first["total"] >= len(rows)
    pps = [r["pp"] for r in rows]
    assert pps == sorted(pps, reverse=True)
    top = rows[0]
    assert top["user"]["id"] > NPC_ID_OFFSET and top["is_ranked"] and 0 <= top["hit_accuracy"] <= 100
    profile = client.get(f"/api/v2/users/{top['user']['id']}/osu", headers=headers).json()
    assert profile["username"] == top["user"]["username"]
    if first["cursor"]:
        second = client.get(f"/api/v2/rankings/osu/performance?page={first['cursor']['page']}", headers=headers).json()
        assert second["ranking"] and second["ranking"][0]["pp"] <= rows[-1]["pp"]
        assert {r["user"]["id"] for r in second["ranking"]}.isdisjoint(r["user"]["id"] for r in rows)

    ru = client.get("/api/v2/rankings/osu/performance?country=RU", headers=headers).json()["ranking"]
    assert all(r["user"]["country_code"] == "RU" for r in ru)

    countries = client.get("/api/v2/rankings/osu/country", headers=headers).json()["ranking"]
    perf = [c["performance"] for c in countries]
    assert countries and perf == sorted(perf, reverse=True) and all(len(c["code"]) == 2 for c in countries)
    assert client.get("/api/v2/rankings/taiko/performance", headers=headers).json()["ranking"] == []


def test_submission_reports_career_pp_and_place(client):
    pid = _career(client)
    headers = _auth(client)
    body = {"client_score_id": "d" * 32, "beatmap_id": MAP, "beatmap_md5": "a" * 32, "artist": "A", "title": "T",
            "version": "N", "mods": ["HD"], "great": 190, "ok": 8, "meh": 1, "miss": 1, "max_combo": 150,
            "accuracy": 0.9683, "total_score": 912345, "status": "passed", "progress": 1.0,
            "played_at": "2026-10-25T12:00:00Z"}
    assert client.post("/api/client/scores", json=body).json()["career_score_id"]
    token = client.post(f"/api/v2/beatmaps/{MAP}/solo/scores", headers=headers).json()["id"]
    done = client.put(f"/api/v2/beatmaps/{MAP}/solo/scores/{token}", headers=headers,
                      json={"rank": "A", "total_score": 912345, "accuracy": 0.9683, "passed": True}).json()
    assert done["pp"] > 0 and isinstance(done["position"], int) and done["position"] >= 1 and done["ranked"]
    board = client.get(f"/api/v2/beatmaps/{MAP}/scores?type=global&mode=osu", headers=headers).json()
    assert board["user_score"]["position"] == done["position"] and board["user_score"]["score"]["user_id"] == pid


def test_career_screens(client):
    _career(client)
    headers = _auth(client)
    career = client.get("/api/v2/tycoon/career", headers=headers).json()
    assert career["name"] == "Tester" and career["date"] == "2016-10-15" and career["groups"] and career["drills"]
    assert career["hand_day"]["attempts"] == 0
    drill = next(d for d in career["drills"] if d["available"] and not d["sets_scores"])
    trained = client.post("/api/v2/tycoon/train", headers=headers,
                          json={"drill": drill["key"], "hours_per_day": 2, "days": 2})
    assert trained.status_code == 200, trained.text
    assert trained.json()["days"] == 2 and trained.json()["end_date"] > "2016-10-15"
    rested = client.post("/api/v2/tycoon/rest", headers=headers, json={"days": 1}).json()
    assert rested["days"] == 1
    assert client.get("/api/v2/tycoon/career", headers=headers).json()["date"] == rested["end_date"]
    bad = client.post("/api/v2/tycoon/train", headers=headers, json={"drill": "nope", "hours_per_day": 2, "days": 1})
    assert bad.status_code >= 400 and "error" in bad.json()
    nothing = client.post("/api/v2/tycoon/hand-day/finish", headers=headers)
    assert nothing.status_code == 409 and nothing.json()["error"]


def test_career_screens_speak_russian(client):
    import pytest
    from app.services import translate
    if translate.ru1("Healthy") == "Healthy":
        pytest.skip("node or the i18n bundle (npm run build:i18n) isn't available")
    _career(client)
    headers = _auth(client)
    career = client.get("/api/v2/tycoon/career", headers=headers).json()
    assert career["injury_label"] == "Здоров"
    assert any(g["label"] != g["key"].capitalize() for g in career["groups"])  # translated group names
    bad = client.post("/api/v2/tycoon/train", headers=headers, json={"drill": "nope", "hours_per_day": 2, "days": 1})
    assert bad.status_code >= 400


def test_world_and_bracket_screens(client):
    _career(client)
    headers = _auth(client)
    world = client.get("/api/v2/tycoon/world", headers=headers).json()
    assert world["procedural"] > 0 and world["ranked"] > 0 and isinstance(world["news"], list)
    grown = client.post("/api/v2/tycoon/world/grow", headers=headers, json={"size": world["procedural"] + 200}).json()
    assert grown["added"] == 200 and grown["procedural"] == world["procedural"] + 200
    assert client.post("/api/v2/tycoon/world/grow", headers=headers, json={"size": 10}).json()["added"] == 0
    assert client.post("/api/v2/tycoon/world/grow", headers=headers, json={"size": 999999}).status_code == 422
    ranking = client.get("/api/v2/rankings/osu/performance", headers=headers).json()
    assert ranking["total"] >= world["ranked"]

    listing = client.get("/api/v2/tycoon/tournaments", headers=headers).json()
    cup = listing["tournaments"][0]
    bracket = client.get(f"/api/v2/tycoon/tournaments/{cup['id']}/bracket", headers=headers).json()
    assert bracket["name"] == cup["name"]
    for r in bracket["rounds"]:
        assert r["side"] in ("upper", "lower", "final") and r["matches"]


def test_forum_and_life_screens(client):
    _career(client)
    headers = _auth(client)
    threads = client.get("/api/v2/tycoon/forum", headers=headers).json()
    assert isinstance(threads, list)
    if threads:
        thread = client.get(f"/api/v2/tycoon/forum/{threads[0]['id']}", headers=headers).json()
        assert thread["title"] and "comments" in thread
    assert client.get("/api/v2/tycoon/forum/999999", headers=headers).status_code == 404

    life = client.get("/api/v2/tycoon/life", headers=headers).json()
    assert life["occupation"] in [o["key"] for o in life["occupations"]] and life["shop"]
    assert all(i["available"] or i["owned"] for i in life["shop"])
    assert client.post("/api/v2/tycoon/life/occupation", headers=headers, json={"occupation": "work"}).status_code == 200
    assert client.get("/api/v2/tycoon/life", headers=headers).json()["occupation"] == "work"
    assert client.post("/api/v2/tycoon/life/occupation", headers=headers, json={"occupation": "astronaut"}).status_code >= 400

    cheap = min((i for i in life["shop"] if not i["owned"]), key=lambda i: i["price"])
    bought = client.post(f"/api/v2/tycoon/life/shop/{cheap['key']}/buy", headers=headers)
    if cheap["price"] <= life["money"]:
        assert bought.status_code == 200
        assert next(i for i in client.get("/api/v2/tycoon/life", headers=headers).json()["shop"] if i["key"] == cheap["key"])["owned"]
    else:
        assert bought.status_code >= 400 and "error" in bought.json()
    style = client.post("/api/v2/tycoon/life/playstyle", headers=headers, json={"tap_style": "singletap"})
    assert style.status_code == 200


def test_trailing_slash_paths_keep_the_login(client):
    pid = _career(client)
    headers = _auth(client)
    me = client.get("/api/v2/me/", headers=headers, follow_redirects=False)
    assert me.status_code == 200 and me.json()["id"] == pid
    assert client.get(f"/api/v2/users/{pid}/?key=id", headers=headers, follow_redirects=False).status_code == 200


def test_beatmap_listing_is_the_careers_world(client):
    from datetime import date
    from app.db import SessionLocal
    from tests.conftest import seed_pool_maps
    with SessionLocal() as db:
        seed_pool_maps(db, n=120)
    _career(client)  # 2016-10-15
    headers = _auth(client)
    first = client.get("/api/v2/beatmapsets/search?m=0&s=leaderboard&sort=ranked_desc", headers=headers).json()
    sets = first["beatmapsets"]
    assert sets and first["total"] >= len(sets) and len(sets) <= 50
    dates = [x["ranked_date"][:10] for x in sets]
    assert dates == sorted(dates, reverse=True) and all(d <= "2016-10-15" for d in dates)
    s0 = sets[0]
    assert s0["beatmaps"] and s0["covers"]["card"].startswith("https://") and s0["status"] in ("ranked", "approved")
    if first["cursor"]:
        nxt = client.get(f"/api/v2/beatmapsets/search?sort=ranked_desc&cursor[offset]={first['cursor']['offset']}",
                         headers=headers).json()
        assert {x["id"] for x in nxt["beatmapsets"]}.isdisjoint(x["id"] for x in sets)
    word = s0["title"].split()[0]
    found = client.get(f"/api/v2/beatmapsets/search?q={word}", headers=headers).json()["beatmapsets"]
    assert any(x["id"] == s0["id"] for x in found)
    by_title = client.get("/api/v2/beatmapsets/search?sort=title_asc", headers=headers).json()["beatmapsets"]
    titles = [x["title"] for x in by_title]
    assert titles == sorted(titles, key=lambda t: t)  # SQLite sorts the same way
    assert client.get("/api/v2/beatmapsets/search?m=1", headers=headers).json()["beatmapsets"] == []
    assert client.get("/api/v2/beatmapsets/search?s=graveyard", headers=headers).json()["beatmapsets"] == []
    assert client.get(f"/api/v2/beatmapsets/{s0['id']}", headers=headers).json()["title"] == s0["title"]
    lookup = client.get(f"/api/v2/beatmapsets/lookup?beatmap_id={s0['beatmaps'][0]['id']}", headers=headers).json()
    assert lookup["id"] == s0["id"]
    with SessionLocal() as db:
        from app.models import BeatmapSet
        future = db.query(BeatmapSet).filter(BeatmapSet.ranked_date > date(2016, 10, 15)).first()
    if future:
        assert client.get(f"/api/v2/beatmapsets/{future.id}", headers=headers).status_code == 404
    assert client.get("/api/v2/tycoon/date", headers=headers).json()["date"] == "2016-10-15"


def test_loved_maps_are_listed_but_never_give_pp(client):
    from datetime import date
    from app.db import SessionLocal
    from app.models import Beatmap, BeatmapSet
    from app.services import beatmap_index, mirror
    from tests.conftest import FIXTURE_BEATMAP_ID, make_osu_file
    from app.config import OSU_CACHE_DIR

    loved_set, loved_map = 777001, 777002
    with SessionLocal() as db:
        bset = BeatmapSet(id=loved_set, artist="Loved Artist", title="Loved Song", creator="m", status="loved",
                          ranked_date=date(2016, 1, 1), play_count=5, favourite_count=1, bpm=180)
        bset.beatmaps.append(Beatmap(id=loved_map, version="Insane", stars=5.0, ar=9, cs=4, od=8, hp=6, bpm=180,
                                     total_length=120, hit_length=110, max_combo=500, count_circles=300,
                                     count_sliders=100))
        db.add(bset)
        db.commit()
    (OSU_CACHE_DIR / f"{loved_map}.osu").write_text(make_osu_file(loved_map, loved_set), encoding="utf-8")
    assert mirror.STATUS_LOVED in beatmap_index.SYNC_STATUSES

    pid = _career(client)
    headers = _auth(client)
    loved = client.get("/api/v2/beatmapsets/search?s=loved", headers=headers).json()["beatmapsets"]
    assert [x["id"] for x in loved] == [loved_set] and loved[0]["status"] == "loved"
    ranked_only = client.get("/api/v2/beatmapsets/search?s=ranked&q=Loved", headers=headers).json()["beatmapsets"]
    assert ranked_only == []
    anything = client.get("/api/v2/beatmapsets/search?s=any&q=Loved", headers=headers).json()["beatmapsets"]
    assert [x["id"] for x in anything] == [loved_set]
    assert client.get(f"/api/v2/beatmaps/{loved_map}/scores?type=global&mode=osu", headers=headers).json()["scores"] == []

    # playing it by hand costs time but is never a career score
    client.put("/api/client/active-player", json={"player_id": pid})
    play = client.post("/api/client/scores", json={
        "client_score_id": "e" * 32, "beatmap_id": loved_map, "beatmap_md5": "a" * 32, "artist": "Loved Artist",
        "title": "Loved Song", "version": "Insane", "mods": [], "great": 190, "ok": 8, "meh": 1, "miss": 1,
        "max_combo": 150, "accuracy": 0.97, "total_score": 900000, "status": "passed", "progress": 1.0,
        "played_at": "2026-10-25T12:00:00Z"}).json()
    assert play["career_score_id"] is None and "loved" in play["career_note"]
    assert client.get(f"/api/players/{pid}/hand-day").json()["attempts"] == 1
    # and the web search (pp maps) doesn't offer it
    with SessionLocal() as db:
        total, _ = beatmap_index.search(db, date(2016, 10, 15), "Loved")
    assert total == 0


def test_beatmap_lookup_by_md5(client, monkeypatch):
    from app.services import beatmap_index, beatmap_lookup
    from tests.conftest import FIXTURE_BEATMAP_ID
    _career(client)
    headers = _auth(client)
    md5 = "0123456789abcdef0123456789abcdef"

    class Mirror:
        calls = 0

        def get_beatmap_by_md5(self, checksum):
            Mirror.calls += 1
            return {"id": FIXTURE_BEATMAP_ID, "beatmapset_id": 1, "status": "ranked", "checksum": checksum} \
                if checksum == md5 else None

        def get_set(self, set_id):
            return None

    monkeypatch.setattr(beatmap_index, "default_client", lambda: Mirror())
    beatmap_lookup._unknown.clear()
    beatmap_lookup._outside_index.clear()
    found = client.get(f"/api/v2/beatmaps/lookup?checksum={md5}&filename=x.osu", headers=headers).json()
    assert found["id"] == FIXTURE_BEATMAP_ID and found["checksum"] == md5 and found["beatmapset"]["status"]
    again = client.get(f"/api/v2/beatmaps/lookup?checksum={md5}", headers=headers).json()
    assert again["id"] == FIXTURE_BEATMAP_ID and Mirror.calls == 1  # remembered: no second mirror call
    unknown = "f" * 32
    assert client.get(f"/api/v2/beatmaps/lookup?checksum={unknown}", headers=headers).status_code == 404
    assert client.get(f"/api/v2/beatmaps/lookup?checksum={unknown}", headers=headers).status_code == 404
    assert Mirror.calls == 2  # an unknown md5 is only asked once a day
    assert client.get("/api/v2/beatmaps/lookup?id=999999999", headers=headers).status_code == 404
    assert client.get("/api/v2/users/1/recent_activity", headers=headers).json() == []


def test_everyone_has_an_avatar_of_the_world(client, tmp_path, monkeypatch):
    from app.services import avatars
    _career(client)
    headers = _auth(client)
    board = client.get(f"/api/v2/beatmaps/{MAP}/scores?type=global&mode=osu", headers=headers).json()
    urls = [s["user"]["avatar_url"] for s in board["scores"]]
    assert all(u and "/api/avatars/" in u for u in urls)
    me = client.get("/api/v2/me/osu", headers=headers).json()
    assert me["avatar_url"].endswith("/api/avatars/Tester.png")

    png = client.get("/api/avatars/Tester.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/api/avatars/Tester.png").content == png.content  # the same person, the same face
    assert client.get("/api/avatars/Somebody.png").content != png.content
    legend = client.get("/api/avatars/Tester.png?legend=1").content
    assert legend != png.content  # legends get a gold frame

    monkeypatch.setattr(avatars, "AVATAR_DIR", tmp_path)
    (tmp_path / "tester.JPG").write_bytes(b"\xff\xd8custom")
    custom = client.get("/api/avatars/Tester.png")
    assert custom.content == b"\xff\xd8custom" and custom.headers["content-type"] == "image/jpeg"
