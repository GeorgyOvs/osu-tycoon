import random
from datetime import date, timedelta
from types import SimpleNamespace

from app.db import SessionLocal
from app.engine import mindlock as M
from app.engine import play
from app.models import MapBlock, Player
from app.services import mindlock as S
from app.services import sessions
from tests.conftest import FIXTURE_BEATMAP_ID


def attempt(fail_progress=None, misses=0, passed=False, choke=None, timeline=None):
    return SimpleNamespace(fail_progress=fail_progress, misses=misses, passed=passed, choke_note=choke, timeline=timeline or [])


def test_onset_needs_repeated_failures_and_shaky_nerves():
    assert M.onset_chance(2, 50, 50) == 0
    assert M.onset_chance(5, 50, 50) > M.onset_chance(3, 50, 50) > 0
    assert M.onset_chance(4, 20, 20) > M.onset_chance(4, 95, 95)
    assert M.effective(0.8, 1.0) == 0.4 and M.faded(0.8, 10) < 0.45


def test_trouble_bucket_locates_fails_chokes_and_miss_clusters():
    assert M.trouble_bucket(attempt(fail_progress=0.5), 200) == 20
    assert M.trouble_bucket(attempt(passed=True, choke=(300, 50, 1.0)), 200) == 30
    tl = [SimpleNamespace(misses=0) for _ in range(40)]
    tl[7] = SimpleNamespace(misses=4)
    assert M.trouble_bucket(attempt(passed=True, misses=4, timeline=tl), 200) == 7
    assert M.trouble_bucket(attempt(passed=True), 200) is None


def test_blocks_appear_by_chance_and_dissolve_with_time(client):
    pid = client.post("/api/players", json=dict(name="Stuck", country="RU", start_date="2016-01-01", seed=3, age=17)).json()["id"]
    appeared = 0
    with SessionLocal() as db:
        player = db.get(Player, pid)
        for map_id in range(7000, 7040):  # many separate maps: onset is a lottery, not a rule
            for _ in range(6):
                S.record(db, player, map_id, attempt(fail_progress=0.5), 200, 100.0, 20.0, 20.0)
            if S.current(db, player, map_id):
                appeared += 1
        assert 3 <= appeared <= 38  # neither never nor always
        blocked = next(m for m in range(7000, 7040) if S.current(db, player, m))
        bucket, severity = S.current(db, player, blocked)
        assert bucket == 20 and severity > 0.3
        assert S.current(db, player, blocked, mastery=1.0)[1] < severity  # mastery weakens it
        player.in_game_date += timedelta(days=40)
        assert S.current(db, player, blocked) is None  # a long break clears it
        db.rollback()


def test_a_clean_pass_relieves_and_failing_again_deepens():
    with SessionLocal() as db:
        from app.engine import simulation

        player = simulation.new_career("A", "RU", date(2016, 1, 1), 5)
        db.add(player)
        db.flush()
        db.add(MapBlock(player_id=player.id, beatmap_id=1, bucket=20, streak=3, severity=0.5, last_on=player.in_game_date, attempts=9))
        db.flush()
        S.record(db, player, 1, attempt(fail_progress=0.51), 200, 100.0, 50, 50)
        assert db.get(MapBlock, (player.id, 1)).severity > 0.5
        for _ in range(4):
            S.record(db, player, 1, attempt(passed=True), 200, 100.0, 50, 50)
        row = db.get(MapBlock, (player.id, 1))
        assert row is None or row.severity < 0.2
        db.rollback()


def test_a_block_costs_misses_where_the_head_is_stuck(client):
    prof = sessions.map_profile(FIXTURE_BEATMAP_ID, "")
    from app.engine import simulation

    skills = {a.key: 60.0 for a in simulation.new_career("X", "RU", date(2016, 1, 1), 1).attributes}

    def misses_near_spot(day):
        total = 0
        for seed in range(60):
            a = play.simulate(prof, skills, "NF", day, random.Random(seed))
            total += sum(a.timeline[b].misses for b in range(18, 23))
        return total

    free = misses_near_spot(play.DayModifiers())
    stuck = misses_near_spot(play.DayModifiers(block_bucket=20, block_severity=1.0))
    assert stuck > free
