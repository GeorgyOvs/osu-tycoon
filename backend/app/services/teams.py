"""Teams and clans: invites, founding, recruiting, chemistry, weekly dynamics and clan-cup hooks.

The user is always part of their own team; `TeamMember` rows are the NPC teammates. Invites appear
in the weekly tick (deterministic per career and date). Everything the team does is also written to
the team log, the team's IRC channel and, for the big moments, the forum / SillyTavern outbox.
"""

import math
import random
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import simulation, world
from app.engine import teams as rules
from app.models import ChatMessage, Npc, Player, Rival, Team, TeamMember, Tournament
from app.services import life, media, rivals, story, tournaments

LOG_LIMIT = 40
MAX_CATCHUP_DAYS = 770
LOOKBACK_DAYS = 28
INVITE_RECENT_DAYS = 14


class TeamError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


# --- lookups ----------------------------------------------------------------------------------


def _by_status(db: Session, player: Player, status: str) -> Team | None:
    return db.scalar(select(Team).where(Team.player_id == player.id, Team.status == status).order_by(Team.id.desc()))


def active_team(db: Session, player: Player) -> Team | None:
    return _by_status(db, player, "active")


def pending_invite(db: Session, player: Player) -> Team | None:
    return _by_status(db, player, "invited")


def live_members(team: Team) -> list[TeamMember]:
    return [m for m in team.members if m.left_on is None]


def channel(team: Team) -> str:
    return f"#{team.tag.lower()}"


def _npc_comps(npc: Npc) -> dict[str, float]:
    return world.composites(npc.overall, npc.style)


def _user_comps(player: Player) -> dict[str, float]:
    return A.composites(simulation.effective_values(player))


def _set_data(team: Team, **updates) -> None:
    team.data = {**(team.data or {}), **updates}


def _log(team: Team, on: date, text: str) -> None:
    log = [*(team.data or {}).get("log", []), {"date": on.isoformat(), "text": text}]
    _set_data(team, log=log[-LOG_LIMIT:])


def _chat(db: Session, player: Player, team: Team, on: date, rng: random.Random, pool: list[str], n: int = 1,
          speakers: list[Npc] | None = None) -> None:
    npcs = speakers if speakers is not None else [db.get(Npc, m.npc_id) for m in live_members(team)]
    npcs = [n_ for n_ in npcs if n_ is not None]
    if not npcs:
        return
    for _ in range(n):
        who = rng.choice(npcs)
        others = [x.name for x in npcs if x is not who] + [player.name]
        db.add(ChatMessage(player_id=player.id, date=on, channel=channel(team), author=who.name,
                           content=rules.line(rng, pool, other=rng.choice(others), tag=team.tag),
                           source="procedural"))


def _news(db: Session, player: Player, team: Team, on: date, type_: str, message: str, importance: int,
          out: list, **data) -> None:
    tournaments._news(db, player, on, type_, message, importance, {"team_id": team.id, **data}, out)
    _log(team, on, message)


def _announce(db: Session, player: Player, team: Team, event_type: str, title: str, on: date, tone: str,
              upvotes: float, **data) -> None:
    media.emit(db, player, event_type, {"team": {"name": team.name, "tag": team.tag}, **data}, kind="news",
               title=title, flair="Team", base_upvotes=upvotes, tone=tone, fmt={"headline": title}, event_date=on)


def _user_rank(db: Session, player: Player) -> float:
    if player.global_rank:
        return float(player.global_rank)
    worst = db.scalar(select(func.max(Npc.rank)).where(Npc.player_id == player.id))
    return float(worst or 1_000_000) * 1.5


def _avg_rank(db: Session, player: Player, team: Team) -> float:
    ranks = [_user_rank(db, player)]
    for m in live_members(team):
        npc = db.get(Npc, m.npc_id)
        if npc is not None and npc.rank:
            ranks.append(float(npc.rank))
    return sum(ranks) / len(ranks)


def _reputation_target(avg_rank: float) -> float:
    return _clamp(110 - 22 * math.log10(max(avg_rank, 10.0)))


def refresh_roles(db: Session, player: Player, team: Team) -> None:
    people = {"user": _user_comps(player)}
    npcs = {}
    for m in live_members(team):
        npc = db.get(Npc, m.npc_id)
        if npc is not None:
            people[f"npc:{m.npc_id}"] = _npc_comps(npc)
            npcs[f"npc:{m.npc_id}"] = m
    roles = rules.assign_roles(people)
    team.user_role = roles.get("user", "member")
    for key, m in npcs.items():
        m.role = roles.get(key, "member")


# --- views ------------------------------------------------------------------------------------


def _member_view(db: Session, m: TeamMember) -> dict:
    npc = db.get(Npc, m.npc_id)
    return {"npc_id": m.npc_id, "name": npc.name if npc else "?", "country": npc.country if npc else "XX",
            "role": m.role, "bond": round(m.bond, 1), "rank": npc.rank if npc else None,
            "pp": round(npc.pp) if npc else 0, "overall": round(world.display_overall(npc.overall), 1) if npc else 0.0,
            "status": npc.status if npc else "retired", "joined_on": m.joined_on}


def _sponsor_estimate(team: Team, on: date) -> int:
    return rules.sponsor_monthly(team.reputation, media.community_size(on))


def _team_view(db: Session, player: Player, team: Team) -> dict:
    today = player.in_game_date
    data = team.data or {}
    members = live_members(team)
    scrim = date.fromisoformat(data["last_scrim"]) if data.get("last_scrim") else None
    since = (today - scrim).days if scrim else None
    active_npcs = sum(1 for m in members if (n := db.get(Npc, m.npc_id)) is not None and n.status == "active")
    return {
        "id": team.id, "name": team.name, "tag": team.tag, "status": team.status, "founded_on": team.founded_on,
        "chemistry": round(team.chemistry, 1), "reputation": round(team.reputation, 1), "user_role": team.user_role,
        "channel": channel(team), "size": len(members) + 1,
        "members": [_member_view(db, m) for m in members],
        "log": list(reversed((data.get("log") or [])[-30:])),
        "ready_for_cup": active_npcs >= rules.CUP_SIZE - 1,
        "scrim_today": scrim == today, "last_scrim": scrim,
        "cups_won": data.get("cups", 0),
        "expires_on": data.get("expires"),
        "perks": {
            "learning_bonus_pct": round((rules.learning_multiplier(team.chemistry, since) - 1) * 100, 1),
            "nerve_bonus_pct": round((rules.nerve_factor(team.chemistry) - 1) * 100, 1),
            "sponsor_monthly": _sponsor_estimate(team, today),
            "followers_weekly": rules.follower_gain(team.reputation),
        },
    }


def _cups(db: Session, player: Player) -> list[dict]:
    today = player.in_game_date
    team = active_team(db, player)
    ready = team is not None and _view_ready(db, team)
    out = []
    for t in db.scalars(select(Tournament).where(
        Tournament.player_id == player.id, Tournament.tier == "clan", Tournament.status != "finished"
    ).order_by(Tournament.start_date).limit(4)):
        window = t.registration_opens <= today < t.start_date and t.status == "upcoming"
        out.append({"id": t.id, "name": t.name, "start_date": t.start_date, "registration_opens": t.registration_opens,
                    "registered": t.user_registered, "status": t.status, "size": t.size,
                    "can_register": bool(window and ready and not t.user_registered)})
    return out


def _view_ready(db: Session, team: Team) -> bool:
    return sum(1 for m in live_members(team) if (n := db.get(Npc, m.npc_id)) is not None and n.status == "active") \
        >= rules.CUP_SIZE - 1


def found_blocker(db: Session, player: Player) -> str | None:
    today = player.in_game_date
    years = life.age(player)
    if today < rules.TEAMS_FROM:
        return f"clans aren't a thing yet in {today.year}"
    if years is not None and years < rules.MIN_AGE:
        return f"you must be at least {rules.MIN_AGE} to join a clan"
    if active_team(db, player) is not None:
        return "you're already in a team"
    if player.money < rules.FOUND_COST:
        return f"founding a team costs ${rules.FOUND_COST:.0f}; you have ${player.money:.0f}"
    return None


def state(db: Session, player: Player) -> dict:
    team = active_team(db, player)
    invite = pending_invite(db, player)
    invite_view = None
    if invite is not None:
        invite_view = _team_view(db, player, invite)
        invite_view["invited_by"] = next(
            (v["name"] for v in invite_view["members"] if v["npc_id"] == (invite.data or {}).get("invited_by")), None)
    history = [{"name": t.name, "tag": t.tag, "status": t.status, "founded_on": t.founded_on,
                "left_on": (t.data or {}).get("left_on")}
               for t in db.scalars(select(Team).where(Team.player_id == player.id, Team.status.in_(("left", "disbanded")))
                                   .order_by(Team.id.desc()).limit(8))]
    blocker = found_blocker(db, player)
    return {
        "date": player.in_game_date,
        "team": _team_view(db, player, team) if team else None,
        "invite": invite_view,
        "history": history,
        "cups": _cups(db, player),
        "can_found": blocker is None,
        "found_blocker": blocker,
        "found_cost": rules.FOUND_COST,
        "limits": {"max_size": rules.MAX_SIZE, "cup_size": rules.CUP_SIZE, "max_scrim_hours": rules.MAX_SCRIM_HOURS},
    }


# --- founding, invites, membership ------------------------------------------------------------


def _taken_names(db: Session, player: Player) -> set[str]:
    return {n.lower() for n in db.scalars(select(Team.name).where(Team.player_id == player.id))}


def _activate(db: Session, player: Player, team: Team, on: date, founded: bool, out: list) -> None:
    team.status = "active"
    _set_data(team, joined_on=on.isoformat(), last_activity=on.isoformat(), expires=None, founded_by_user=founded)
    team.reputation = _clamp(_reputation_target(_avg_rank(db, player, team)) * 0.6 + 5)
    refresh_roles(db, player, team)
    verb = "founded" if founded else "joined"
    _news(db, player, team, on, "TEAM_FORMED", f"You {verb} {team.name} [{team.tag}].", 2, out, event="formed")
    rng = random.Random(f"{player.seed}:teamchat:{team.id}:{on.isoformat()}")
    _chat(db, player, team, on, rng, rules.CELEBRATE if founded else ["welcome to {tag}!", "glad you joined o/"])
    _announce(db, player, team, "team_formed", f"{player.name} {verb} {team.name} [{team.tag}]", on,
              "welcoming, curious about the new squad", 150, verb=verb)


def found(db: Session, player: Player, name: str, tag: str) -> Team:
    name, tag = name.strip(), tag.strip()
    if not rules.valid_name(name):
        raise TeamError(422, "team name must be 3-32 letters, digits, spaces or - _ .")
    if not rules.valid_tag(tag):
        raise TeamError(422, "team tag must be 2-5 letters or digits")
    blocker = found_blocker(db, player)
    if blocker:
        raise TeamError(409, blocker)
    if name.lower() in _taken_names(db, player):
        raise TeamError(409, f"a team called {name} already exists")
    on = player.in_game_date
    player.money -= rules.FOUND_COST
    team = Team(player_id=player.id, name=name, tag=tag.upper(), founded_on=on, status="invited", chemistry=30.0,
                reputation=5.0, user_role="member", data={"log": []})
    db.add(team)
    db.flush()
    _activate(db, player, team, on, True, [])
    db.flush()
    return team


def _invite_for(db: Session, player: Player, team_id: int) -> Team:
    team = db.get(Team, team_id)
    if team is None or team.player_id != player.id:
        raise TeamError(404, "team not found")
    if team.status != "invited":
        raise TeamError(409, "this invitation is no longer open")
    return team


def accept_invite(db: Session, player: Player, team_id: int) -> Team:
    team = _invite_for(db, player, team_id)
    if active_team(db, player) is not None:
        raise TeamError(409, "leave your current team first")
    _activate(db, player, team, player.in_game_date, False, [])
    db.flush()
    return team


def decline_invite(db: Session, player: Player, team_id: int) -> Team:
    team = _invite_for(db, player, team_id)
    on = player.in_game_date
    team.status = "disbanded"
    _set_data(team, left_on=on.isoformat(), reason="declined")
    story.put_date(player, "team_invite_after", on + timedelta(days=rules.INVITE_COOLDOWN_DAYS))
    return team


def _require_active(db: Session, player: Player) -> Team:
    team = active_team(db, player)
    if team is None:
        raise TeamError(409, "you aren't in a team")
    return team


def leave(db: Session, player: Player) -> Team:
    team = _require_active(db, player)
    on = player.in_game_date
    team.status = "left"
    _set_data(team, left_on=on.isoformat(), reason="left")
    for m in live_members(team):
        m.left_on = on
    story.put_date(player, "team_invite_after", on + timedelta(days=rules.LEAVE_COOLDOWN_DAYS))
    tournaments._news(db, player, on, "TEAM_LEFT", f"You left {team.name}.", 1, {"team_id": team.id}, [])
    _log(team, on, f"You left {team.name}.")
    for t in db.scalars(select(Tournament).where(
        Tournament.player_id == player.id, Tournament.tier == "clan", Tournament.status == "upcoming",
        Tournament.user_registered.is_(True)
    )):
        t.user_registered = False
    return team


def _member_or_404(team: Team, npc_id: int) -> TeamMember:
    m = next((x for x in live_members(team) if x.npc_id == npc_id), None)
    if m is None:
        raise TeamError(404, "that player isn't in your team")
    return m


def kick(db: Session, player: Player, npc_id: int) -> Team:
    team = _require_active(db, player)
    m = _member_or_404(team, npc_id)
    npc = db.get(Npc, npc_id)
    on = player.in_game_date
    m.left_on = on
    team.chemistry = _clamp(team.chemistry - 4)
    for other in live_members(team):
        other.bond = _clamp(other.bond - 3)
    name = npc.name if npc else "?"
    _news(db, player, team, on, "TEAM_MEMBER_LEFT", f"{name} was removed from {team.name}.", 1, [], npc_id=npc_id)
    refresh_roles(db, player, team)
    return team


def _refusal_until(team: Team, npc_id: int, today: date) -> date | None:
    raw = (team.data or {}).get("refused", {}).get(str(npc_id))
    until = date.fromisoformat(raw) if raw else None
    return until if until and until > today else None


def _odds(db: Session, player: Player, team: Team, npc: Npc, bond: float = 30.0) -> float:
    rival = rivals.rival_for(db, player, npc.id)
    return rules.recruit_odds(_user_rank(db, player), float(npc.rank or 1_000_000), team.reputation, bond,
                              rival.heat if rival else 0.0, npc.motivation)


def recruit(db: Session, player: Player, npc_id: int) -> tuple[bool, str, TeamMember | None]:
    team = _require_active(db, player)
    npc = db.get(Npc, npc_id)
    if npc is None or npc.player_id != player.id:
        raise TeamError(404, "player not found")
    if len(live_members(team)) >= rules.MAX_SIZE - 1:
        raise TeamError(409, "the team is full")
    if any(m.npc_id == npc_id for m in live_members(team)):
        raise TeamError(409, f"{npc.name} is already in your team")
    if npc.status != "active" or npc.rank is None:
        raise TeamError(409, f"{npc.name} isn't available ({npc.status})")
    today = player.in_game_date
    until = _refusal_until(team, npc_id, today)
    if until:
        raise TeamError(409, f"{npc.name} declined recently; try again after {until}")
    rival = rivals.rival_for(db, player, npc.id)
    rng = random.Random(f"{player.seed}:recruit:{npc.id}:{today.isoformat()}")
    if rng.random() >= _odds(db, player, team, npc):
        refused = {**(team.data or {}).get("refused", {}),
                   str(npc_id): (today + timedelta(days=rules.REFUSAL_DAYS)).isoformat()}
        _set_data(team, refused=refused)
        if rival and rival.heat >= 40:
            why = "still sees you as a rival"
        elif (npc.rank or 0) < _user_rank(db, player) / 3:
            why = "wants a stronger team"
        else:
            why = "isn't interested right now"
        return False, f"{npc.name} declined: {why}", None
    m = TeamMember(team_id=team.id, npc_id=npc.id, role="member", joined_on=today,
                   bond=_clamp(35 + rng.uniform(-8, 8) + team.reputation / 10))
    team.members.append(m)
    db.flush()
    refresh_roles(db, player, team)
    _news(db, player, team, today, "TEAM_MEMBER_JOINED", f"{npc.name} joined {team.name}.", 1, [], npc_id=npc.id)
    _chat(db, player, team, today, rng, ["hi everyone o/", "glad to be here, {tag}!"], speakers=[npc])
    return True, f"{npc.name} joined {team.name}.", m


def candidates(db: Session, player: Player, limit: int = 20) -> list[dict]:
    team = _require_active(db, player)
    today = player.in_game_date
    taken = {m.npc_id for m in live_members(team)}
    rank = _user_rank(db, player)
    npcs = list(db.scalars(select(Npc).where(Npc.player_id == player.id, Npc.status == "active",
                                             Npc.rank.is_not(None))))
    npcs = [n for n in npcs if n.id not in taken]
    npcs.sort(key=lambda n: abs(math.log(max(n.rank, 1) / rank)) - (0.15 if n.country == player.country else 0.0))
    out = []
    for n in npcs[:limit]:
        rival = rivals.rival_for(db, player, n.id)
        comps = _npc_comps(n)
        until = _refusal_until(team, n.id, today)
        out.append({"npc_id": n.id, "name": n.name, "country": n.country, "rank": n.rank, "pp": round(n.pp),
                    "overall": round(world.display_overall(n.overall), 1), "odds": round(_odds(db, player, team, n), 2),
                    "rival": bool(rival), "strength": max(comps, key=lambda g: comps[g]),
                    "refused_until": until})
    return out


# --- scrims -----------------------------------------------------------------------------------


def scrim(db: Session, player: Player, hours: float) -> dict:
    team = _require_active(db, player)
    members = live_members(team)
    if not members:
        raise TeamError(409, "you need at least one teammate to scrim")
    if not 0.5 <= hours <= rules.MAX_SCRIM_HOURS:
        raise TeamError(422, f"a scrim lasts 0.5-{rules.MAX_SCRIM_HOURS:g} hours")
    today = player.in_game_date
    if (team.data or {}).get("last_scrim") == today.isoformat():
        raise TeamError(409, "you already played a scrim today")
    if player.injury == simulation.SEVERE_RSI:
        raise TeamError(409, f"recovering from severe RSI until {player.injury_until}")
    try:
        life.check_hours(player, hours)
    except life.LifeError as e:
        raise TeamError(e.status_code, str(e)) from e
    avg_bond = sum(m.bond for m in members) / len(members)
    gain = rules.chemistry_gain(hours, team.chemistry, avg_bond)
    before = team.chemistry
    team.chemistry = _clamp(team.chemistry + gain)
    for m in members:
        m.bond = _clamp(m.bond + 1.2 * hours)
    player.fatigue = _clamp(player.fatigue + 3.0 * hours)
    player.motivation = _clamp(player.motivation + 0.5 * hours)
    team.reputation = _clamp(team.reputation + 0.15 * hours)
    _set_data(team, last_scrim=today.isoformat(), last_activity=today.isoformat())
    rng = random.Random(f"{player.seed}:scrim:{team.id}:{today.isoformat()}")
    _chat(db, player, team, today, rng, rules.BANTER, n=2)
    message = f"Scrim with {team.name}: {hours:g}h, chemistry {before:.0f} -> {team.chemistry:.0f}."
    _log(team, today, message)
    return {"hours": hours, "chemistry_before": round(before, 1), "chemistry": round(team.chemistry, 1),
            "message": message, "team": _team_view(db, player, team)}


def learning_multiplier(db: Session, player: Player) -> float:
    team = active_team(db, player)
    if team is None or not live_members(team):
        return 1.0
    raw = (team.data or {}).get("last_scrim")
    since = (player.in_game_date - date.fromisoformat(raw)).days if raw else None
    return rules.learning_multiplier(team.chemistry, since)


# --- clan cups --------------------------------------------------------------------------------


def cup_squad(db: Session, player: Player) -> tuple[Team, list[dict]] | None:
    """(team, member dicts) if the team can field a full clan-cup lineup right now."""
    team = active_team(db, player)
    if team is None:
        return None
    candidates_ = []
    for m in live_members(team):
        npc = db.get(Npc, m.npc_id)
        if npc is not None and npc.status == "active":
            candidates_.append(npc)
    if len(candidates_) < rules.CUP_SIZE - 1:
        return None
    best = sorted(candidates_, key=lambda n: -n.overall)[: rules.CUP_SIZE - 1]
    return team, [tournaments._user_member(player), *[tournaments._npc_member(n) for n in best]]


def on_cup_result(db: Session, player: Player, t: Tournament, entry, on: date, out: list) -> None:
    team = active_team(db, player)
    if team is None or entry.placement is None:
        return
    first = entry.placement == "1st"
    team.reputation = _clamp(team.reputation + {"1st": 12, "2nd": 7, "3rd": 4, "4th": 3}.get(entry.placement, 1.5))
    team.chemistry = _clamp(team.chemistry + (6 if first else 2))
    for m in live_members(team):
        m.bond = _clamp(m.bond + (4 if first else 1))
    _set_data(team, last_activity=on.isoformat(), cups=(team.data or {}).get("cups", 0) + (1 if first else 0))
    _news(db, player, team, on, "TEAM_CUP_RESULT", f"{team.name} placed {entry.placement} at {t.name}.",
          3 if first else 2, out, tournament_id=t.id)
    if first:
        rng = random.Random(f"{player.seed}:cupwin:{t.id}")
        _chat(db, player, team, on, rng, rules.CELEBRATE, n=2)
        _announce(db, player, team, "team_cup_win", f"{team.name} wins {t.name}!", on,
                  "hyped, congratulating the squad", 600, tournament=t.name)


# --- weekly tick ------------------------------------------------------------------------------


def _mondays(after: date, upto: date):
    d = after + timedelta(days=1)
    d += timedelta(days=(7 - d.weekday()) % 7)
    while d <= upto:
        yield d
        d += timedelta(days=7)


def tick(db: Session, player: Player, news: list) -> None:
    target = player.in_game_date
    raw = story.get(player, "team_ticked_through")
    mark = date.fromisoformat(raw) if raw else target - timedelta(days=LOOKBACK_DAYS)
    mark = max(mark, target - timedelta(days=MAX_CATCHUP_DAYS), rules.TEAMS_FROM - timedelta(days=1))
    for on in _mondays(mark, target):
        _week(db, player, on, news, target)
    story.put_date(player, "team_ticked_through", max(target, mark))
    db.flush()


def _week(db: Session, player: Player, on: date, out: list, target: date) -> None:
    rng = random.Random(f"{player.seed}:team:{on.isoformat()}")
    invite = pending_invite(db, player)
    if invite is not None:
        expires = (invite.data or {}).get("expires")
        if expires and date.fromisoformat(expires) < on:
            invite.status = "disbanded"
            _set_data(invite, left_on=on.isoformat(), reason="expired")
            story.put_date(player, "team_invite_after", on + timedelta(days=rules.INVITE_COOLDOWN_DAYS // 2))
            tournaments._news(db, player, on, "TEAM_INVITE_EXPIRED", f"The invitation from {invite.name} expired.", 1,
                              {"team_id": invite.id}, out)
            db.flush()
    team = active_team(db, player)
    if team is not None:
        _week_active(db, player, team, on, rng, out)
    elif pending_invite(db, player) is None and (target - on).days <= INVITE_RECENT_DAYS:
        _maybe_invite(db, player, on, rng, out)


def _maybe_invite(db: Session, player: Player, on: date, rng: random.Random, out: list) -> None:
    if on < rules.TEAMS_FROM or not player.global_rank:
        return
    years = life.age(player, on)
    if years is not None and years < rules.MIN_AGE:
        return
    after = story.get(player, "team_invite_after")
    if after and on < date.fromisoformat(after):
        return
    threshold = max(2000.0, 150_000 * media.community_size(on))
    rank = player.global_rank
    if rank > threshold:
        return
    from app.services import integrity

    if integrity.reputation(player) < 25:  # nobody wants a tainted name on the roster
        return
    p = 0.05 + 0.10 * (1 - rank / threshold)
    if rng.random() >= p:
        return
    heated = {r.npc_id for r in db.scalars(select(Rival).where(Rival.player_id == player.id, Rival.active.is_(True),
                                                      Rival.heat >= 40))}
    pool = [n for n in db.scalars(select(Npc).where(Npc.player_id == player.id, Npc.status == "active",
                                                    Npc.rank.is_not(None)))
            if rank / 3 <= n.rank <= rank * 2 and n.id not in heated]
    if len(pool) < 2:
        return
    pool.sort(key=lambda n: n.id)
    weights = [3.0 if n.country == player.country else 1.0 for n in pool]
    chosen: list[Npc] = []
    for _ in range(rng.randint(2, 4)):
        if not pool:
            break
        n = rng.choices(pool, weights)[0]
        i = pool.index(n)
        pool.pop(i)
        weights.pop(i)
        chosen.append(n)
    name, tag = rules.team_name(rng, _taken_names(db, player))
    team = Team(player_id=player.id, name=name, tag=tag, founded_on=on, status="invited", chemistry=30.0,
                reputation=10.0, user_role="member",
                data={"log": [], "expires": (on + timedelta(days=rules.INVITE_DAYS)).isoformat(),
                      "invited_by": chosen[0].id, "last_activity": on.isoformat()})
    db.add(team)
    db.flush()
    for n in chosen:
        team.members.append(TeamMember(team_id=team.id, npc_id=n.id, role="member", joined_on=on,
                                       bond=_clamp(35 + rng.uniform(-8, 8))))
    db.flush()
    leader = chosen[0]
    tournaments._news(db, player, on, "TEAM_INVITE", f"{leader.name} invites you to join {team.name} [{team.tag}].", 2,
                      {"team_id": team.id, "npc_id": leader.id}, out)
    db.add(ChatMessage(player_id=player.id, date=on, channel=f"DM:{leader.name}", author=leader.name,
                       content=rules.line(rng, rules.INVITE_DM, team=team.name), source="procedural"))


def _week_active(db: Session, player: Player, team: Team, on: date, rng: random.Random, out: list) -> None:
    last = date.fromisoformat((team.data or {}).get("last_activity") or on.isoformat())
    idle = max(0, (on - last).days)
    team.chemistry = _clamp(team.chemistry - rules.weekly_decay(team.chemistry, idle))

    # Members: retirements, drifting away, hiatuses.
    for m in list(live_members(team)):
        npc = db.get(Npc, m.npc_id)
        m.bond = _clamp(m.bond + (-1.5 if idle > 14 else 0.2))
        reason = None
        if npc is None or npc.status == "retired":
            reason = "retired"
        elif m.bond < 8:
            reason = "drifted away"
        if reason:
            m.left_on = on
            name = npc.name if npc else "?"
            _news(db, player, team, on, "TEAM_MEMBER_LEFT", f"{name} left {team.name}: {reason}.", 1, out,
                  npc_id=m.npc_id)
    members = live_members(team)

    # Something happens roughly every third week.
    roll = rng.random()
    if members and roll < 0.30:
        npcs = [db.get(Npc, m.npc_id) for m in members]
        kind = rng.choices(["banter", "drama", "poach"], [60, 18, 12])[0]
        if kind == "banter":
            _chat(db, player, team, on, rng, rules.BANTER, n=rng.randint(1, 3))
            team.chemistry = _clamp(team.chemistry + 0.8)
        elif kind == "drama" and len(members) >= 2:
            a, b = rng.sample([n for n in npcs if n is not None], 2) if len([n for n in npcs if n]) >= 2 else (None, None)
            if a is not None:
                team.chemistry = _clamp(team.chemistry - 3)
                for m in members:
                    if m.npc_id in (a.id, b.id):
                        m.bond = _clamp(m.bond - 4)
                _news(db, player, team, on, "TEAM_DRAMA", f"Tension in {team.name}: {a.name} and {b.name} had an argument.",
                      1, out)
                _chat(db, player, team, on, rng, rules.DRAMA, n=2, speakers=[a, b])
                if team.reputation >= 30:
                    _announce(db, player, team, "team_drama", f"Drama in {team.name}: {a.name} vs {b.name}", on,
                              "gossipy, taking sides", 200)
        elif kind == "poach":
            shaky = [m for m in members if m.bond < 50]
            if shaky and team.reputation < 70:
                m = rng.choice(shaky)
                npc = db.get(Npc, m.npc_id)
                m.left_on = on
                name = npc.name if npc else "?"
                _news(db, player, team, on, "TEAM_MEMBER_LEFT", f"{name} left {team.name}: joined another team.", 1,
                      out, npc_id=m.npc_id)
                team.chemistry = _clamp(team.chemistry - 3)
        members = live_members(team)

    # Reputation follows the squad's strength; milestones, followers and sponsors.
    before = team.reputation
    target_rep = _reputation_target(_avg_rank(db, player, team))
    team.reputation = _clamp(team.reputation + (target_rep - team.reputation) * 0.05)
    for mark in (25, 50, 75):
        if before < mark <= team.reputation:
            _news(db, player, team, on, "TEAM_MILESTONE", f"{team.name} reputation reached {mark}.", 2, out)
            if mark >= 50:
                _announce(db, player, team, "team_milestone", f"{team.name} is becoming a name in the community", on,
                          "impressed", 300, reputation=mark)
    player.followers += rules.follower_gain(team.reputation)
    month = on.strftime("%Y-%m")
    if (team.data or {}).get("sponsor_month") != month:
        _set_data(team, sponsor_month=month)
        pay = _sponsor_estimate(team, on)
        if pay > 0:
            player.money += pay
            _news(db, player, team, on, "TEAM_SPONSOR", f"{team.name} sponsor pays ${pay:,} this month.", 1, out,
                  amount=pay)
    if members and rng.random() < 0.45:
        _chat(db, player, team, on, rng, rules.BANTER, n=1)
    refresh_roles(db, player, team)
