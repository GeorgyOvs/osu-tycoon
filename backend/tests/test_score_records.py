from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from app.config import OSU_CACHE_DIR
from app.db import SessionLocal
from app.engine import leaderboard as lb, pp_history
from app.models import Player, Npc, Beatmap, MapScore, WorldState, WorldEvent, ForumThread, StEvent
from app.services import leaderboards, score_records, media, tournaments
from tests.conftest import make_osu_file, make_set

MAP = 990001


def career(client, on='2024-01-01'):
    response = client.post('/api/players', json=dict(name='Tester', start_date=on, seed=42))
    assert response.status_code == 201, response.text
    return response.json()['id']


@pytest.fixture(autouse=True)
def hard_map(fresh_db):
    (OSU_CACHE_DIR / f'{MAP}.osu').write_text(make_osu_file(MAP, 501, gap_ms=100), encoding='utf-8')
    leaderboards.map_facts.cache_clear()
    leaderboards._parsed.cache_clear()
    from app.services import osu_files
    osu_files._MEMORY.pop(MAP, None)
    from app.services import beatmap_index, sessions
    sessions.map_profile.cache_clear()
    with SessionLocal() as db:
        beatmap_index.upsert_set(db, make_set(50199, date(2010, 1, 1), [MAP], stars=[8]))
        db.commit()


def stored_record(db, player):
    npc = db.scalars(select(Npc).where(Npc.player_id == player.id, Npc.kind == 'procedural')).first()
    facts = leaderboards.map_facts(MAP)
    score = MapScore(player_id=player.id, npc_id=npc.id, name=npc.name, country=npc.country,
                     kind='npc', beatmap_id=MAP, mods='', accuracy=100, misses=0,
                     max_combo=facts.max_combo, score=123456789, set_on=player.in_game_date,
                     pp=leaderboards.era_pp(MAP, '', 100, 0, facts.max_combo, player.in_game_date))
    db.add(score)
    db.flush()
    return npc, score


def test_first_1000_is_a_saved_calculable_map_score_visible_in_board(client):
    pid = career(client)
    with SessionLocal() as db:
        player = db.get(Player, pid)
        npc, score = stored_record(db, player)
        event = score_records.consider(db, player, score, player.in_game_date, npc)
        assert event.type == 'FIRST_1000PP'
        assert event.data['beatmap_id'] == MAP and event.data['score_id'] == score.id
        assert 'Song' in event.message and score.record
        news = tournaments.News(player.in_game_date, event.type, event.message, 3, event.data)
        social = media.world_headline(db, player, news)
        assert social.payload['data']['score_pp'] == pytest.approx(score.pp)
        assert str(MAP) in db.get(ForumThread, social.thread_id).body
        leaderboards.ensure_board(db, player, MAP)
        row = next(r for r in leaderboards.board_entries(db, player, MAP) if r.npc_id == npc.id)
        assert row.pp == pytest.approx(score.pp)
        assert score_records.consider(db, player, score, player.in_game_date, npc) is None
        out = []
        tournaments._news(db, player, player.in_game_date, event.type, event.message, 3, event.data, out)
        db.flush()
        # Another mod combination can beat ScoreV1 while earning less pp; the announced play is retained.
        db.add(MapScore(player_id=pid, npc_id=npc.id, beatmap_id=MAP, kind='npc', name=npc.name,
                        country=npc.country, mods='HD', accuracy=90, max_combo=100, misses=10,
                        score=score.score + 1, pp=0, set_on=player.in_game_date))
        db.flush()
        archive = leaderboards.record_history(db, player, MAP)
        assert len(archive) == 1 and archive[0].pp == pytest.approx(event.data['score_pp'])
        assert archive[0].max_combo == score.max_combo and archive[0].mods == ''


def test_no_1000pp_news_before_pp_exists_or_for_real_players_or_future_maps(client):
    pid = career(client, '2010-06-01')
    with SessionLocal() as db:
        player = db.get(Player, pid)
        npc, score = stored_record(db, player)
        assert score.pp > 1000
        assert score_records.consider(db, player, score, player.in_game_date, npc) is None
        player.in_game_date = date(2024, 1, 1)
        npc.kind = 'real'
        assert score_records.consider(db, player, score, player.in_game_date, npc) is None
        npc.kind = 'procedural'
        db.get(Beatmap, MAP).beatmapset.ranked_date = date(2025, 1, 1)
        assert score_records.consider(db, player, score, player.in_game_date, npc) is None


def test_user_record_is_one_scorepost_and_appears_in_map_leaderboard(client):
    pid = career(client)
    response = client.post(f'/api/players/{pid}/scores', json={
        'beatmap_id': MAP, 'mods': '', 'accuracy': 100, 'misses': 0,
    })
    assert response.status_code == 200, response.text
    earned = response.json()['score']['pp']
    assert earned > 1000
    board = client.get(f'/api/players/{pid}/beatmaps/{MAP}/leaderboard').json()
    user = next(row for row in board['entries'] if row['kind'] == 'user')
    assert user['pp'] == pytest.approx(earned)
    assert board['record_history'][0]['pp'] == pytest.approx(earned)
    threads = client.get(f'/api/players/{pid}/forum').json()
    assert sum(t['kind'] == 'scorepost' for t in threads) == 1


def test_weekly_attempts_cannot_create_implausible_early_scores(client, monkeypatch):
    pid = career(client, '2010-06-01')
    with SessionLocal() as db:
        player = db.get(Player, pid)
        npc = db.scalars(select(Npc).where(Npc.player_id == pid, Npc.kind == 'procedural')).first()
        npc.status, npc.overall = 'active', 110
        facts = leaderboards.map_facts(MAP)
        monkeypatch.setattr(lb, 'estimate_best', lambda *a: SimpleNamespace(
            mods='', accuracy=100, misses=0, max_combo=facts.max_combo, score=99999999))
        assert score_records.weekly(db, player, [npc], player.in_game_date, {MAP}) == []
        assert db.scalars(select(MapScore).where(MapScore.player_id == pid)).first() is None


def test_board_pp_uses_same_era_formula_as_player_scores(client):
    pid = career(client, '2013-06-01')
    with SessionLocal() as db:
        player = db.get(Player, pid)
        npc, score = stored_record(db, player)
        score.max_combo //= 2
        score.pp = 99999  # stale modern pp cached by the old implementation
        score.record = True
        expected = leaderboards.era_pp(MAP, '', 100, 0, score.max_combo, player.in_game_date, score.set_on)
        db.flush()
        row = next(r for r in leaderboards.board_entries(db, player, MAP) if r.npc_id == npc.id)
        assert row.pp == pytest.approx(expected)
        assert row.pp < leaderboards._pp(MAP, '', 100, 0, score.max_combo)


def test_legacy_news_is_retracted_without_erasing_discussion(client):
    pid = career(client, '2010-06-01')
    with SessionLocal() as db:
        message = 'FakeNPC sets the fictional world\'s first 1000pp score!'
        old = WorldEvent(player_id=pid, date=date(2010, 6, 1), type='FIRST_1000PP',
                         message=message, data={'npc_id': 1}, importance=3)
        thread = ForumThread(player_id=pid, date=date(2010, 6, 1), board='osu! forums', kind='news',
                             title=message, author='User')
        pending = StEvent(player_id=pid, date=date(2010, 6, 1), type='WORLD_NEWS',
                          payload={'data': {'headline': message, 'news_type': 'FIRST_1000PP'}})
        db.add_all([old, thread, pending])
        db.flush()
        assert score_records.repair_legacy_records(db) == 1
        assert old.data['retracted'] and thread.flair == 'Correction' and pending.handled
        assert score_records.repair_legacy_records(db) == 0
