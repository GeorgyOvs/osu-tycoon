"""Rivals: a few NPCs near your level who take it personally.

They're picked around your rank (compatriots first), get heated by snipes, head-to-head
matches and rank overtakes, cool off over time, and fade away when your paths diverge.
Rivals hunt your #1 scores, sign up for the same tournaments and slide into your DMs.
"""

import math
import random
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatMessage, Npc, Player, Rival
from app.services import media

MAX_RIVALS = 3
RANK_WINDOW = 2.5  # a rival's rank stays within [rank / 2.5, rank * 2.5] of yours
FADE_RATIO = 6.0  # beyond this rank ratio the rivalry fades
WEEKLY_COOLING = 2.0
HEAT_SNIPE, HEAT_MATCH, HEAT_OVERTAKE = 15.0, 25.0, 6.0
ST_HEAT_THRESHOLD = 40.0  # below this, overtakes are just DMs, not SillyTavern events

DM_LINES = {
    "new": ["saw your plays, not bad. don't get comfortable", "you're the one climbing the {country} ranks? gl",
            "hi :) we're about the same rank, wanna 1v1 sometime?"],
    "passed_by_user": ["ok you got me this week", "enjoy it while it lasts", "how are you improving so fast"],
    "passed_user": ["see you behind me o/", "back on top", "you slacking? :)"],
    "snipe_taken": ["you sniped my score?? it's on", "nice score. i'll take it back", "wow ok"],
    "snipe_back": ["told you i'd take it back", "that #1 is mine now", "your move"],
    "match_won": ["gg, you were better today", "rematch next tourney", "gg wp, that tb was insane"],
    "match_lost": ["gg ez (jk gg)", "better luck next time", "gg, close one"],
    "decline": ["sorry, busy grinding right now", "maybe when you're a bit higher ranked :)", "not today, gl though"],
}


def _rng(player: Player, *parts) -> random.Random:
    return random.Random(":".join(str(p) for p in (player.seed, "rival", *parts)))


def active(db: Session, player: Player) -> list[Rival]:
    return list(db.scalars(select(Rival).where(Rival.player_id == player.id, Rival.active.is_(True))))


def rival_for(db: Session, player: Player, npc_id: int | None) -> Rival | None:
    if npc_id is None:
        return None
    return db.scalar(select(Rival).where(Rival.player_id == player.id, Rival.npc_id == npc_id,
                                         Rival.active.is_(True)))


def dm(db: Session, player: Player, npc: Npc, kind: str, on: date) -> None:
    line = _rng(player, kind, npc.id, on.isoformat()).choice(DM_LINES[kind]).format(country=player.country)
    db.add(ChatMessage(player_id=player.id, date=on, channel=f"DM:{npc.name}", author=npc.name, content=line,
                       source="procedural"))


def _rank(player: Player) -> int:
    return player.global_rank or 1_000_000


def ensure_rivals(db: Session, player: Player) -> list[Rival]:
    """Fade rivalries that drifted apart and recruit new rivals up to MAX_RIVALS."""
    rivals = active(db, player)
    me = _rank(player)
    for r in rivals:
        npc = db.get(Npc, r.npc_id)
        if npc is None or npc.rank is None or max(npc.rank / me, me / npc.rank) > FADE_RATIO or npc.status == "retired":
            r.active = False
    rivals = [r for r in rivals if r.active]
    if len(rivals) >= MAX_RIVALS:
        return rivals

    taken = {r.npc_id for r in db.scalars(select(Rival).where(Rival.player_id == player.id))}
    candidates = [n for n in db.scalars(select(Npc).where(Npc.player_id == player.id, Npc.status == "active"))
                  if n.rank and me / RANK_WINDOW <= n.rank <= me * RANK_WINDOW and n.id not in taken]
    rng = _rng(player, "pick", player.in_game_date.isoformat())
    weights = [(3.0 if n.country == player.country else 1.0) / (1 + abs(math.log(n.rank / me))) for n in candidates]
    while candidates and len(rivals) < MAX_RIVALS:
        npc = rng.choices(candidates, weights=weights)[0]
        i = candidates.index(npc)
        candidates.pop(i)
        weights.pop(i)
        rival = Rival(player_id=player.id, npc_id=npc.id, since=player.in_game_date, heat=20.0, active=True,
                      record={"snipes_for": 0, "snipes_against": 0, "matches_won": 0, "matches_lost": 0})
        db.add(rival)
        rivals.append(rival)
        dm(db, player, npc, "new", player.in_game_date)
    db.flush()
    return rivals


def bump(rival: Rival, heat: float, record_key: str | None = None) -> None:
    rival.heat = min(100.0, rival.heat + heat)
    if record_key:
        rival.record = {**rival.record, record_key: rival.record.get(record_key, 0) + 1}


def weekly(db: Session, player: Player, rank_before: int | None) -> None:
    """Cooling and rank overtakes since the last tick."""
    me_before, me_now = rank_before or 1_000_000, _rank(player)
    for r in ensure_rivals(db, player):
        r.heat = max(0.0, r.heat - WEEKLY_COOLING)
        npc = db.get(Npc, r.npc_id)
        if npc is None or npc.rank is None:
            continue
        passed = me_before > npc.rank >= me_now  # we were behind, now ahead
        was_passed = me_before <= npc.rank < me_now
        if not (passed or was_passed):
            continue
        bump(r, HEAT_OVERTAKE)
        dm(db, player, npc, "passed_by_user" if passed else "passed_user", player.in_game_date)
        if r.heat >= ST_HEAT_THRESHOLD:
            media.rival_overtake(db, player, npc, passed)


def on_match(db: Session, player: Player, npc_ids: list[int], won: bool) -> None:
    for npc_id in npc_ids:
        rival = rival_for(db, player, npc_id)
        npc = db.get(Npc, npc_id)
        if rival and npc:
            bump(rival, HEAT_MATCH, "matches_won" if won else "matches_lost")
            dm(db, player, npc, "match_won" if won else "match_lost", player.in_game_date)


def on_snipe(db: Session, player: Player, npc_id: int | None, user_sniped: bool) -> None:
    rival = rival_for(db, player, npc_id)
    npc = db.get(Npc, npc_id) if npc_id else None
    if rival and npc:
        bump(rival, HEAT_SNIPE, "snipes_for" if user_sniped else "snipes_against")
        dm(db, player, npc, "snipe_taken" if user_sniped else "snipe_back", player.in_game_date)


def send_dm(db: Session, player: Player, npc_name: str, text: str):
    """The user writes to an NPC. The reply comes from the LLM through SillyTavern, in character."""
    from app.engine import world
    from app.services.media import _attitude, private_event

    npc = db.scalar(select(Npc).where(Npc.player_id == player.id, Npc.name == npc_name))
    if npc is None:
        return None
    channel = f"DM:{npc.name}"
    db.add(ChatMessage(player_id=player.id, date=player.in_game_date, channel=channel, author=player.name,
                       content=text, source="user"))
    db.flush()
    history = list(db.scalars(select(ChatMessage).where(ChatMessage.player_id == player.id,
                                                        ChatMessage.channel == channel)
                              .order_by(ChatMessage.id.desc()).limit(12)))[::-1]
    rival = rival_for(db, player, npc.id)
    legend = world.LEGENDS_BY_NAME.get(npc.name) if npc.kind == "legend" else None
    relationship = (f"rivals (heat {rival.heat:.0f}/100, record {rival.record})" if rival
                    else "no history yet")
    profile = f"{npc.kind} player, status {npc.status}, {_attitude(npc)}" + (f" {legend.note}" if legend else "")
    return private_event(db, player, "DM_REPLY", {
        "npc": {"name": npc.name, "country": npc.country, "rank": npc.rank, "profile": profile,
                "relationship": relationship},
        "conversation": [{"author": m.author, "content": m.content} for m in history],
    }, channel=channel)


def rival_npc_ids(db: Session, player: Player) -> set[int]:
    return {r.npc_id for r in active(db, player)}
