import random

from tests.test_tournaments import _career, _cup, _register_and_reach_start


def _login(client, name="Tour"):
    token = client.post("/oauth/token", data={"username": name, "password": "x", "grant_type": "password"}).json()
    return {"Authorization": f"Bearer {token['access_token']}"}


def _send(client, n, awaiting, mods, accuracy=0.97):
    pairs = [mods[i:i + 2] for i in range(0, len(mods), 2)]
    body = {"client_score_id": f"{n:032x}", "beatmap_id": awaiting["beatmap_id"], "beatmap_md5": "a" * 32,
            "artist": "A", "title": awaiting["title"], "version": "X", "mods": pairs,
            "great": 180, "ok": 15, "meh": 2, "miss": 3, "max_combo": 120, "accuracy": accuracy,
            "total_score": 700000 + n, "status": "passed", "progress": 1.0, "played_at": "2026-10-25T12:00:00Z"}
    r = client.post("/api/client/scores", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_match_played_by_hand(client):
    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    headers = _login(client)

    listing = client.get("/api/v2/tycoon/tournaments", headers=headers).json()
    assert listing["pending"] and listing["pending"]["opponent"] and listing["pending"]["playable"]
    d = client.post("/api/v2/tycoon/draft/hand", headers=headers, json={"on": True}).json()
    assert d["hand"] is True and not d["finished"]

    rng = random.Random(3)
    n, wrong_mods_tried, simulated_one = 0, False, False
    for _ in range(80):
        if d["finished"]:
            break
        if d["awaiting"]:
            a = d["awaiting"]
            if not wrong_mods_tried:  # the wrong mods don't count, the map keeps waiting
                wrong = "HR" if a["mods"] != "HR" else "HD"
                n += 1
                note = _send(client, n, a, wrong)["career_note"]
                assert note.startswith("match map not counted")
                again = client.get("/api/v2/tycoon/draft", headers=headers).json()
                assert again["awaiting"]["slot"] == a["slot"]
                wrong_mods_tried = True
            if not simulated_one and d["my_score"] + d["their_score"] == 1:
                d = client.post("/api/v2/tycoon/draft/simulate-map", headers=headers).json()
                simulated_one = True
                continue
            n += 1
            note = _send(client, n, a, a["mods"] + "NF")["career_note"]
            assert note.startswith(f"match map {a['slot']}:")
            d = client.get("/api/v2/tycoon/draft", headers=headers).json()
            assert "slots" in d, d
            played = next(s for s in d["slots"] if s["slot"] == a["slot"])
            assert played["state"] == "played" and played["my_score"] is not None
        elif d["my_turn"]:
            d = client.post("/api/v2/tycoon/draft/act", headers=headers, json={"slot": rng.choice(d["legal"])}).json()
        else:
            raise AssertionError(f"stuck: {d['turn']}")
    assert d["finished"] and max(d["my_score"], d["their_score"]) == listing["pending"]["first_to"]
    assert wrong_mods_tried and simulated_one

    # the stored match shows which maps were played by hand
    detail = client.get(f"/api/players/{pid}/tournaments/{cup['id']}").json()
    match = next(m for m in detail["matches"] if m["id"] == listing["pending"]["match_id"])
    hand_maps = [x for x in match["maps"] if "slot" in x and any(p.get("hand") for p in x["players"])]
    assert len(hand_maps) == len([x for x in match["maps"] if "slot" in x]) - 1  # all but the simulated one


def test_hand_mode_off_simulates_the_waiting_map(client):
    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    headers = _login(client)
    d = client.post("/api/v2/tycoon/draft/hand", headers=headers, json={"on": True}).json()
    rng = random.Random(5)
    while not d["awaiting"]:
        d = client.post("/api/v2/tycoon/draft/act", headers=headers, json={"slot": rng.choice(d["legal"])}).json()
    d = client.post("/api/v2/tycoon/draft/hand", headers=headers, json={"on": False}).json()
    assert d["awaiting"] is None and any(s["state"] == "played" for s in d["slots"])


def test_beatmap_download_goes_to_the_mirror(client):
    _career(client)
    headers = _login(client)
    r = client.get("/api/v2/beatmapsets/123/download?noVideo=1", headers=headers, follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"].endswith("/d/123")
