"""The living world: news, rankings, NPC profiles, tournaments."""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.engine import world
from app.models import Match, Npc, Player, Tournament, TournamentEntry
from app.routers.players import get_player_or_404
from app.schemas import (
    DraftActIn,
    DraftOut,
    EntryOut,
    LeaderboardOut,
    LeaderboardRowOut,
    MatchStrategyIn,
    MatchOut,
    NewsOut,
    NpcOut,
    TournamentDetailOut,
    TournamentsOut,
    TournamentSummaryOut,
)
from app.services import media, tournaments, world_service

router = APIRouter(prefix="/api/players/{player_id}", tags=["world"])

LISTING_WINDOW_DAYS = 120  # recent results and the next few months


def _player_with_world(db: Session, player_id: int) -> Player:
    player = get_player_or_404(db, player_id)
    world_service.ensure_world(db, player)
    db.commit()
    return player


@router.get("/news", response_model=list[NewsOut])
def news(
    player_id: int,
    limit: int = Query(default=50, le=200),
    min_importance: int = Query(default=1, ge=1, le=3),
    db: Session = Depends(get_db),
) -> list[NewsOut]:
    player = _player_with_world(db, player_id)
    return [
        NewsOut(id=e.id, date=e.date, type=e.type, message=e.message, importance=e.importance, data=e.data)
        for e in world_service.recent_news(db, player, limit, min_importance)
    ]


@router.get("/leaderboard", response_model=LeaderboardOut)
def leaderboard(
    player_id: int,
    country: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> LeaderboardOut:
    player = _player_with_world(db, player_id)
    rows = world_service.leaderboard(db, player, country, limit)
    you = world_service.user_row(player) if player.total_pp > 0 else None
    return LeaderboardOut(
        date=player.in_game_date,
        rows=[LeaderboardRowOut(**asdict(r)) for r in rows],
        you=LeaderboardRowOut(**asdict(you)) if you else None,
    )


@router.get("/npcs/{npc_id}", response_model=NpcOut)
def npc(player_id: int, npc_id: int, db: Session = Depends(get_db)) -> NpcOut:
    player = _player_with_world(db, player_id)
    n = db.get(Npc, npc_id)
    if n is None or n.player_id != player.id:
        raise HTTPException(404, "player not found in this world")
    legend = world.LEGENDS_BY_NAME.get(n.name) if n.kind == "legend" else None
    comps = world.composites(n.overall, n.style)
    ordered = sorted(comps, key=comps.get, reverse=True)
    story = dict(n.story or {})
    development = dict(n.development or {})
    rival_npc = db.get(Npc, story.get("rival_id")) if story.get("rival_id") else None
    return NpcOut(
        id=n.id, name=n.name, country=n.country, kind=n.kind, status=n.status, overall=world.display_overall(n.overall),
        composites=comps, form=n.form, pp=n.pp, rank=n.rank,
        best_rank=n.best_rank, titles=n.titles, away_until=n.away_until, note=legend.note if legend else "",
        aliases=list(legend.aliases) if legend else [], archetype=world.archetype(n.style),
        pp_potential=world.pp_overall(comps, player.in_game_date),
        tournament_strength=world.tournament_overall(comps),
        best_score_types=world.best_score_types(comps), peaks=ordered[:2], weaknesses=list(reversed(ordered[-2:])),
        match_stats=_npc_match_stats(db, player, n), development=development,
        storyline={"arc": story.get("arc", "historical" if n.kind == "legend" else "anchored"),
                   "phase": story.get("phase", n.status), "breakthroughs": development.get("breakthroughs", 0),
                   "comebacks": story.get("comebacks", 0), "focus": development.get("focus")},
        rival={"id": rival_npc.id, "name": rival_npc.name, "rank": rival_npc.rank} if rival_npc else None,
    )


def _npc_match_stats(db: Session, player: Player, npc: Npc) -> dict:
    entries = list(db.scalars(
        select(TournamentEntry).join(Tournament, Tournament.id == TournamentEntry.tournament_id)
        .where(Tournament.player_id == player.id, TournamentEntry.npc_id == npc.id)
    ))
    played = wins = upsets = 0
    for entry in entries:
        tournament = db.get(Tournament, entry.tournament_id)
        by_id = {e.id: e for e in tournament.entries}
        for match in tournament.matches:
            if match.played_on is None or entry.id not in (match.entry_a, match.entry_b):
                continue
            played += 1
            if match.winner == entry.id:
                wins += 1
                opponent_id = match.entry_b if match.entry_a == entry.id else match.entry_a
                opponent = by_id.get(opponent_id)
                if opponent and entry.seed > opponent.seed:
                    upsets += 1
    if not played:
        summary = "No official match sample yet"
    elif upsets and wins / played >= 0.5:
        summary = "Plays above their rank in tournaments"
    elif wins / played >= 0.65:
        summary = "Reliable tournament performer"
    elif wins / played < 0.4:
        summary = "Underperforms their rank under match pressure"
    else:
        summary = "Performs close to ranking expectations"
    return {"played": played, "wins": wins, "losses": played - wins, "upset_wins": upsets, "summary": summary}


def _summary(player: Player, t: Tournament) -> TournamentSummaryOut:
    today = player.in_game_date
    winner = next((e.name for e in t.entries if e.id == t.winner_entry_id), None)
    user_entry = next((e for e in t.entries if e.includes_user), None)
    can_register = (
        t.tier != "owc"
        and t.status == "upcoming"
        and not t.user_registered
        and t.registration_opens <= today < t.start_date
        and tournaments.eligible(player, t)
    )
    return TournamentSummaryOut(
        id=t.id, name=t.name, tier=t.tier, rank_min=t.rank_min, rank_max=t.rank_max, size=t.size,
        team_size=t.team_size, registration_opens=t.registration_opens, start_date=t.start_date,
        base_stars=t.base_stars, status=t.status, user_registered=t.user_registered, can_register=can_register,
        eligible=tournaments.eligible(player, t), winner=winner,
        user_placement=user_entry.placement if user_entry else None,
    )


def _match_out(t: Tournament, m: Match) -> MatchOut:
    entries = {e.id: e for e in t.entries}
    is_user = any(entries[x].includes_user for x in (m.entry_a, m.entry_b) if x in entries)
    return MatchOut(
        id=m.id, key=m.key, week=m.week, stage=m.stage, first_to=m.first_to, due=tournaments.due_date(t, m.week),
        entry_a=m.entry_a, entry_b=m.entry_b, winner=m.winner, score_a=m.score_a, score_b=m.score_b,
        played_on=m.played_on, is_user_match=is_user, maps=m.maps,
    )


@router.get("/tournaments", response_model=TournamentsOut)
def list_tournaments(player_id: int, db: Session = Depends(get_db)) -> TournamentsOut:
    player = _player_with_world(db, player_id)
    today = player.in_game_date
    ts = db.scalars(select(Tournament).where(Tournament.player_id == player.id).order_by(Tournament.start_date))
    shown = [t for t in ts if abs((t.start_date - today).days) <= LISTING_WINDOW_DAYS or t.status == "ongoing"]
    pending = tournaments.pending_user_match(db, player)
    return TournamentsOut(
        date=today,
        pending_match=_match_out(*pending) if pending else None,
        pending_tournament_id=pending[0].id if pending else None,
        tournaments=[_summary(player, t) for t in shown],
    )


def _tournament(db: Session, player: Player, tournament_id: int) -> Tournament:
    t = db.get(Tournament, tournament_id)
    if t is None or t.player_id != player.id:
        raise HTTPException(404, "tournament not found")
    return t


def _detail(player: Player, t: Tournament) -> TournamentDetailOut:
    return TournamentDetailOut(
        **_summary(player, t).model_dump(),
        entries=[
            EntryOut(
                id=e.id, kind=e.kind, name=e.name, country=e.country, seed=e.seed, npc_id=e.npc_id,
                includes_user=e.includes_user, placement=e.placement, members=[m["name"] for m in e.members],
            )
            for e in sorted(t.entries, key=lambda e: e.seed)
        ],
        matches=[_match_out(t, m) for m in t.matches],
        pools=t.pools,
    )


@router.get("/tournaments/{tournament_id}", response_model=TournamentDetailOut)
def tournament_detail(player_id: int, tournament_id: int, db: Session = Depends(get_db)) -> TournamentDetailOut:
    player = _player_with_world(db, player_id)
    return _detail(player, _tournament(db, player, tournament_id))


@router.post("/tournaments/{tournament_id}/register", response_model=TournamentSummaryOut)
def register(player_id: int, tournament_id: int, db: Session = Depends(get_db)) -> TournamentSummaryOut:
    player = _player_with_world(db, player_id)
    t = _tournament(db, player, tournament_id)
    try:
        tournaments.register(db, player, t)
    except tournaments.TournamentError as e:
        raise HTTPException(e.status_code, str(e)) from e
    db.commit()
    return _summary(player, t)


@router.post("/tournaments/{tournament_id}/matches/{match_id}/forfeit", response_model=TournamentDetailOut)
def forfeit_match(player_id: int, tournament_id: int, match_id: int, db: Session = Depends(get_db)) -> TournamentDetailOut:
    """Withdraw from your pending match (the opponent advances)."""
    player = _player_with_world(db, player_id)
    t = _tournament(db, player, tournament_id)
    pending = tournaments.pending_user_match(db, player)
    if pending is None or pending[1].id != match_id:
        raise HTTPException(409, "this isn't your next match")
    tournaments.forfeit(db, player, t, pending[1], reason="withdrew")
    db.commit()
    return _detail(player, t)


@router.post("/tournaments/{tournament_id}/matches/{match_id}/play", response_model=TournamentDetailOut)
def play_match(
    player_id: int,
    tournament_id: int,
    match_id: int,
    body: MatchStrategyIn | None = None,
    db: Session = Depends(get_db),
) -> TournamentDetailOut:
    """Play your match. Optional strategy: your ban and pick priorities (slot names); the AI fills the rest."""
    player = _player_with_world(db, player_id)
    t = _tournament(db, player, tournament_id)
    m = next((x for x in t.matches if x.id == match_id), None)
    if m is None:
        raise HTTPException(404, "match not found")
    rank_before = player.global_rank
    try:
        strategy = {"bans": body.bans, "picks": body.picks} if body and (body.bans or body.picks) else None
        _, news = tournaments.play_user_match(db, player, t, m, strategy)
    except tournaments.TournamentError as e:
        db.rollback()
        raise HTTPException(e.status_code, str(e)) from e
    media.after_action(db, player, rank_before, news=news)
    db.commit()
    return _detail(player, t)


# --- interactive ban/pick draft ---------------------------------------------------------------------


def _draft_call(db: Session, player_id: int, tournament_id: int, match_id: int, fn) -> DraftOut:
    from app.services import draft

    player = _player_with_world(db, player_id)
    t = _tournament(db, player, tournament_id)
    m = next((x for x in t.matches if x.id == match_id), None)
    if m is None:
        raise HTTPException(404, "match not found")
    rank_before = player.global_rank
    try:
        result = fn(draft, player, t, m)
    except tournaments.TournamentError as e:
        db.rollback()
        raise HTTPException(e.status_code, str(e)) from e
    view, news = result if isinstance(result, tuple) else (result, [])
    if news:
        media.after_action(db, player, rank_before, news=news)
    db.commit()
    return DraftOut(**view)


@router.get("/tournaments/{tournament_id}/matches/{match_id}/draft", response_model=DraftOut)
def get_draft(player_id: int, tournament_id: int, match_id: int, db: Session = Depends(get_db)) -> DraftOut:
    """Open (or resume) the live ban/pick room of your next match; the opponent's turns are already played."""
    return _draft_call(db, player_id, tournament_id, match_id, lambda d, p, t, m: d.start_or_get(db, p, t, m))


@router.post("/tournaments/{tournament_id}/matches/{match_id}/draft/act", response_model=DraftOut)
def draft_act(player_id: int, tournament_id: int, match_id: int, body: DraftActIn,
              db: Session = Depends(get_db)) -> DraftOut:
    return _draft_call(db, player_id, tournament_id, match_id, lambda d, p, t, m: d.act(db, p, t, m, body.slot))


@router.post("/tournaments/{tournament_id}/matches/{match_id}/draft/auto", response_model=DraftOut)
def draft_auto(player_id: int, tournament_id: int, match_id: int, body: MatchStrategyIn | None = None,
               db: Session = Depends(get_db)) -> DraftOut:
    strategy = {"bans": body.bans, "picks": body.picks} if body and (body.bans or body.picks) else None
    return _draft_call(db, player_id, tournament_id, match_id, lambda d, p, t, m: d.auto(db, p, t, m, strategy))


@router.post("/tournaments/{tournament_id}/matches/{match_id}/draft/warmup", response_model=DraftOut)
def draft_warmup(player_id: int, tournament_id: int, match_id: int, db: Session = Depends(get_db)) -> DraftOut:
    return _draft_call(db, player_id, tournament_id, match_id, lambda d, p, t, m: d.warmup(db, p, t, m))
