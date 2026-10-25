from datetime import date, timedelta

import pytest

from app.engine import attributes as A
from app.engine import simulation as S
from app.engine.training import DRILLS, Era, available_drills, era_for


def career(seed: int = 1, start: date = date(2017, 1, 1)):
    return S.new_career("Test", "RU", start, seed)


def attr(player, key):
    return next(a for a in player.attributes if a.key == key)


def test_hierarchy_has_21_substats_in_6_groups():
    assert len(A.GROUPS) == 6
    assert len(A.SUBSTATS) == 21


def test_composites_and_overall_are_weighted_means():
    values = {k: 50.0 for k in A.SUBSTATS}
    assert all(v == pytest.approx(50) for v in A.composites(values).values())
    assert A.overall(values) == pytest.approx(50)

    values["snap_aim"] = 90.0  # heaviest aim sub-stat (1.2 of 4.0)
    assert A.composite(values, A.GROUPS_BY_KEY["aim"]) == pytest.approx(50 + 40 * 1.2 / 4.0)


def test_new_career_is_deterministic_per_seed():
    a, b, c = career(seed=7), career(seed=7), career(seed=8)
    assert [x.base for x in a.attributes] == [x.base for x in b.attributes]
    assert a.potential == b.potential
    assert [x.base for x in a.attributes] != [x.base for x in c.attributes]
    assert S.POTENTIAL_RANGE[0] <= a.potential <= S.POTENTIAL_RANGE[1]
    assert len(a.attributes) == 21


def test_eras_gate_drills():
    assert era_for(date(2009, 5, 1)) == Era.OLD_SCHOOL
    assert era_for(date(2014, 5, 1)) == Era.COMPETITIVE
    assert era_for(date(2018, 5, 1)) == Era.FARM
    assert era_for(date(2023, 5, 1)) == Era.MODERN

    old_school = {d.key for d in available_drills(date(2009, 1, 1))}
    assert "ranked_pack_grind" in old_school
    assert "stream_practice" not in old_school  # can't isolate streams before 2012
    assert "jump_farm" not in old_school
    assert "rapid_trigger_drills" in {d.key for d in available_drills(date(2023, 1, 1))}


def test_unavailable_drill_is_blocked():
    p = career(start=date(2009, 1, 1))
    with pytest.raises(S.TrainingBlocked):
        S.run_days(p, S.DayPlan(DRILLS["jump_farm"], 4), 1)


def test_training_improves_targets_and_advances_calendar():
    p = career()
    before = attr(p, "snap_aim").base
    result = S.run_days(p, S.DayPlan(DRILLS["jump_farm"], 4), 7)
    assert p.in_game_date == date(2017, 1, 8)
    assert result.days == 7
    assert attr(p, "snap_aim").base > before
    assert result.deltas["snap_aim"] > 0
    assert attr(p, "snap_aim").last_trained_on == date(2017, 1, 7)


def test_gains_diminish_near_cap():
    low, high = career(), career()
    attr(low, "snap_aim").base = 20
    attr(high, "snap_aim").base = 90
    S.run_days(low, S.DayPlan(DRILLS["jump_farm"], 4), 5)
    S.run_days(high, S.DayPlan(DRILLS["jump_farm"], 4), 5)
    assert attr(low, "snap_aim").base - 20 > (attr(high, "snap_aim").base - 90) * 3


def test_simulation_is_deterministic():
    def play(p):
        for _ in range(10):
            try:
                S.run_days(p, S.DayPlan(DRILLS["deathstream_240"], 9), 3)
            except S.TrainingBlocked:
                pass
            S.run_days(p, S.DayPlan(), 1)
        return [(a.key, a.base, a.rust, a.cap) for a in p.attributes], p.injury, p.fatigue

    assert play(career(seed=3)) == play(career(seed=3))


def test_rust_after_14_idle_days_and_capped():
    p = career()
    attr(p, "snap_aim").base = 60
    # Last trained on the start day; rust needs more than 14 idle days.
    S.run_days(p, S.DayPlan(), 15)
    assert attr(p, "snap_aim").rust == 0

    result = S.run_days(p, S.DayPlan(), 1)
    assert attr(p, "snap_aim").rust == 1
    assert any(e.type == "RUST" and e.data["group"] == "aim" for e in result.events)

    S.run_days(p, S.DayPlan(), 100)
    assert attr(p, "snap_aim").rust == S.RUST_MAX
    # low skills never lose more than 20%
    low = min(p.attributes, key=lambda a: a.base)
    assert low.rust <= low.base * S.RUST_MAX_SHARE + 1e-9


def test_rust_clears_twice_as_fast_as_skill_builds():
    a = career()
    x = attr(a, "snap_aim")
    x.base, x.rust, x.last_trained_on = 50.0, 3.0, a.in_game_date
    S._gain(x, 1.0, a.in_game_date)
    points = 1.0 * ((x.cap - 50) / x.cap) ** 1.3
    assert x.rust == pytest.approx(3.0 - 2 * points)
    assert x.base == pytest.approx(50.0)


def test_training_one_group_keeps_it_fresh_while_others_rust():
    p = career()
    S.run_days(p, S.DayPlan(DRILLS["jump_farm"], 3), 30)
    assert attr(p, "snap_aim").rust == 0
    assert attr(p, "strict_od").rust > 0


def test_fatigue_builds_with_long_sessions_and_recovers_with_rest():
    p = career()
    S.run_days(p, S.DayPlan(DRILLS["ranked_pack_grind"], 4), 3)
    sane = p.fatigue
    p2 = career()
    S.run_days(p2, S.DayPlan(DRILLS["ranked_pack_grind"], 10), 3)
    assert p2.fatigue > sane + 20
    S.run_days(p2, S.DayPlan(), 5)
    assert p2.fatigue < 10


def _grind_until(p, state, max_days=200):
    for _ in range(max_days):
        if p.injury == state:
            return
        S.run_days(p, S.DayPlan(DRILLS["deathstream_240"], 10), 1)
    raise AssertionError(f"never reached {state}")


def test_minor_strain_applies_penalties_and_heals_with_rest():
    p = career()
    _grind_until(p, S.MINOR_STRAIN)
    ds = attr(p, "deathstream")
    assert S.effective_value(ds, p.injury) == pytest.approx(A.clamp((ds.base - ds.rust) * 0.85))

    result = S.run_days(p, S.DayPlan(), 10)
    assert p.injury == S.HEALTHY
    assert any(e.type == "INJURY_RECOVERED" for e in result.events)


def test_ignoring_strain_leads_to_hiatus_and_permanent_damage():
    p = career()
    _grind_until(p, S.SEVERE_RSI)
    assert p.injury_until is not None
    hiatus = (p.injury_until - p.in_game_date).days
    assert 0 < hiatus <= S.SEVERE_HIATUS_DAYS[1]

    with pytest.raises(S.TrainingBlocked):
        S.run_days(p, S.DayPlan(DRILLS["tech_maps"], 2), 1)

    cap_before = attr(p, "hand_stamina").cap
    result = S.run_days(p, S.DayPlan(), hiatus + 1)
    assert p.injury == S.HEALTHY
    assert any(e.type == "PERMANENT_DAMAGE" for e in result.events)
    assert attr(p, "hand_stamina").cap < cap_before


def test_physio_prevents_permanent_damage_and_shortens_hiatus():
    p = career()
    _grind_until(p, S.SEVERE_RSI)
    until = p.injury_until
    cap_before = attr(p, "hand_stamina").cap
    result = S.run_days(p, S.DayPlan(physio=True), 120)
    assert p.injury == S.HEALTHY
    assert attr(p, "hand_stamina").cap == cap_before
    recovered = next(e for e in result.events if e.type == "INJURY_RECOVERED")
    assert recovered.date < until


def test_training_stops_when_severe_injury_hits_mid_action():
    p = career()
    _grind_until(p, S.MINOR_STRAIN)
    start = p.in_game_date
    result = S.run_days(p, S.DayPlan(DRILLS["deathstream_240"], 12), 30)
    assert p.injury == S.SEVERE_RSI
    assert result.days < 30
    assert any(e.type == "TRAINING_INTERRUPTED" for e in result.events)
    assert p.in_game_date == start + timedelta(days=result.days)


def test_talent_profile_is_seeded_and_varied():
    a, b = career(seed=11), career(seed=11)
    assert a.talent == b.talent
    assert [x.affinity for x in a.attributes] == [x.affinity for x in b.attributes]
    talents = {career(seed=s).talent for s in range(30)}
    assert len(talents) > 20
    assert all(S.TALENT_RANGE[0] <= t <= S.TALENT_RANGE[1] for t in talents)


def test_daily_gains_vary_from_day_to_day():
    p = career(seed=5)
    a = attr(p, "snap_aim")
    gains = []
    for _ in range(10):
        before = a.base
        S.run_days(p, S.DayPlan(DRILLS["jump_farm"], 4), 1)
        gains.append(a.base - before)
    assert len({round(g, 4) for g in gains}) == len(gains)


def test_form_is_autocorrelated():
    p = career(seed=9)
    forms = []
    for _ in range(400):
        S.run_days(p, S.DayPlan(), 1)
        forms.append(p.form)
    mean = sum(forms) / len(forms)
    num = sum((x - mean) * (y - mean) for x, y in zip(forms, forms[1:]))
    den = sum((x - mean) ** 2 for x in forms)
    assert num / den > 0.6  # streaks, not independent coin flips


def test_plateau_builds_and_reduces_gains_and_rest_consolidates():
    fresh, walled = career(seed=4), career(seed=4)
    attr(walled, "snap_aim").plateau = S.PLATEAU_SCALE  # halves gains
    S.run_days(fresh, S.DayPlan(DRILLS["jump_farm"], 4), 1)
    S.run_days(walled, S.DayPlan(DRILLS["jump_farm"], 4), 1)
    gain = lambda p: attr(p, "snap_aim").base - attr(career(seed=4), "snap_aim").base
    assert gain(walled) < gain(fresh) * 0.6

    level = attr(fresh, "snap_aim").plateau
    assert level > 0
    S.run_days(fresh, S.DayPlan(), 1)
    assert attr(fresh, "snap_aim").plateau == pytest.approx(level * S.PLATEAU_REST_DECAY)


def test_breakthroughs_happen_and_lower_the_plateau():
    p = career(seed=2)
    events = []
    for _ in range(40):
        events += S.run_days(p, S.DayPlan(DRILLS["jump_farm"], 4), 6).events
        S.run_days(p, S.DayPlan(), 1)
    hits = [e for e in events if e.type == "BREAKTHROUGH"]
    assert hits
    assert all(e.data["jump"] > 0 for e in hits)


def test_traits_reflect_hidden_profile():
    p = career()
    p.talent = 1.4
    for a in p.attributes:
        a.affinity = 1.3 if a.key in ("snap_aim", "flow_aim", "precision", "distance") else 1.0
    assert S.traits(p) == ["Fast learner", "Natural aim"]


def test_every_skill_is_trainable_in_every_era():
    """No sub-stat may be a dead end: whatever year a career starts, each skill has a drill that trains it."""
    from datetime import date

    from app.engine import attributes as A
    from app.engine.training import available_drills

    for year in (2007, 2011, 2013, 2018, 2023):
        drills = available_drills(date(year, 6, 1))
        trainable = set(S.PASSIVE_TARGETS)
        for drill in drills:
            trainable |= set(drill.targets)
        missing = set(A.SUBSTATS) - trainable
        assert not missing, f"{year}: nothing trains {sorted(missing)}"


def test_old_school_streams_are_slower_than_stream_practice():
    from datetime import date

    from app.engine.training import DRILLS, Era

    early = DRILLS["ranked_streams"]
    assert early.available(date(2008, 1, 1))
    assert early.efficiency(date(2008, 1, 1)) < 1.0
    assert DRILLS["stream_practice"].efficiency(date(2013, 1, 1)) > early.efficiency(date(2013, 1, 1))
    assert early.targets["deathstream"] > 0 and early.available_from == Era.OLD_SCHOOL
