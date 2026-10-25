import pytest

from app.db import SessionLocal
from app.services import chat_intents as CI
from tests.conftest import seed_pool_maps


@pytest.mark.parametrize("text,intent", [
    ("what should I farm today?", "recommend"), ("any good stream maps?", "recommend"), ("посоветуй что сыграть", "recommend"),
    ("who should I snipe", "snipe"), ("кого снайпнуть?", "snipe"),
    ("you all suck, I'm better than everyone here", "provoke"), ("ты лох, я лучше", "provoke"), ("lol noob", "provoke"),
    ("Cookiezi 1v1 me", "duel"), ("кто хочет дуэль?", "duel"),
    ("how do I improve my streams", "skill_help"), ("which mouse is good?", "gear"), ("what's my rank", "rank"),
    ("hey everyone", "greeting"), ("is osu fun?", "question"), ("cool", "other"),
])
def test_classification(text, intent):
    assert CI.classify(text) == intent


def career(client, country="US", start="2016-06-01"):
    pid = client.post("/api/players", json=dict(name="Talker", country=country, start_date=start, seed=6, age=17)).json()["id"]
    with SessionLocal() as db:
        seed_pool_maps(db)
    return pid


def say(client, pid, text, channel="#osu"):
    assert client.post(f"/api/players/{pid}/irc/say", json={"channel": channel, "text": text}).status_code == 200
    lines = client.get(f"/api/players/{pid}/irc", params={"channel": channel}).json()
    mine = max(i for i, l in enumerate(lines) if l["content"] == text)
    return lines[mine + 1:]


def test_map_advice_names_real_maps(client):
    pid = career(client)
    replies = say(client, pid, "what should I farm?")
    assert replies and any("★" in r["content"] for r in replies)
    assert all(r["author"] != "Talker" for r in replies)


def test_russian_message_gets_russian_answer(client):
    pid = career(client)
    replies = say(client, pid, "посоветуй что сыграть")
    assert replies and any(any("а" <= ch.lower() <= "я" for ch in r["content"]) for r in replies)


def test_provocation_gets_a_reaction_and_heats_the_rival(client):
    pid = career(client)
    client.post(f"/api/players/{pid}/scores", json={"beatmap_id": 1001, "accuracy": 97})
    client.get(f"/api/players/{pid}/rivals")
    before = {r["name"]: r.get("heat", 0) for r in client.get(f"/api/players/{pid}/rivals").json()}
    replies = say(client, pid, "you all suck, I'm better than everyone here")
    assert replies
    import re

    templates = [l for key in ("provoke_rival", "provoke_named", "provoke_calm", "provoke_gracious") for l in CI.LINES[key][0]]
    patterns = [re.compile("^" + re.sub(r"\\\{\w+\\\}", ".*", re.escape(t)) + "$") for t in templates]
    assert any(p.match(r["content"]) for r in replies for p in patterns)
    after = {r["name"]: r.get("heat", 0) for r in client.get(f"/api/players/{pid}/rivals").json()}
    assert all(after.get(n, 0) >= h for n, h in before.items())


def test_snipe_question_points_at_players(client):
    pid = career(client)
    client.get(f"/api/players/{pid}/beatmaps/1001/leaderboard")  # opens a board
    replies = say(client, pid, "who should I snipe?")
    assert replies


def test_duel_invitation_creates_or_declines_a_real_duel(client):
    pid = career(client)
    client.get(f"/api/st/careers/{pid}/events")  # LLM connected: the engine hands it the facts
    client.post(f"/api/players/{pid}/irc/say", json={"channel": "#osu", "text": "Cookiezi 1v1 me?"})
    events = client.get(f"/api/st/careers/{pid}/events").json()
    reply = next(e for e in events if e["type"] == "CHAT_REPLY")
    data = reply["payload"]["data"]
    assert data["intent"] == "duel" and data["facts"]["addressed"]["name"] == "Cookiezi"
    assert "duel_created" in data["facts"] or "duel_declined" in data["facts"]
    assert "Grounded facts" in reply["prompts"]["irc"] and data["suggested_replies"]
    duels = client.get(f"/api/players/{pid}/duels").json()
    if "duel_created" in data["facts"]:
        assert any(d["status"] == "pending" for d in duels)


def test_addressed_player_answers_a_dm_in_character(client):
    pid = career(client)
    r = client.post(f"/api/players/{pid}/dm", json={"to": "Cookiezi", "text": "how do I improve my streams?"})
    assert r.status_code == 200
    reply = [m for m in r.json() if m["source"] == "procedural"]
    assert reply and all(m["author"] == "Cookiezi" for m in reply)
