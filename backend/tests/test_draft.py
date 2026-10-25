import random

import pytest

from app.engine import match
from tests.test_tournaments import _career, _cup, _register_and_reach_start


def _pool(names=None):
    return [match.Slot(n, 6.0, beatmap_id=i + 1, title=n) for i, n in enumerate(names or match.SMALL_POOL)]


def _adv(slot):  # a likes HD/DT, b likes NM/HR
    return {"HD": 3.0, "DT": 5.0, "NM": -4.0, "HR": -2.0, "TB": 0.0}[slot.slot[:2]] + (hash(slot.slot) % 3) * 0.1


def _play(slot, decisive):
    return (600 if slot.slot[:2] in ("HD", "DT") else 400), (500), {"players": []}


def _state(**kw):
    kw.setdefault("rng_for", lambda tag: random.Random(f"t:{tag}"))
    return match.MatchState(_pool(), 5, _adv, bans_per_side=2, first_ban="a", first_pick="b", **kw)


# --- the state machine ---------------------------------------------------------------------------


def test_order_is_bans_then_alternating_picks_and_a_tiebreaker():
    st = _state()
    seq = []
    while True:
        kind, side = st.actor()
        if kind == "done":
            break
        seq.append((kind, side))
        if kind == "play":
            st.play(_play)
        else:
            st.choose()
    bans = [s for s in seq if s[0] == "ban"]
    assert [side for _, side in bans] == ["a", "b", "a"]  # 11 open maps, 8 must stay: only three bans fit
    picks = [side for kind, side in seq if kind in ("pick", "tb")]
    assert picks[0] == "b" and picks[1] == "a"  # alternating, first_pick leads
    assert all(kind in ("ban", "pick", "play", "tb") for kind, _ in seq)


def test_banned_picked_and_played_slots_are_never_legal_again():
    rng = random.Random(3)
    for trial in range(25):
        st = _state()
        taken: set[str] = set()
        while not st.done:
            kind, _ = st.actor()
            if kind == "play":
                st.play(_play)
                continue
            legal = [s.slot for s in st.legal_slots()]
            assert not taken & set(legal)
            if kind == "tb":
                st.choose()
                continue
            slot = rng.choice(legal)
            st.choose(slot)
            taken.add(slot)
        played = [m.slot for m in st.maps if m.picked_by != "tb"]
        assert len(played) == len(set(played))
        assert not set(played) & set(st.bans["a"] + st.bans["b"])


def test_choosing_a_taken_or_unknown_slot_is_rejected():
    st = _state()
    st.choose("NM1")
    assert st.bans["a"] == ["NM1"]
    with pytest.raises(ValueError):
        st.choose("NM1")
    with pytest.raises(ValueError):
        st.choose("ZZ9")
    with pytest.raises(ValueError):
        _state().choose("TB")  # the tiebreaker is never banned


def test_snapshot_restore_continues_identically():
    def run(split: bool):
        st = _state()
        humans = {"a"}
        st.run(_play, humans)
        st.choose("DT1")
        st.run(_play, humans)
        if split:
            snap = st.snapshot()
            st = _state().restore(snap)
        while not st.run(_play, humans):
            st.choose()
        return st.outcome().score_a, st.outcome().score_b, [m.slot for m in st.maps], st.bans

    assert run(False) == run(True)


def test_per_step_seeding_is_deterministic_and_wrapper_unchanged():
    def tie(slot, decisive):
        return 500, 500, {"players": [{"side": "a", "accuracy": 98.0, "misses": 0}, {"side": "b", "accuracy": 98.0, "misses": 0}]}

    one = [m.winner for m in (lambda s: (s.run(tie), s.maps)[1])(_state())]
    two = [m.winner for m in (lambda s: (s.run(tie), s.maps)[1])(_state())]
    assert one == two
    out = match.run_match(_pool(), 5, _adv, _play, random.Random(2), bans_per_side=2)
    again = match.run_match(_pool(), 5, _adv, _play, random.Random(2), bans_per_side=2)
    assert (out.score_a, out.score_b, [m.slot for m in out.maps]) == (again.score_a, again.score_b, [m.slot for m in again.maps])


def test_the_ai_bans_what_the_opponent_loves_and_keeps_its_own_picks():
    st = _state()
    st.choose()  # a (AI) bans: the slot where b's edge is largest = smallest advantage
    assert st.bans["a"] == [min((s for s in _pool() if s.slot != "TB"), key=_adv).slot]
    st.choose()  # b bans where a's edge is largest
    assert st.bans["b"] == [max((s for s in _pool() if s.slot != "TB"), key=_adv).slot]


# --- the API ------------------------------------------------------------------------------------


def _match_urls(client, pid, cup):
    pending = client.get(f"/api/players/{pid}/tournaments").json()["pending_match"]
    base = f"/api/players/{pid}/tournaments/{cup['id']}/matches/{pending['id']}"
    return pending, base


def _drive(client, base, rng=None, limit=60):
    rng = rng or random.Random(1)
    d = client.get(f"{base}/draft").json()
    for _ in range(limit):
        if d["finished"]:
            return d
        assert d["turn"]["mine"], d["turn"]
        slot = rng.choice(d["legal"])
        r = client.post(f"{base}/draft/act", json={"slot": slot})
        assert r.status_code == 200, r.text
        d = r.json()
    raise AssertionError("draft never finished")


def test_full_draft_through_the_api(client):
    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    pending, base = _match_urls(client, pid, cup)
    before = client.get(f"/api/players/{pid}/tournaments/{cup['id']}").json()
    d = client.get(f"{base}/draft").json()
    assert not d["finished"] and d["turn"]["mine"] and d["legal"] and len(d["slots"]) == 12
    assert d["names"][d["user_side"]] and d["seeds"]
    states = {s["slot"]: s["state"] for s in d["slots"]}
    assert set(d["legal"]) == {k for k, v in states.items() if v == "open"} - {"TB"}

    final = _drive(client, base)
    assert final["finished"] and max(final["score"].values()) == pending["first_to"]
    played = [s["slot"] for s in final["slots"] if s["state"] == "played"]
    banned = [s["slot"] for s in final["slots"] if s["state"] == "banned"]
    assert len(played) == len(final["maps"]) and not set(played) & set(banned)
    assert banned and all(final["log"])  # bans were made by both sides

    after = client.get(f"/api/players/{pid}/tournaments/{cup['id']}").json()
    mine = next(m for m in after["matches"] if m["id"] == pending["id"])
    assert mine["winner"] is not None and mine["score_a"] + mine["score_b"] >= pending["first_to"]
    assert mine["maps"][-1]["bans"] == final["bans"]
    assert all("winner" in x for x in mine["maps"] if "slot" in x)
    done_before = sum(1 for m in before["matches"] if m["winner"] is not None)
    done_after = sum(1 for m in after["matches"] if m["winner"] is not None)
    assert done_after >= done_before + 1
    played_matches = [m for m in after["matches"] if m["id"] == pending["id"]]
    assert len(played_matches) == 1
    # the room is closed now: no more moves, no second result
    assert client.post(f"{base}/draft/act", json={"slot": "NM1"}).status_code in (409, 422)
    assert client.post(f"{base}/play").status_code == 409


def test_a_half_played_draft_survives_reloads_and_freezes_the_calendar(client):
    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    pending, base = _match_urls(client, pid, cup)
    d = client.get(f"{base}/draft").json()
    first = d["legal"][0]
    d2 = client.post(f"{base}/draft/act", json={"slot": first}).json()
    assert [s for s in d2["slots"] if s["slot"] == first][0]["state"] == "banned"
    reload_ = client.get(f"{base}/draft").json()
    assert reload_ == d2  # nothing is replayed or re-rolled when you come back
    date_before = client.get(f"/api/players/{pid}").json()["in_game_date"]
    assert client.post(f"/api/players/{pid}/rest", json={"days": 3}).status_code == 409
    assert client.get(f"/api/players/{pid}").json()["in_game_date"] == date_before
    still = client.get(f"/api/players/{pid}/tournaments").json()["pending_match"]
    assert still and still["id"] == pending["id"]
    assert not client.get(f"/api/players/{pid}/tournaments/{cup['id']}").json()["matches"][0].get("winner_locked")


def test_illegal_moves_are_refused(client):
    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    _, base = _match_urls(client, pid, cup)
    d = client.get(f"{base}/draft").json()
    taken = next(s["slot"] for s in d["slots"] if s["state"] == "banned") if any(s["state"] == "banned" for s in d["slots"]) else None
    if taken:
        assert client.post(f"{base}/draft/act", json={"slot": taken}).status_code == 422  # the opponent already banned it
    assert client.post(f"{base}/draft/act", json={"slot": "TB"}).status_code == 422
    assert client.post(f"{base}/draft/act", json={"slot": "XX9"}).status_code == 422


def test_warmup_once_before_the_first_map(client):
    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    _, base = _match_urls(client, pid, cup)
    tired = client.get(f"/api/players/{pid}").json()["conditions"]["fatigue"]
    d = client.post(f"{base}/draft/warmup").json()
    assert d["warmup"]["used"] and not d["warmup"]["available"]
    assert client.get(f"/api/players/{pid}").json()["conditions"]["fatigue"] > tired
    assert client.post(f"{base}/draft/warmup").status_code == 409


def test_auto_finish_continues_a_draft_with_your_priorities(client):
    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    pending, base = _match_urls(client, pid, cup)
    d = client.get(f"{base}/draft").json()
    client.post(f"{base}/draft/act", json={"slot": d["legal"][0]})
    r = client.post(f"{base}/draft/auto", json={"bans": ["DT3"], "picks": ["NM1"]})
    assert r.status_code == 200, r.text
    assert r.json()["finished"]
    detail = client.get(f"/api/players/{pid}/tournaments/{cup['id']}").json()
    assert next(m for m in detail["matches"] if m["id"] == pending["id"])["winner"] is not None


def test_the_saved_draft_and_the_stored_match_agree(client):
    pid = _career(client, seed=33)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    pending, base = _match_urls(client, pid, cup)
    final = _drive(client, base, random.Random(5))
    assert client.get(f"{base}/draft").json() == final  # the finished room can still be reopened, unchanged
    stored = next(m for m in client.get(f"/api/players/{pid}/tournaments/{cup['id']}").json()["matches"] if m["id"] == pending["id"])
    assert [(x["slot"], x["score_a"], x["score_b"]) for x in stored["maps"] if "slot" in x] == \
        [(x["slot"], x["score_a"], x["score_b"]) for x in final["maps"]]


def test_forfeit_removes_the_open_draft(client):
    pid = _career(client)
    cup = _cup(client, pid)
    _register_and_reach_start(client, pid, cup)
    pending, base = _match_urls(client, pid, cup)
    client.get(f"{base}/draft")
    r = client.post(f"{base}/forfeit")
    assert r.status_code == 200, r.text
    assert client.get(f"{base}/draft").status_code == 409
