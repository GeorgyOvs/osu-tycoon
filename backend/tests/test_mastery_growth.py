import random
from datetime import date

from app.db import SessionLocal
from app.engine import leaderboard as lb
from app.engine import play, simulation, world
from app.models import MapScore, Player
from app.services import familiarity, progression, story
from tests.conftest import FIXTURE_BEATMAP_ID


def test_mastery_builds_slowly_and_fades_slowly():
    assert familiarity.mastery_from(0, 0) == 0
    a = [familiarity.mastery_from(n, 0) for n in (5, 30, 100, 300)]
    assert a == sorted(a) and a[0] < 0.1 and a[-1] > 0.95
    assert familiarity.mastery_from(300, 365) > 0.55  # a year away and it is still largely there
    assert familiarity.mastery_from(300, 1000) < familiarity.mastery_from(300, 100)


def test_mastered_maps_play_above_the_general_level():
    base = play.DayModifiers().capability(50)
    assert play.DayModifiers(mastery=1.0).capability(50) > base * 1.09
    assert play.DayModifiers(familiarity=1.0, mastery=1.0).capability(50) > base * 1.14


def test_a_map_beyond_your_numbers_becomes_playable_with_practice(client):
    from app.services import sessions

    prof = sessions.map_profile(FIXTURE_BEATMAP_ID, "DT")
    skills = {k: 40.0 for k in simulation.effective_values(simulation.new_career("X", "RU", date(2013, 1, 1), 1))}
    fresh = play.assess(prof, skills, "DT", play.DayModifiers(), "t").pass_rate
    drilled = play.assess(prof, skills, "DT", play.DayModifiers(familiarity=1.0, mastery=1.0), "t").pass_rate
    assert drilled >= fresh


def test_skill_ceilings_follow_the_scene_over_the_years(client):
    pid = client.post("/api/players", json=dict(name="Grow", country="RU", start_date="2009-06-01", seed=3, age=17)).json()["id"]
    with SessionLocal() as db:
        player = db.get(Player, pid)
        story.put(player, "cap_ref_top", world.era_top_overall(date(2009, 6, 1)))
        story.put(player, "cap_growth", 0.0)
        before = {a.key: a.cap for a in player.attributes}
        player.in_game_date = date(2020, 6, 1)
        progression.tick(db, player, [])
        expected = progression.target_growth(world.era_top_overall(date(2009, 6, 1)), world.era_top_overall(date(2020, 6, 1)))
        assert expected > 8
        assert all(abs(a.cap - min(115.0, before[a.key] + expected)) < 1e-6 for a in player.attributes)
        progression.tick(db, player, [])  # idempotent
        assert all(abs(a.cap - min(115.0, before[a.key] + expected)) < 1e-6 for a in player.attributes)


def test_npcs_remember_maps_they_have_played(client):
    pid = client.post("/api/players", json=dict(name="Look", country="RU", start_date="2016-06-01", seed=4, age=17)).json()["id"]
    client.get(f"/api/players/{pid}/beatmaps/{FIXTURE_BEATMAP_ID}/leaderboard")
    client.post(f"/api/players/{pid}/rest", json={"days": 200, "physio": False})
    client.get(f"/api/players/{pid}/beatmaps/{FIXTURE_BEATMAP_ID}/leaderboard")
    with SessionLocal() as db:
        rows = db.query(MapScore).filter_by(player_id=pid, beatmap_id=FIXTURE_BEATMAP_ID, kind="npc").all()
        assert rows and all(r.attempts >= 2 for r in rows)
        assert max(r.attempts for r in rows) > 8  # some have come back several times
    comps = {"aim": 60.0, "tapping": 60.0}
    assert lb.boost(comps, 0.1)["aim"] == 66.0 and lb.boost(comps, 0.0) is comps
