from datetime import date
from types import SimpleNamespace
import random

from app.engine import world


def _pp(style_name, overall, on):
    return world.pp_for_overall(world.pp_overall(world.composites(overall, world.ARCHETYPES[style_name] and
                                                                  {g: v * 0.5 for g, v in world.ARCHETYPES[style_name].items()}), on), on)


def test_specialists_can_outrank_a_higher_overall_player():
    on = date(2016, 1, 1)
    # A farmer rated 4 points lower still out-earns a tournament player (nerves don't make pp).
    assert _pp("farmer", 84, on) > _pp("tournament player", 88, on)
    # Same overall: the meta decides. Streams are worth more after the November 2021 rework.
    assert _pp("streamer", 80, date(2022, 1, 1)) / _pp("farmer", 80, date(2022, 1, 1)) > (
        _pp("streamer", 80, on) / _pp("farmer", 80, on))


def test_archetype_is_recovered_from_the_style_vector():
    import random

    rng = random.Random(3)
    assert world.archetype({g: v * 0.5 for g, v in world.ARCHETYPES["streamer"].items()}) == "streamer"
    assert world.archetype(world.random_style(rng)) in world.ARCHETYPES


def test_fictional_npcs_practise_their_profitable_focus():
    npc = SimpleNamespace(
        kind="procedural", seed=17, join_date=date(2014, 1, 1), ramp_years=3.0,
        prime_years=2.0, style={g: 0.0 for g in world.GROUP_KEYS}, overall=60.0,
        deviation=0.0, development={}, story={},
    )
    world.initialize_development(npc)
    dev = dict(npc.development)
    dev.update({"focus": "aim", "training_weeks": 0, "plateau_weeks": 0})
    npc.development = dev
    before = dict(npc.style)
    world._advance_development(npc, date(2015, 1, 1), 70.0, "active", False, random.Random(2))
    assert npc.style["aim"] > before["aim"]
    assert npc.style["tapping"] < before["tapping"]


def test_pp_potential_and_tournament_strength_reward_different_profiles():
    on = date(2019, 1, 1)
    farmer = world.composites(80, {g: v * 0.5 for g, v in world.ARCHETYPES["farmer"].items()})
    tournament = world.composites(80, {g: v * 0.5 for g, v in world.ARCHETYPES["tournament player"].items()})
    assert world.pp_overall(farmer, on) > world.pp_overall(tournament, on)
    assert world.tournament_overall(tournament) > world.tournament_overall(farmer)
    assert "DT jumps" in world.best_score_types(farmer)
