import random

from tests.test_tournaments import _career, _cup, _register_and_reach_start


def _login(client, name="Tour"):
    token = client.post("/oauth/token", data={"username": name, "password": "x", "grant_type": "password"}).json()
    return {"Authorization": f"Bearer {token['access_token']}"}


def _play_match(client, headers, hand_first_map=False):
    d = client.post("/api/v2/tycoon/draft/hand", headers=headers, json={"on": hand_first_map}).json()
    rng = random.Random(4)
    n = 0
    while not d["finished"]:
        if d["awaiting"]:
            a = d["awaiting"]
            n += 1
            client.post("/api/client/scores", json={
                "client_score_id": f"{n:032x}", "beatmap_id": a["beatmap_id"], "beatmap_md5": "a" * 32,
                "artist": "A", "title": a["title"], "version": "X", "mods": [a["mods"][i:i + 2] for i in range(0, len(a["mods"]), 2)] + ["NF"],
                "great": 150, "ok": 20, "meh": 3, "miss": 4, "max_combo": 90, "accuracy": 0.93,
                "total_score": 600000 + n, "status": "passed", "progress": 1.0, "played_at": "2026-10-25T12:00:00Z"})
            d = client.post("/api/v2/tycoon/draft/hand", headers=headers, json={"on": False}).json()  # rest simulated
        elif d["my_turn"]:
            d = client.post("/api/v2/tycoon/draft/act", headers=headers, json={"slot": rng.choice(d["legal"])}).json()
        else:
            raise AssertionError(d["turn"])
    return d


def test_watch_a_played_match(client):
    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    headers = _login(client)
    _play_match(client, headers, hand_first_map=True)

    listing = client.get("/api/v2/tycoon/watch", headers=headers).json()
    match = next(x for x in listing if x["kind"] == "match")
    assert match["watchable"] and match["maps"] >= 4 and match["opponent"]

    hand_seen = sim_seen = False
    for index in range(match["maps"]):
        view = client.get(f"/api/v2/tycoon/watch/match/{match['id']}/{index}", headers=headers).json()
        assert view["beatmap_id"] and len(view["players"]) == 2 and view["names"]["a"] and view["names"]["b"]
        assert sum(view["after"].values()) == sum(view["before"].values()) + 1
        for p in view["players"]:
            assert p["objects"] and "flow" in p["knobs"] and p["avatar_url"] and p["side"] in ("a", "b")
            assert all(o["result"] in ("great", "ok", "meh", "miss", "sliderbreak", "sliderend") for o in p["objects"])
            if p["reconstructed"]:
                hand_seen = True
                assert sum(o["result"] == "miss" for o in p["objects"]) == p["misses"]
            else:
                sim_seen = True
                assert p["knobs"]["aim"] > 0
    assert hand_seen and sim_seen
    assert client.get(f"/api/v2/tycoon/watch/match/{match['id']}/99", headers=headers).status_code == 404
    assert client.get("/api/v2/tycoon/watch/match/999999/0", headers=headers).status_code == 404


def test_watch_an_npc_match(client):
    from app.db import SessionLocal
    from app.models import Match, Tournament

    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    client.post("/api/v2/tycoon/draft/auto", headers=_login(client))  # the user's match; NPC matches run alongside
    client.post(f"/api/players/{pid}/rest", json={"days": 8})
    headers = _login(client)
    bracket = client.get(f"/api/v2/tycoon/tournaments/{cup['id']}/bracket", headers=headers).json()
    npc_match = next(x for r in bracket["rounds"] for x in r["matches"] if x["watchable"] and not x["mine"])

    first = client.get(f"/api/v2/tycoon/watch/match/{npc_match['id']}/0", headers=headers).json()
    assert len(first["players"]) == 2 and all(p["objects"] and not p["reconstructed"] for p in first["players"])
    winner = first["winner"]
    assert (first["score_a"] > first["score_b"]) == (winner == "a")  # the note-by-note result is the recorded one
    again = client.get(f"/api/v2/tycoon/watch/match/{npc_match['id']}/0", headers=headers).json()
    assert again["players"][0]["objects"] == first["players"][0]["objects"]  # kept: it replays the same

    # a match from before maps were kept: rebuilt so it still ends with its real score
    with SessionLocal() as db:
        m = db.get(Match, npc_match["id"])
        final = (m.score_a, m.score_b)
        m.maps = []
        db.commit()
    rebuilt = [client.get(f"/api/v2/tycoon/watch/match/{npc_match['id']}/{i}", headers=headers).json()
               for i in range(sum(final))]
    assert (rebuilt[-1]["after"]["a"], rebuilt[-1]["after"]["b"]) == final


def test_slider_mistakes_survive_in_match_traces():
    from types import SimpleNamespace
    from app.engine.replay import Trace
    from app.services import match_watch, tournaments

    trace = Trace()
    for points, slider in ((300, ""), (100, "b"), (100, "e"), (0, "")):
        trace.add(1, 1.0, points, "aim" if points == 0 else "", 4.0, slider)
    out = tournaments.trace_json(SimpleNamespace(trace=trace), 1.0)
    assert out["points"] == "3110" and out["sliders"] == {"1": "b", "2": "e"}
    results = [match_watch.SLIDER_RESULTS.get(out["sliders"].get(str(k), "")) or match_watch.RESULTS[c]
               for k, c in enumerate(out["points"])]
    assert results == ["great", "sliderbreak", "sliderend", "miss"]
