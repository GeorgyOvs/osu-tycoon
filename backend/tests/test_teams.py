from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.engine import teams as rules
from app.models import Npc, Player, TeamMember, WorldEvent
from app.services import story, teams, world_service
from tests.conftest import seed_pool_maps


def _career(client, start="2014-03-01", seed=7, age=17, name="Teamer"):
    return client.post("/api/players", json={"name": name, "country": "RU", "start_date": start, "seed": seed,
                                             "age": age}).json()["id"]


def _url(pid, path=""):
    return f"/api/players/{pid}/team{path}"


def _found(client, pid, name="Pixel Pact", tag="PXP"):
    return client.post(_url(pid, "/found"), json={"name": name, "tag": tag})


def _force_members(pid, n=2):
    """Put the strongest active NPCs straight into the player's team (no recruiting dice)."""
    with SessionLocal() as db:
        player = db.get(Player, pid)
        team = teams.active_team(db, player)
        npcs = list(db.scalars(select(Npc).where(Npc.player_id == pid, Npc.status == "active", Npc.rank.is_not(None))
                               .order_by(Npc.rank).limit(n + 10)))[:n]
        for npc in npcs:
            team.members.append(TeamMember(team_id=team.id, npc_id=npc.id, role="member",
                                           joined_on=player.in_game_date, bond=50.0))
        db.commit()
        return [n.id for n in npcs]


def test_found_charges_money_and_validates(client):
    pid = _career(client)
    assert _found(client, pid, tag="a").status_code == 422
    assert _found(client, pid, name="x").status_code == 422
    with SessionLocal() as db:
        before = db.get(Player, pid).money
    resp = _found(client, pid)
    assert resp.status_code == 200, resp.text
    state = resp.json()
    assert state["team"]["name"] == "Pixel Pact" and state["team"]["tag"] == "PXP"
    assert state["team"]["channel"] == "#pxp" and state["team"]["size"] == 1
    assert not state["can_found"]
    with SessionLocal() as db:
        assert db.get(Player, pid).money == pytest.approx(before - rules.FOUND_COST)
    assert _found(client, pid, name="Another").status_code == 409  # already in a team


def test_cannot_found_before_clans_or_when_broke(client):
    old = _career(client, start="2008-02-01", seed=2)
    resp = _found(client, old)
    assert resp.status_code == 409 and "aren't a thing yet in 2008" in resp.json()["detail"]
    pid = _career(client, seed=3)
    with SessionLocal() as db:
        db.get(Player, pid).money = 5
        db.commit()
    assert _found(client, pid).status_code == 409


def test_actions_without_a_team_are_refused(client):
    pid = _career(client)
    assert client.post(_url(pid, "/scrim"), json={"hours": 1}).status_code == 409
    assert client.post(_url(pid, "/leave")).status_code == 409
    assert client.post(_url(pid, "/recruit"), json={"npc_id": 1}).status_code == 409
    state = client.get(_url(pid)).json()
    assert state["team"] is None and state["invite"] is None and state["can_found"]


def test_recruiting_is_gated_by_odds_and_remembers_refusals(client):
    pid = _career(client)
    _found(client, pid)
    candidates = client.get(_url(pid, "/candidates")).json()
    assert candidates and all(0 < c["odds"] < 1 for c in candidates)
    assert len({c["odds"] for c in candidates}) > 1  # odds depend on the player

    refused = accepted = None
    for c in sorted(candidates, key=lambda c: c["odds"]):
        resp = client.post(_url(pid, "/recruit"), json={"npc_id": c["npc_id"]})
        if resp.status_code == 409:  # team full
            break
        assert resp.status_code == 200, resp.text
        out = resp.json()
        if out["accepted"] and accepted is None:
            accepted = c
        elif not out["accepted"] and refused is None:
            refused = c
        if accepted and refused:
            break
    assert accepted is not None
    names = [m["name"] for m in client.get(_url(pid)).json()["team"]["members"]]
    assert accepted["name"] in names
    if refused:
        again = client.post(_url(pid, "/recruit"), json={"npc_id": refused["npc_id"]})
        assert again.status_code == 409 and "declined recently" in again.json()["detail"]
    assert client.post(_url(pid, "/recruit"), json={"npc_id": accepted["npc_id"]}).status_code == 409


def test_team_has_a_size_limit_and_roles(client):
    pid = _career(client)
    _found(client, pid)
    _force_members(pid, rules.MAX_SIZE - 1)
    with SessionLocal() as db:
        player = db.get(Player, pid)
        teams.refresh_roles(db, player, teams.active_team(db, player))
        db.commit()
    team = client.get(_url(pid)).json()["team"]
    assert team["size"] == rules.MAX_SIZE
    roles = [m["role"] for m in team["members"]] + [team["user_role"]]
    assert len(set(roles)) >= 4 and "leader" in roles
    extra = client.get(_url(pid, "/candidates")).json()
    assert extra == [] or client.post(_url(pid, "/recruit"), json={"npc_id": extra[0]["npc_id"]}).status_code == 409


def test_scrim_builds_chemistry_once_a_day(client):
    pid = _career(client)
    _found(client, pid)
    _force_members(pid, 2)
    before = client.get(_url(pid)).json()["team"]["chemistry"]
    resp = client.post(_url(pid, "/scrim"), json={"hours": 2})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["chemistry"] > before and out["state"]["team"]["scrim_today"]
    assert out["state"]["team"]["perks"]["learning_bonus_pct"] > 0
    assert client.post(_url(pid, "/scrim"), json={"hours": 1}).status_code == 409
    assert client.post(_url(pid, "/scrim"), json={"hours": 9}).status_code == 422
    with SessionLocal() as db:
        assert teams.learning_multiplier(db, db.get(Player, pid)) > 1.0
    client.post(f"/api/players/{pid}/rest", json={"days": 4})
    with SessionLocal() as db:
        assert teams.learning_multiplier(db, db.get(Player, pid)) == 1.0  # the glow fades


def _mondays(start: date, n: int):
    d = start + timedelta(days=(7 - start.weekday()) % 7)
    for i in range(n):
        yield d + timedelta(days=7 * i)


def _tick_until_invite(pid, rank=150, weeks=80, start=date(2014, 3, 3)):
    with SessionLocal() as db:
        player = db.get(Player, pid)
        player.global_rank = rank
        world_service.ensure_world(db, player)
        for on in _mondays(start, weeks):
            player.in_game_date = on
            teams._week(db, player, on, [], on)
            invite = teams.pending_invite(db, player)
            if invite is not None:
                db.commit()
                return on, invite.name, invite.tag, [db.get(Npc, m.npc_id).name for m in invite.members]
        db.commit()
    return None


def test_invites_arrive_weekly_and_are_deterministic(client):
    a = _tick_until_invite(_career(client, seed=11))
    b = _tick_until_invite(_career(client, seed=11))
    assert a is not None and a == b
    assert len(a[3]) >= 2


def test_no_invites_for_unranked_kids_or_before_clans(client):
    kid = _career(client, seed=12, age=9)
    assert _tick_until_invite(kid, weeks=60) is None
    old = _career(client, start="2008-01-01", seed=13)
    assert _tick_until_invite(old, weeks=20, start=date(2008, 1, 7)) is None
    with SessionLocal() as db:  # unranked: nobody has heard of you
        player = db.get(Player, _career(client, seed=14))
        world_service.ensure_world(db, player)
        for on in _mondays(date(2014, 3, 3), 40):
            teams._week(db, player, on, [], on)
        assert teams.pending_invite(db, player) is None


def test_accept_decline_and_expiry(client):
    pid = _career(client, seed=11)
    on, name, tag, ids = _tick_until_invite(pid)
    state = client.get(_url(pid)).json()
    invite = state["invite"]
    assert invite["name"] == name and invite["invited_by"] and state["team"] is None
    resp = client.post(_url(pid, f"/invites/{invite['id']}/accept"))
    assert resp.status_code == 200, resp.text
    team = resp.json()["team"]
    assert team["name"] == name and team["size"] == len(ids) + 1 and resp.json()["invite"] is None
    assert client.post(_url(pid, f"/invites/{invite['id']}/accept")).status_code == 409  # already open no more

    other = _career(client, seed=11)
    on, name, *_ = _tick_until_invite(other)
    invite = client.get(_url(other)).json()["invite"]
    declined = client.post(_url(other, f"/invites/{invite['id']}/decline"))
    assert declined.status_code == 200 and declined.json()["invite"] is None
    assert declined.json()["history"][0]["status"] == "disbanded"

    third = _career(client, seed=11)
    on, *_ = _tick_until_invite(third)
    with SessionLocal() as db:
        player = db.get(Player, third)
        teams._week(db, player, on + timedelta(days=rules.INVITE_DAYS + 7), [], on + timedelta(days=rules.INVITE_DAYS + 7))
        db.flush()
        assert teams.pending_invite(db, player) is None


def test_leave_sets_cooldown_and_archives(client):
    pid = _career(client)
    _found(client, pid)
    out = client.post(_url(pid, "/leave")).json()
    assert out["team"] is None and out["history"][0]["status"] == "left"
    with SessionLocal() as db:
        after = story.get(db.get(Player, pid), "team_invite_after")
    assert after is not None


def test_neglect_decays_chemistry_and_retirement_removes_members(client):
    pid = _career(client)
    _found(client, pid)
    ids = _force_members(pid, 2)
    with SessionLocal() as db:
        player = db.get(Player, pid)
        team = teams.active_team(db, player)
        team.chemistry = 80.0
        teams._set_data(team, last_activity=(player.in_game_date - timedelta(days=60)).isoformat())
        db.get(Npc, ids[0]).status = "retired"
        out = []
        teams._week(db, player, player.in_game_date + timedelta(days=1), out, player.in_game_date)
        assert team.chemistry < 80.0
        left = [m for m in team.members if m.left_on is not None]
        assert [m.npc_id for m in left] == [ids[0]]
        assert any(n.type == "TEAM_MEMBER_LEFT" for n in out)
        db.commit()


def test_kick_removes_a_member(client):
    pid = _career(client)
    _found(client, pid)
    ids = _force_members(pid, 2)
    out = client.post(_url(pid, "/kick"), json={"npc_id": ids[0]}).json()
    assert [m["npc_id"] for m in out["team"]["members"]] == [ids[1]]
    assert client.post(_url(pid, "/kick"), json={"npc_id": ids[0]}).status_code == 404


def test_team_chatter_goes_to_its_channel(client):
    pid = _career(client)
    _found(client, pid)
    _force_members(pid, 2)
    client.post(_url(pid, "/scrim"), json={"hours": 1})
    assert "#pxp" in client.get(f"/api/players/{pid}/irc/channels").json()
    lines = client.get(f"/api/players/{pid}/irc", params={"channel": "#pxp"}).json()
    assert lines and all(line["author"] != "" for line in lines)


# --- clan cups --------------------------------------------------------------------------------


def _clan_cup(client, pid):
    listing = client.get(f"/api/players/{pid}/tournaments").json()
    return next(t for t in listing["tournaments"] if t["tier"] == "clan")


def test_clan_cup_needs_a_squad_and_features_the_team(client):
    pid = _career(client, start="2014-03-01", seed=21)
    with SessionLocal() as db:
        seed_pool_maps(db)
    cup = _clan_cup(client, pid)
    assert cup["team_size"] == 3 and cup["size"] == 16
    client.post(f"/api/players/{pid}/rest", json={"days": 1})
    assert client.post(f"/api/players/{pid}/tournaments/{cup['id']}/register").status_code == 409  # no team

    _found(client, pid)
    assert client.post(f"/api/players/{pid}/tournaments/{cup['id']}/register").status_code == 409  # alone
    _force_members(pid, 2)
    client.post(_url(pid, "/scrim"), json={"hours": 2})
    assert client.post(f"/api/players/{pid}/tournaments/{cup['id']}/register").status_code == 200

    client.post(f"/api/players/{pid}/rest", json={"days": 60})  # stops on the first match day
    detail = client.get(f"/api/players/{pid}/tournaments/{cup['id']}").json()
    mine = [e for e in detail["entries"] if e["includes_user"]]
    assert len(mine) == 1 and mine[0]["kind"] == "team" and mine[0]["name"] == "Pixel Pact"
    assert len(mine[0]["members"]) == 3 and "Teamer" in mine[0]["members"]
    assert all(e["kind"] == "team" and len(e["members"]) == 3 for e in detail["entries"])
    assert len(detail["entries"]) == 16

    listing = client.get(f"/api/players/{pid}/tournaments").json()
    pending = listing["pending_match"]
    assert pending is not None
    played = client.post(f"/api/players/{pid}/tournaments/{cup['id']}/matches/{pending['id']}/play")
    assert played.status_code == 200, played.text
    me = next(m for m in played.json()["matches"] if m["id"] == pending["id"])
    assert me["winner"] is not None and me["maps"]
    state = client.get(_url(pid)).json()
    assert state["cups"][0]["registered"]


def test_clan_cup_registration_is_dropped_if_the_squad_breaks(client):
    pid = _career(client, start="2014-03-01", seed=22)
    _found(client, pid)
    ids = _force_members(pid, 2)
    cup = _clan_cup(client, pid)
    client.post(f"/api/players/{pid}/rest", json={"days": 1})
    assert client.post(f"/api/players/{pid}/tournaments/{cup['id']}/register").status_code == 200
    with SessionLocal() as db:
        hurt = db.get(Npc, ids[0])
        hurt.status, hurt.away_until = "injured", date(2015, 1, 1)
        db.commit()
    client.post(f"/api/players/{pid}/rest", json={"days": 40})
    detail = client.get(f"/api/players/{pid}/tournaments/{cup['id']}").json()
    assert not detail["user_registered"] and not any(e["includes_user"] for e in detail["entries"])
    with SessionLocal() as db:
        types = [e.type for e in db.scalars(select(WorldEvent).where(WorldEvent.player_id == pid))]
        assert "TEAM_CUP_WITHDRAWN" in types


def test_cup_result_updates_reputation_and_posts_a_thread(client):
    from types import SimpleNamespace

    from app.models import StEvent
    pid = _career(client)
    _found(client, pid)
    _force_members(pid, 2)
    with SessionLocal() as db:
        player = db.get(Player, pid)
        team = teams.active_team(db, player)
        before = team.reputation
        cup = SimpleNamespace(id=1, name="Clan Cup Spring 2014")
        teams.on_cup_result(db, player, cup, SimpleNamespace(placement="1st"), player.in_game_date, [])
        assert team.reputation > before and team.data["cups"] == 1
        assert db.scalar(select(StEvent).where(StEvent.player_id == pid, StEvent.type == "team_cup_win"))
        db.commit()
    assert client.get(_url(pid)).json()["team"]["cups_won"] == 1


def test_training_gets_a_bonus_right_after_a_scrim(client):
    pid = _career(client, seed=31)
    _found(client, pid)
    _force_members(pid, 2)
    client.post(_url(pid, "/scrim"), json={"hours": 2})
    from app.services import condition, life
    with SessionLocal() as db:
        player = db.get(Player, pid)
        learning, _ = condition.learning_extras(db, player)
        assert learning > life.learning_multiplier(player)
