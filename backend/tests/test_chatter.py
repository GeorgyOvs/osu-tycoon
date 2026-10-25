from datetime import date, timedelta

from app.db import SessionLocal
from app.models import ChatMessage, ForumThread, Player, StEvent
from app.services import chatter


def new_player(client, seed=3, start="2014-03-01", country="RU"):
    return client.post("/api/players", json=dict(name="Chat", country=country, start_date=start, seed=seed, age=17)).json()["id"]


def rest(client, pid, days):
    assert client.post(f"/api/players/{pid}/rest", json={"days": days, "physio": False}).status_code == 200


def st_events(client, pid):
    out, after = [], 0
    while True:
        page = client.get(f"/api/st/careers/{pid}/events", params={"limit": 50, "after": after}).json()
        if not page:
            return out
        out += page
        after = page[-1]["id"]


def test_ambient_events_are_scheduled_and_capped(client):
    pid = new_player(client)
    rest(client, pid, 30)
    ambient = [e for e in st_events(client, pid) if e["type"] == "AMBIENT_CHATTER"]
    assert 1 <= len(ambient) <= chatter.MAX_PENDING_AMBIENT
    e = ambient[0]
    assert set(e["prompts"]) == {"irc"} and e["schemas"]["irc"]["required"] == ["lines"]
    assert e["payload"]["data"]["topic_hint"] and e["channel"] in ("#osu", "#russian")
    with SessionLocal() as db:
        lines = db.query(ChatMessage).filter_by(player_id=pid, source="procedural").count()
        assert lines >= 6  # procedural chatter fills the channels even without the LLM


def test_ambient_prompts_carry_recent_lines_to_avoid_repeats(client):
    pid = new_player(client)
    rest(client, pid, 12)
    first = [e for e in st_events(client, pid) if e["type"] == "AMBIENT_CHATTER"][0]
    with SessionLocal() as db:
        sample = db.query(ChatMessage).filter_by(player_id=pid, channel=first["channel"]).first()
    assert sample is not None and sample.content in first["prompts"]["irc"]
    assert "do NOT repeat" in first["prompts"]["irc"]


def test_forum_ideas_and_llm_threads(client):
    pid = new_player(client, country="DE")
    for _ in range(10):
        rest(client, pid, 5)
    ideas = [e for e in st_events(client, pid) if e["type"] == "FORUM_IDEAS"]
    assert len(ideas) == 1 and "threads" in ideas[0]["prompts"] and ideas[0]["schemas"]["threads"]["required"] == ["threads"]
    with SessionLocal() as db:
        procedural = db.query(ForumThread).filter_by(player_id=pid, kind="discussion").count()
    assert procedural >= 3
    body = {"threads": [{"title": "Which tablet for flow aim?", "body": "Switching from mouse, advice?", "author": "tabby",
                         "comments": [{"author": "zed", "content": "wacom ctl-471, cheap and fine"},
                                      {"author": "mia", "content": "give it two weeks"}]}]}
    r = client.post(f"/api/st/careers/{pid}/threads", json=body)
    assert r.status_code == 200, r.text
    thread = r.json()[0]
    assert thread["title"] == "Which tablet for flow aim?" and len(thread["comments"]) == 2
    assert all(c["source"] == "llm" for c in thread["comments"])
    listed = client.get(f"/api/players/{pid}/forum", params={"kind": "discussion"}).json()
    assert any(t["title"] == "Which tablet for flow aim?" for t in listed)


def test_schedule_is_deterministic(client):
    def run():
        pid = new_player(client, seed=9)
        rest(client, pid, 20)
        return [(e["channel"], e["payload"]["data"]["topic"]) for e in st_events(client, pid) if e["type"] == "AMBIENT_CHATTER"]

    assert run() == run()


def test_pp_topics_follow_the_era():
    assert "pp_debate" not in chatter._era_topics(date(2010, 1, 1), False)
    assert "score_grind" in chatter._era_topics(date(2010, 1, 1), False)
    assert "streaming" not in chatter._era_topics(date(2010, 1, 1), False)
    assert "pp_debate" in chatter._era_topics(date(2016, 1, 1), False) and "score_grind" not in chatter._era_topics(date(2016, 1, 1), False)
