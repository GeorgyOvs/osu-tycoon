from datetime import date
import pytest
from app.engine import character, simulation
from app.db import SessionLocal
from app.models import Npc, WorldState
from app.services import world_service


def test_perks_change_start_and_learning_without_changing_random_default():
    def career():
        return simulation.new_career("User", "RU", date(2016, 1, 1), 42)
    baseline, selected = career(), career()
    perks = character.resolve("custom", ["aim_gift", "tapping_weakness"], False)
    character.apply(selected, "custom", perks, False)
    a, b = baseline.attributes[0], selected.attributes[0]
    assert b.base == a.base + 5
    assert b.affinity == pytest.approx(a.affinity * 1.3)
    character.apply(baseline, "random", [], False)
    assert baseline.talent == career().talent


def test_budget_and_conflicts_are_enforced_even_for_api_clients():
    with pytest.raises(ValueError):
        character.resolve("custom", ["quick_learner", "high_ceiling"], False)
    assert len(character.resolve("custom", ["quick_learner", "high_ceiling"], True)) == 2
    with pytest.raises(ValueError):
        character.resolve("custom", ["aim_gift", "aim_weakness"], True)
    with pytest.raises(ValueError):
        character.resolve("custom", ["unknown"], True)


def test_creation_api_and_larger_leaderboard(client):
    options = client.get('/api/players/creation-options').json()
    assert options['budget'] == 4
    body = dict(name='Builder', country='RU', start_date='2016-01-01', seed=42,
                preset='custom', perks=['quick_learner', 'high_ceiling'])
    assert client.post('/api/players', json=body).status_code == 422
    response = client.post('/api/players', json={**body, 'unbalanced': True})
    assert response.status_code == 201, response.text
    player = response.json()
    assert player['character_build']['perks'] == body['perks']
    board = client.get(f"/api/players/{player['id']}/leaderboard?limit=1000")
    assert board.status_code == 200
    assert len(board.json()['rows']) > 200
    assert client.get(f"/api/players/{player['id']}/leaderboard?limit=0").status_code == 422


def test_old_world_population_upgrade_is_idempotent(client):
    from app.models import Player
    response = client.post('/api/players', json=dict(name='Old', start_date='2016-01-01', seed=42))
    pid = response.json()['id']
    with SessionLocal() as db:
        state = db.get(WorldState, pid)
        state.population_version = 0
        npc = db.query(Npc).filter_by(player_id=pid, kind='procedural').first()
        name = npc.name
        db.delete(npc)
        db.commit()
        world_service.ensure_world(db, db.get(Player, pid))
        db.commit()
        assert db.query(Npc).filter_by(player_id=pid, name=name).count() == 1
        count = db.query(Npc).filter_by(player_id=pid).count()
        world_service.ensure_world(db, db.get(Player, pid))
        assert db.query(Npc).filter_by(player_id=pid).count() == count


def test_start_scenarios_start_far_above_a_newcomer():
    from app.engine import attributes as A
    from app.engine import scenarios, world

    def overall(key):
        p = simulation.new_career("User", "RU", date(2016, 1, 1), 42)
        scenarios.apply(p, scenarios.SCENARIOS[key])
        return A.overall(simulation.effective_values(p)), p

    values = {k: overall(k)[0] for k in scenarios.SCENARIOS}
    order = ["newcomer", "rhythm_gamer", "returning_veteran", "ex_pro", "phenom"]
    assert [values[k] for k in order] == sorted(values[k] for k in order)
    assert values["newcomer"] < 20 and values["phenom"] > 70
    # calibrated against the world: an ex-pro lands in the low thousands, a phenom in the top ~500
    assert world.pp_for_overall(values["phenom"], date(2016, 1, 1)) > 3 * world.pp_for_overall(values["newcomer"], date(2016, 1, 1))
    _, phenom = overall("phenom")
    assert all(a.base < a.cap for a in phenom.attributes) and phenom.followers >= 5000


def test_scenarios_are_deterministic_and_validated(client):
    body = dict(name='Vet', country='RU', start_date='2014-01-01', seed=7, age=20, scenario='ex_pro')
    a = client.post('/api/players', json=body)
    assert a.status_code == 201, a.text
    b = client.post('/api/players', json=body)
    key = lambda r: [(g['key'], round(g['value'], 1)) for g in r.json()['attributes']]
    assert key(a) == key(b)
    assert any(g['value'] > 50 for g in a.json()['attributes'])
    assert 'Бывший топ-игрок' in a.json()['traits']
    assert client.post('/api/players', json={**body, 'age': 12}).status_code == 422  # too young for an ex-pro
    assert client.post('/api/players', json={**body, 'scenario': 'god'}).status_code == 422
    assert 'phenom' in client.get('/api/players/creation-options').json()['scenarios']
