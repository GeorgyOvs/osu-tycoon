from datetime import date

from app.db import SessionLocal
from app.models import Player, StEvent
from app.services import media
from app.services.tournaments import News
from app.services import st_prompts
from tests.conftest import FIXTURE_BEATMAP_ID


import pytest


def test_forum_schema_uses_optional_scalar_reply_to_for_google_response_schema():
    comments = st_prompts.FORUM_SCHEMA['properties']['comments']['items']
    assert comments['properties']['reply_to']['type'] == 'integer'
    assert 'reply_to' not in comments['required']
    from app.schemas import LlmComment
    assert LlmComment(author='User', content='gz').reply_to is None
    assert LlmComment(author='User', content='reply', reply_to=0).reply_to == 0

    def check(schema):
        assert isinstance(schema['type'], str)
        for child in schema.get('properties', {}).values():
            check(child)
        if 'items' in schema:
            check(schema['items'])
    check(st_prompts.FORUM_SCHEMA)
    check(st_prompts.IRC_SCHEMA)


@pytest.fixture
def any_score_is_news(monkeypatch):
    """The fixture map is easy, so its pp would never impress the community; lower the bar."""
    monkeypatch.setattr(media, "SCOREPOST_MIN_SIGNIFICANCE", 0.0)


def _career(client, start="2016-10-15"):
    return client.post("/api/players", json={"name": "Tester", "country": "RU", "start_date": start, "seed": 3}).json()


def _first_score(client, pid, misses=2):
    resp = client.post(f"/api/players/{pid}/scores",
                       json={"beatmap_id": FIXTURE_BEATMAP_ID, "mods": "HD", "accuracy": 97.5, "misses": misses})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_ordinary_scores_are_not_news(client):
    pid = _career(client)["id"]
    _first_score(client, pid)
    assert client.get(f"/api/players/{pid}/forum").json() == []
    assert client.get(f"/api/st/careers/{pid}/events").json() == []


def test_new_top_play_becomes_a_scorepost(client, any_score_is_news):
    pid = _career(client)["id"]
    score = _first_score(client, pid)["score"]

    threads = client.get(f"/api/players/{pid}/forum").json()
    assert len(threads) == 1
    t = threads[0]
    assert t["kind"] == "scorepost" and t["board"] == "r/osugame"
    # Player | Artist - Title [Diff] +MODS (acc%) combo/maxx NxMiss | pp (fc pp) | tag
    assert t["title"].startswith("Tester | Test Artist - Test Song [Insane] +HD (97.50%) ")
    assert "2xMiss" in t["title"] and "pp if FC" in t["title"] and t["title"].endswith("Their new top play!")
    assert t["comment_count"] >= 2 and t["llm_status"] == "pending"

    irc = client.get(f"/api/players/{pid}/irc", params={"channel": "#russian"}).json()
    assert irc and all(m["source"] == "procedural" for m in irc)
    assert "#russian" in client.get(f"/api/players/{pid}/irc/channels").json()

    events = client.get(f"/api/st/careers/{pid}/events").json()
    assert len(events) == 1
    e = events[0]
    assert e["type"] == "SCORE_SUBMISSION"
    data = e["payload"]["data"]
    assert e["payload"]["event_type"] == "SCORE_SUBMISSION"
    assert data["in_game_date"] == "2016-10-15"
    assert data["player"]["name"] == "Tester"
    assert data["score"]["pp_earned"] == round(score["pp"], 2)
    assert data["score"]["is_new_top_play"] is True
    assert data["reddit_thread_spec"]["upvotes"] >= 1
    assert set(e["prompts"]) == {"forum", "irc", "narration"}
    assert "JSON only" in e["prompts"]["forum"] and e["schemas"]["forum"]["required"] == ["comments"]


def test_worse_score_makes_no_thread(client, any_score_is_news):
    pid = _career(client)["id"]
    _first_score(client, pid, misses=0)
    _first_score(client, pid, misses=20)
    assert len(client.get(f"/api/players/{pid}/forum").json()) == 1


def test_llm_results_flow_back(client, any_score_is_news):
    pid = _career(client)["id"]
    _first_score(client, pid)
    e = client.get(f"/api/st/careers/{pid}/events").json()[0]
    tid = e["thread"]["id"]

    resp = client.post(f"/api/st/careers/{pid}/threads/{tid}/comments", json={"comments": [
        {"author": "cookiefan", "content": "how is this legal", "upvotes": 50},
        {"author": "Tester", "content": "thanks guys", "reply_to": 0},
    ]})
    assert resp.status_code == 200, resp.text
    t = resp.json()
    assert t["llm_status"] == "done"
    llm = [c for c in t["comments"] if c["source"] == "llm"]
    assert llm[1]["parent_id"] == llm[0]["id"]

    lines = client.post(f"/api/st/careers/{pid}/irc",
                        json={"channel": "#osu", "lines": [{"author": "rrtyui", "content": "plz enjoy game"}]})
    assert lines.status_code == 200
    assert any(m["content"] == "plz enjoy game" for m in client.get(f"/api/players/{pid}/irc").json())

    assert client.post(f"/api/st/careers/{pid}/events/{e['id']}/ack").status_code == 204
    assert client.get(f"/api/st/careers/{pid}/events").json() == []
    assert len(client.get(f"/api/st/careers/{pid}/events", params={"include_handled": True}).json()) == 1


def test_context_summarises_the_career(client):
    pid = _career(client)["id"]
    _first_score(client, pid)
    text = client.get(f"/api/st/careers/{pid}/context").json()["text"]
    assert "Tester [RU]" in text and "2016-10-15" in text
    assert "Top plays:" in text and "Current global top 5:" in text
    assert any(c["id"] == pid for c in client.get("/api/st/careers").json())


def test_milestones_and_headlines(client):
    pid = _career(client)["id"]
    with SessionLocal() as db:
        player = db.get(Player, pid)
        player.global_rank = 9_500
        ev = media.rank_milestone(db, player, 12_000, 9_500)
        assert ev is not None and ev.payload["data"]["milestone"] == "4 digits"
        assert media.rank_milestone(db, player, 9_800, 9_500) is None  # nothing crossed

        retired = News(date(2016, 10, 15), "RETIRED", "WhiteCat retires from competitive osu!.", 3, {})
        minor = News(date(2016, 10, 15), "INJURY", "someone is injured", 2, {})
        assert media.world_headline(db, player, retired).type == "WORLD_NEWS"
        assert media.world_headline(db, player, minor) is None
        db.commit()
        assert db.query(StEvent).filter_by(player_id=pid).count() == 2


def test_old_eras_use_the_osu_forums(client, any_score_is_news):
    pid = _career(client, start="2010-03-01")["id"]
    _first_score(client, pid)
    assert client.get(f"/api/players/{pid}/forum").json()[0]["board"].startswith("osu! forums")


def test_nobodies_get_no_threads_for_small_things(client, any_score_is_news):
    from app.db import SessionLocal
    from app.models import Player
    from app.services import media as m
    pid = _career(client)["id"]
    with SessionLocal() as db:
        player = db.get(Player, pid)
        player.global_rank = 800_000

        class Ev:  # a severe injury
            type, date, message, data = "INJURY_SEVERE_RSI", player.in_game_date, "hiatus", {}

        m.player_injury(db, player, Ev())
        db.commit()
    assert client.get(f"/api/players/{pid}/forum").json() == []


def test_dms_reach_sillytavern_and_replies_land_in_the_channel(client):
    pid = _career(client)["id"]
    resp = client.post(f"/api/players/{pid}/dm", json={"to": "Cookiezi", "text": "hi, big fan"})
    assert resp.status_code == 200, resp.text
    assert resp.json()[-1]["content"] == "hi, big fan"
    assert client.post(f"/api/players/{pid}/dm", json={"to": "nobody_here", "text": "x"}).status_code == 404

    event = next(e for e in client.get(f"/api/st/careers/{pid}/events").json() if e["type"] == "DM_REPLY")
    assert set(event["prompts"]) == {"dm"}
    assert "You are Cookiezi" in event["prompts"]["dm"] and "hi, big fan" in event["prompts"]["dm"]
    assert event["channel"] == "DM:Cookiezi" and event["thread"] is None

    client.post(f"/api/st/careers/{pid}/irc", json={"channel": "DM:Cookiezi",
                                                    "lines": [{"author": "Cookiezi", "content": "thanks :)"}]})
    lines = client.get(f"/api/players/{pid}/irc", params={"channel": "DM:Cookiezi"}).json()
    assert [l["content"] for l in lines][-2:] == ["hi, big fan", "thanks :)"]
