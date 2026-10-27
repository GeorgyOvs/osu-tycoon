"""The slice of the osu! API v2 that the tycoon client (lazer fork) talks to.

Login: username = a career's name, any password. The token names the career, which also becomes the client's
active career. Everything is local; nothing here is reachable by or forwarded to osu.ppy.sh.
"""
import email
from datetime import datetime, timezone
import json
import itertools
import secrets
import time
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import MIRROR_DOWNLOAD_URL
from app.db import SessionLocal, get_db
from app.models import Beatmap, BeatmapSet, Player, RealPlay, Score
from app.services import beatmap_index, client_scores, leaderboards, osu_api, osu_files, translate, world_service

router = APIRouter(tags=["osu-api"])

TOKEN_PREFIX = "tycoon."
TOKEN_LIFETIME = 30 * 24 * 3600


def _form(content_type: str, body: bytes) -> dict[str, str]:
    """osu-framework posts parameters as multipart; accept urlencoded too."""
    if content_type.startswith("multipart/"):
        message = email.message_from_bytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
        return {part.get_param("name", header="content-disposition"): part.get_payload(decode=True).decode()
                for part in message.get_payload() if part.get_param("name", header="content-disposition")}
    return {k: v[0] for k, v in parse_qs(body.decode()).items()}


def _token_error(hint: str) -> JSONResponse:
    return JSONResponse({"error": "invalid_grant", "hint": hint, "message": hint}, status_code=401)


def _token(player: Player) -> dict:
    return {"access_token": f"{TOKEN_PREFIX}{player.id}.{secrets.token_hex(8)}",
            "refresh_token": f"{TOKEN_PREFIX}{player.id}.refresh", "expires_in": TOKEN_LIFETIME,
            "token_type": "Bearer"}


def _player_from_token(db: Session, token: str) -> Player | None:
    if not token.startswith(TOKEN_PREFIX):
        return None
    player_id = token[len(TOKEN_PREFIX):].split(".")[0]
    return db.get(Player, int(player_id)) if player_id.isdigit() else None


@router.post("/oauth/token")
async def oauth_token(request: Request, db: Session = Depends(get_db)):
    form = _form(request.headers.get("content-type", ""), await request.body())
    if form.get("grant_type") == "refresh_token":
        player = _player_from_token(db, form.get("refresh_token", ""))
    else:
        name = form.get("username", "").strip()
        player = db.scalar(select(Player).where(func.lower(Player.name) == name.lower())) if name else None
        if player is None:
            return _token_error(f"No career named '{name}'. Log in with the name of a tycoon career.")
    if player is None:
        return _token_error("Session expired, log in again.")
    client_scores.set_active_player(db, player)
    db.commit()
    return _token(player)


def current_player(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> Player:
    player = _player_from_token(db, authorization.removeprefix("Bearer ").strip())
    if player is None:
        raise HTTPException(401, "Unauthorized")
    world_service.ensure_world(db, player)
    return player


@router.get("/api/v2/me")
@router.get("/api/v2/me/{ruleset}")
def me(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    user = osu_api.career_user(db, player)
    db.commit()
    return user | {"session_verification_method": None}


@router.get("/api/v2/users/{lookup}")
@router.get("/api/v2/users/{lookup}/{ruleset}")
def user(lookup: str, key: str = "id", player: Player = Depends(current_player), db: Session = Depends(get_db)):
    found = osu_api.find_user(db, player, lookup, by_name=key == "username")
    if found is None:
        raise HTTPException(404, "This player isn't in your world.")
    db.commit()
    return found


@router.get("/api/v2/users/{user_id}/scores/{kind}")
def user_scores(user_id: int, kind: str, limit: int = Query(default=5, ge=1, le=100),
                offset: int = Query(default=0, ge=0), player: Player = Depends(current_player),
                db: Session = Depends(get_db)):
    scores = osu_api.user_scores(db, player, user_id, kind, limit, offset)
    if scores is None:
        raise HTTPException(404, "This player isn't in your world.")
    return scores


@router.get("/api/v2/beatmaps/{beatmap_id}/scores")
def beatmap_scores(request: Request, beatmap_id: int, type: str = "global", mode: str = "osu",
                   limit: int = Query(default=50, ge=1, le=100), player: Player = Depends(current_player),
                   db: Session = Depends(get_db)):
    empty = {"scores": [], "user_score": None, "score_count": 0}
    if mode != "osu":
        return empty
    wanted = request.query_params.getlist("mods[]")
    mods = {m.upper() for m in wanted if m.upper() not in ("CL", "CR")} if wanted else None
    try:
        scores, mine = osu_api.board_scores(db, player, beatmap_id, type, mods, limit)
    except (beatmap_index.NotPlayable, osu_files.BeatmapNotFound):
        return empty  # unranked, not ranked yet in the career's year, or unknown: an empty board
    db.commit()
    return {"scores": scores, "user_score": mine, "score_count": len(scores)}


# Lists lazer fetches after login; the tycoon world has no friends list, blocks or announcements yet.
@router.get("/api/v2/friends")
@router.get("/api/v2/blocks")
def empty_list(player: Player = Depends(current_player)):
    return []


# Score submission handshake. Lazer asks for a token before every play and submits at the end; the career
# itself records plays through /api/client/scores (TycoonScoreReporter), so this only keeps lazer's flow happy.
_tokens = itertools.count(int(time.time()))


@router.post("/api/v2/beatmaps/{beatmap_id}/solo/scores")
def solo_token(beatmap_id: int, player: Player = Depends(current_player)):
    return {"id": next(_tokens)}


@router.put("/api/v2/beatmaps/{beatmap_id}/solo/scores/{token}")
async def solo_submit(request: Request, beatmap_id: int, token: int, player: Player = Depends(current_player)):
    body = await request.json()
    # The play itself reaches the career through /api/client/scores, sent at the same moment; wait for it briefly
    # so lazer's results screen can show the pp and the place on the map's board.
    pp_value, position = await run_in_threadpool(_career_result, player.id, beatmap_id, int(body.get("total_score", 0)))
    return {
        "id": token, "user": {"id": player.id, "username": player.name, "country_code": player.country},
        "beatmap_id": beatmap_id, "ruleset_id": body.get("ruleset_id", 0), "rank": body.get("rank", "D"),
        "total_score": body.get("total_score", 0), "accuracy": body.get("accuracy", 0),
        "max_combo": body.get("max_combo", 0), "mods": body.get("mods", []),
        "statistics": body.get("statistics", {}), "maximum_statistics": body.get("maximum_statistics", {}),
        "passed": body.get("passed", False),
        "ended_at": body.get("ended_at") or datetime.now(timezone.utc).isoformat(), "pp": pp_value, "position": position,
        "has_replay": False, "ranked": pp_value is not None,
    }


def _career_result(player_id: int, beatmap_id: int, total_score: int, wait_s: float = 3.0) -> tuple[float | None, int | None]:
    deadline = time.monotonic() + wait_s
    while True:
        with SessionLocal() as db:
            play = db.scalar(select(RealPlay).where(RealPlay.player_id == player_id, RealPlay.beatmap_id == beatmap_id,
                                                    RealPlay.source == "client", RealPlay.score_value == total_score)
                             .order_by(RealPlay.id.desc()))
            if play is not None:
                if play.career_score_id is None:
                    return None, None
                score = db.get(Score, play.career_score_id)
                player = db.get(Player, player_id)
                placed = leaderboards.placement(db, player, beatmap_id, score.score_value) if score and player else None
                return (round(score.pp, 2) if score else None), (placed[0] if placed else None)
        if time.monotonic() > deadline:
            return None, None
        time.sleep(0.2)


def _page(items: list[dict], total: int, page: int) -> dict:
    more = page * osu_api.PAGE_SIZE < total
    return {"ranking": items, "cursor": {"page": page + 1} if more else None, "total": total}


@router.get("/api/v2/rankings/{mode}/country")
def country_rankings(mode: str, page: int = Query(default=1, ge=1, le=200), player: Player = Depends(current_player),
                     db: Session = Depends(get_db)):
    if mode != "osu":
        return _page([], 0, page)
    items, total = osu_api.country_rankings(db, player, page)
    return _page(items, total, page)


@router.get("/api/v2/rankings/{mode}/{kind}")
def user_rankings(mode: str, kind: str, page: int = Query(default=1, ge=1, le=200), country: str | None = None,
                  player: Player = Depends(current_player), db: Session = Depends(get_db)):
    """performance and score both list the pp ranking: the world doesn't track a separate ranked-score race."""
    if mode != "osu" or kind not in ("performance", "score"):
        return _page([], 0, page)
    items, total = osu_api.rankings(db, player, country, page)
    return _page(items, total, page)


# --- Career screens inside the client -----------------------------------------------------------------------
# A flat facade over the regular career endpoints, addressed by the login token instead of a player id.

# Text in these responses is Russian, translated with the web UI's dictionaries (services/translate).
INJURY_LABELS = {"healthy": "Healthy", "minor_strain": "Minor wrist strain", "severe_rsi": "Severe tendonitis"}


def _tycoon_error(e: HTTPException) -> JSONResponse:
    return JSONResponse({"error": translate.ru1(str(e.detail))}, status_code=e.status_code)


def _events_json(events: list[tuple[str, str, str]]) -> list[dict]:
    messages = translate.ru([m for _, _, m in events])
    return [{"date": d, "type": t, "message": m} for (d, t, _), m in zip(events, messages)]


def _action_json(result) -> dict:
    return {
        "start_date": result.start_date.isoformat(), "end_date": result.end_date.isoformat(), "days": result.days,
        "events": _events_json([(e.date.isoformat(), e.type, e.message) for e in result.events]),
    }


@router.get("/api/v2/tycoon/career")
def tycoon_career(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    from app.routers import career
    from app.routers.client import _hand_day_out
    from app.services import profile

    out = profile.to_player_out(player)
    life_out = out.life
    drills = career.list_drills(player.id, db)
    hand_day = _hand_day_out(db, player).model_dump()
    # Translate everything in one round trip to the worker.
    texts = ([out.era_label, INJURY_LABELS.get(out.injury.state, out.injury.state), hand_day["blocked"] or ""]
             + [g.label for g in out.attributes] + [d.label for d in drills] + [d.description for d in drills])
    ru = iter(translate.ru(texts))
    era, injury_label, blocked = next(ru), next(ru), next(ru)
    group_labels = [next(ru) for _ in out.attributes]
    drill_labels = [next(ru) for _ in drills]
    drill_descriptions = [next(ru) for _ in drills]
    hand_day["blocked"] = blocked or None
    data = {
        "name": out.name, "country": out.country, "date": out.in_game_date.isoformat(), "era": era,
        "injury_label": injury_label,
        "overall": round(out.overall, 1), "form": round(out.form, 1),
        "fatigue": round(out.conditions.fatigue, 1), "motivation": round(out.conditions.motivation, 1),
        "morale": round(out.conditions.morale, 1), "injury": out.injury.state,
        "injury_until": out.injury.until.isoformat() if out.injury.until else None,
        "pp": round(out.total_pp, 2), "rank": out.global_rank, "previous_rank": out.previous_rank,
        "accuracy": round(out.accuracy, 2), "play_count": out.play_count,
        "money": round(life_out.money, 2) if life_out else None,
        "free_hours_today": round(life_out.free_hours_today, 1) if life_out else None,
        "groups": [{"key": g.key, "label": label, "value": round(g.value, 1)}
                   for g, label in zip(out.attributes, group_labels)],
        "hand_day": hand_day,
        "drills": [d.model_dump() | {"label": label, "description": description}
                   for d, label, description in zip(drills, drill_labels, drill_descriptions)],
    }
    db.commit()
    return data


@router.post("/api/v2/tycoon/train")
async def tycoon_train(request: Request, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    from app.routers import career
    from app.schemas import TrainRequest

    try:
        body = TrainRequest(**await request.json())
        return _action_json(career.train(player.id, body, db))
    except HTTPException as e:
        return _tycoon_error(e)
    except ValueError as e:
        return JSONResponse({"error": translate.ru1(str(e))}, status_code=422)


@router.post("/api/v2/tycoon/rest")
async def tycoon_rest(request: Request, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    from app.routers import career
    from app.schemas import RestRequest

    try:
        body = RestRequest(**await request.json())
        return _action_json(career.rest(player.id, body, db))
    except HTTPException as e:
        return _tycoon_error(e)
    except ValueError as e:
        return JSONResponse({"error": translate.ru1(str(e))}, status_code=422)


@router.post("/api/v2/tycoon/hand-day/finish")
def tycoon_finish_hand_day(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    from app.routers.client import finish_hand_day

    try:
        done = finish_hand_day(player.id, db)
    except HTTPException as e:
        return _tycoon_error(e)
    end = done.end_date.date().isoformat()
    events = [(e["date"], e["type"], e["message"]) for e in done.events] + [(end, "NEWS", n) for n in done.news]
    return {"start_date": done.start_date.date().isoformat(), "end_date": end, "days": 1,
            "events": _events_json(events)}


# --- Tournaments inside the client --------------------------------------------------------------------------

TOURNAMENT_STATUS = {"upcoming": "скоро", "registration": "регистрация", "ongoing": "идёт", "finished": "завершён"}


def _pending(db: Session, player: Player):
    from app.services import tournaments as tournaments_service

    return tournaments_service.pending_user_match(db, player)


@router.get("/api/v2/tycoon/tournaments")
def tycoon_tournaments(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    from app.routers import world as world_router
    from app.services import draft as draft_service

    listing = world_router.list_tournaments(player.id, db)
    pending = None
    if listing.pending_match is not None:
        t, m = _pending(db, player)
        mine = next(e for e in t.entries if e.id in (m.entry_a, m.entry_b) and e.includes_user)
        opponent = next((e for e in t.entries if e.id in (m.entry_a, m.entry_b) and e is not mine), None)
        row = draft_service._draft_row(db, m)
        pending = {"tournament_id": t.id, "tournament_name": t.name, "match_id": m.id, "stage": m.stage,
                   "first_to": m.first_to, "due": tournaments_due(t, m), "opponent": opponent.name if opponent else "?",
                   "opponent_seed": opponent.seed if opponent else None, "my_seed": mine.seed,
                   "draft_open": row is not None and not row.finished,
                   "playable": tournaments_due(t, m) <= player.in_game_date.isoformat()}
    items = listing.tournaments
    texts = [i.user_placement or "" for i in items] + [pending["stage"] if pending else ""]
    ru = translate.ru(texts)
    if pending:
        pending["stage"] = ru[-1]
    out = [{
        "id": i.id, "name": i.name, "tier": i.tier, "status": TOURNAMENT_STATUS.get(i.status, i.status),
        "registration_opens": i.registration_opens.isoformat(), "start_date": i.start_date.isoformat(),
        "rank_min": i.rank_min, "rank_max": i.rank_max, "size": i.size, "team_size": i.team_size,
        "stars": i.base_stars, "user_registered": i.user_registered, "can_register": i.can_register,
        "eligible": i.eligible, "winner": i.winner, "user_placement": placement or None,
    } for i, placement in zip(items, ru)]
    db.commit()
    return {"date": listing.date.isoformat(), "pending": pending, "tournaments": out}


def tournaments_due(t, m) -> str:
    from app.services import tournaments as tournaments_service

    return tournaments_service.due_date(t, m.week).isoformat()


@router.post("/api/v2/tycoon/tournaments/{tournament_id}/register")
def tycoon_register(tournament_id: int, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    from app.routers import world as world_router

    try:
        world_router.register(player.id, tournament_id, db)
    except HTTPException as e:
        return _tycoon_error(e)
    return {"ok": True}


def _draft_json(d, db: Session) -> dict:
    """The draft from the user's point of view: 'me' and 'them' instead of sides a and b."""
    me = d.user_side
    them = "b" if me == "a" else "a"

    def mine(side):
        return None if side is None else side == me

    slots = [{
        "slot": s["slot"], "mods": s["mods"], "stars": s["stars"], "title": s["title"], "beatmap_id": s["beatmap_id"],
        "state": s["state"], "mine": mine(s.get("by")), "legal": s["legal"],
        "my_score": s.get(f"score_{me}"), "their_score": s.get(f"score_{them}"),
        "won": None if s.get("winner") is None else s["winner"] == me,
    } for s in d.slots]
    log = [{
        "kind": e["kind"], "slot": e.get("slot"), "mine": e.get("side") == me if e.get("side") else None,
        "my_score": e.get(f"score_{me}"), "their_score": e.get(f"score_{them}"),
    } for e in d.log]
    [stage] = translate.ru([d.stage])
    awaiting = dict(d.awaiting) if d.awaiting else None
    if awaiting:
        beatmap = db.get(Beatmap, awaiting["beatmap_id"]) if awaiting.get("beatmap_id") else None
        awaiting["beatmapset_id"] = beatmap.beatmapset_id if beatmap else None
    return {
        "match_id": d.match_id, "tournament_id": d.tournament_id, "stage": stage, "first_to": d.first_to,
        "finished": d.finished, "me": d.names[me], "them": d.names[them],
        "my_score": d.score[me], "their_score": d.score[them],
        "turn": d.turn["kind"], "my_turn": d.turn["mine"], "legal": d.legal, "slots": slots, "log": log,
        "hand": d.hand, "awaiting": awaiting, "warmup_available": d.warmup["available"],
    }


def _last_finished_match(db: Session, player: Player):
    from app.models import Match, MatchDraft, Tournament

    row = db.scalar(select(MatchDraft).where(MatchDraft.player_id == player.id, MatchDraft.finished.is_(True))
                    .order_by(MatchDraft.id.desc()))
    m = db.get(Match, row.match_id) if row else None
    t = db.get(Tournament, m.tournament_id) if m else None
    return (t, m) if t and m else None


def _draft_action(player: Player, db: Session, action: str, body: dict | None = None):
    from app.routers import world as world_router
    from app.schemas import DraftActIn, DraftHandIn

    pending = _pending(db, player)
    if pending is None and action == "get":
        pending = _last_finished_match(db, player)  # show how the match that just ended went
    if pending is None:
        return JSONResponse({"error": "нет назначенного матча"}, status_code=409)
    t, m = pending
    calls = {
        "get": lambda: world_router.get_draft(player.id, t.id, m.id, db),
        "act": lambda: world_router.draft_act(player.id, t.id, m.id, DraftActIn(**(body or {})), db),
        "hand": lambda: world_router.draft_hand(player.id, t.id, m.id, DraftHandIn(**(body or {})), db),
        "simulate-map": lambda: world_router.draft_simulate_map(player.id, t.id, m.id, db),
        "auto": lambda: world_router.draft_auto(player.id, t.id, m.id, None, db),
        "warmup": lambda: world_router.draft_warmup(player.id, t.id, m.id, db),
    }
    try:
        return _draft_json(calls[action](), db)
    except HTTPException as e:
        return _tycoon_error(e)
    except ValueError as e:
        return JSONResponse({"error": translate.ru1(str(e))}, status_code=422)


@router.get("/api/v2/tycoon/draft")
def tycoon_draft(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    return _draft_action(player, db, "get")


@router.post("/api/v2/tycoon/draft/{action}")
async def tycoon_draft_action(action: str, request: Request, player: Player = Depends(current_player),
                              db: Session = Depends(get_db)):
    if action not in ("act", "hand", "simulate-map", "auto", "warmup"):
        raise HTTPException(404, "unknown draft action")
    raw = await request.body()
    return _draft_action(player, db, action, json.loads(raw) if raw else None)


@router.post("/api/v2/tycoon/match/forfeit")
def tycoon_forfeit(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    from app.routers import world as world_router

    pending = _pending(db, player)
    if pending is None:
        return JSONResponse({"error": "нет назначенного матча"}, status_code=409)
    try:
        world_router.forfeit_match(player.id, pending[0].id, pending[1].id, db)
    except HTTPException as e:
        return _tycoon_error(e)
    return {"ok": True}


@router.get("/api/v2/beatmapsets/{beatmapset_id}/download")
def beatmapset_download(beatmapset_id: int, player: Player = Depends(current_player)):
    """Lazer downloads maps through the API; the tycoon has no files of its own, so send it to the mirror."""
    return RedirectResponse(MIRROR_DOWNLOAD_URL.format(beatmapset_id=beatmapset_id))


# --- The world and tournament brackets inside the client ----------------------------------------------------

@router.get("/api/v2/tycoon/world")
def tycoon_world(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    news = world_service.recent_news(db, player, 40, 1)
    messages = translate.ru([n.message for n in news])
    out = {**world_service.world_size(db, player),
           "news": [{"date": n.date.isoformat(), "type": n.type, "importance": n.importance, "message": m}
                    for n, m in zip(news, messages)]}
    db.commit()
    return out


@router.post("/api/v2/tycoon/world/grow")
async def tycoon_grow_world(request: Request, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    body = await request.json()
    size = int(body.get("size", 0))
    if not 1 <= size <= world_service.MAX_WORLD_SIZE:
        return JSONResponse({"error": f"размер мира: от 1 до {world_service.MAX_WORLD_SIZE:,}"}, status_code=422)
    added = world_service.grow_world(db, player, size)
    db.commit()
    return {"added": added, **world_service.world_size(db, player)}


def _bracket_side(key: str) -> str:
    return "lower" if key.startswith("L") else "upper" if key.startswith("W") else "final"


@router.get("/api/v2/tycoon/tournaments/{tournament_id}/bracket")
def tycoon_bracket(tournament_id: int, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    """Every match of a tournament by round: upper bracket, lower bracket, then the grand final."""
    from app.models import Tournament

    t = db.get(Tournament, tournament_id)
    if t is None or t.player_id != player.id:
        return JSONResponse({"error": "турнир не найден"}, status_code=404)
    entries = {e.id: e for e in t.entries}
    rounds: dict[str, dict] = {}
    for m in sorted(t.matches, key=lambda m: (m.week, _bracket_side(m.key) != "upper", m.key)):
        prefix = m.key.split("-")[0]
        rnd = rounds.setdefault(prefix, {"key": prefix, "stage": m.stage, "side": _bracket_side(m.key),
                                         "week": m.week, "first_to": m.first_to, "matches": []})
        a, b = entries.get(m.entry_a), entries.get(m.entry_b)
        rnd["matches"].append({
            "a": a.name if a else None, "b": b.name if b else None,
            "a_seed": a.seed if a else None, "b_seed": b.seed if b else None,
            "score_a": m.score_a, "score_b": m.score_b,
            "winner": None if m.winner is None else ("a" if m.winner == m.entry_a else "b"),
            "mine": bool((a and a.includes_user) or (b and b.includes_user)),
            "id": m.id, "watchable": m.winner is not None and not any("forfeit" in x for x in (m.maps or [])),
            "played_on": m.played_on.isoformat() if m.played_on else None,
        })
    ordered = list(rounds.values())
    stages = translate.ru([r["stage"] for r in ordered])
    for r, stage in zip(ordered, stages):
        r["stage"] = stage
    user_entry = next((e for e in t.entries if e.includes_user), None)
    return {"name": t.name, "status": TOURNAMENT_STATUS.get(t.status, t.status), "size": t.size,
            "winner": next((e.name for e in t.entries if e.id == t.winner_entry_id), None),
            "user_placement": translate.ru1(user_entry.placement) if user_entry and user_entry.placement else None,
            "rounds": ordered}


# --- Forum and life inside the client -----------------------------------------------------------------------

CATEGORY_LABELS = {"mouse": "Mouse", "tablet": "Tablet", "software": "Drivers", "keyboard": "Keyboard",
                   "monitor": "Monitor", "chair": "Chair & desk"}
OCCUPATIONS = ("school", "university", "work", "pro")
DEVICES = ("mouse", "tablet")
TAP_STYLES = ("alternate", "singletap")


@router.get("/api/v2/tycoon/forum")
def tycoon_forum(limit: int = Query(default=30, ge=1, le=100), player: Player = Depends(current_player),
                 db: Session = Depends(get_db)):
    from app.routers import social

    threads = social.forum(player.id, None, limit, db)
    titles = translate.ru([t.title for t in threads])
    return [{"id": t.id, "date": t.date.isoformat(), "board": t.board, "title": title, "author": t.author,
             "flair": t.flair, "upvotes": t.upvotes, "comments": t.comment_count}
            for t, title in zip(threads, titles)]


@router.get("/api/v2/tycoon/forum/{thread_id}")
def tycoon_thread(thread_id: int, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    from app.routers import social

    try:
        t = social.thread(player.id, thread_id, db)
    except HTTPException as e:
        return _tycoon_error(e)
    texts = translate.ru([t.title, t.body] + [c.content for c in t.comments])
    title, body, contents = texts[0], texts[1], texts[2:]
    return {"id": t.id, "date": t.date.isoformat(), "board": t.board, "title": title, "author": t.author,
            "flair": t.flair, "upvotes": t.upvotes, "body": body,
            "comments": [{"id": c.id, "parent_id": c.parent_id, "author": c.author, "content": content,
                          "upvotes": c.upvotes} for c, content in zip(t.comments, contents)]}


@router.get("/api/v2/tycoon/life")
def tycoon_life(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    from app.routers import life as life_router
    from app.services import profile

    out = profile.to_player_out(player)
    life_out = out.life
    shop = life_router._shop(db, player)
    rival_rows = life_router.list_rivals(player.id, db)
    items = [i for i in shop.items if i.available or i.owned]
    labels = translate.ru(
        [CATEGORY_LABELS.get(c, c) for c in CATEGORY_LABELS] + list(OCCUPATIONS) + list(DEVICES) + list(TAP_STYLES)
        + [i.notes for i in items])
    it = iter(labels)
    categories = {c: next(it) for c in CATEGORY_LABELS}
    occupations = {o: next(it) for o in OCCUPATIONS}
    devices = {d: next(it) for d in DEVICES}
    taps = {s: next(it) for s in TAP_STYLES}
    notes = [next(it) for _ in items]
    data = {
        "age": life_out.age if life_out else None, "money": round(player.money, 2),
        "free_hours_today": life_out.free_hours_today if life_out else None,
        "followers": player.followers, "occupation": player.occupation, "input_device": player.input_device,
        "tap_style": player.tap_style, "adaptation": round(player.style_adaptation, 3),
        "occupations": [{"key": k, "label": v} for k, v in occupations.items()],
        "devices": [{"key": k, "label": v} for k, v in devices.items()],
        "tap_styles": [{"key": k, "label": v} for k, v in taps.items()],
        "effects": shop.effects,
        "shop": [{"key": i.key, "name": i.name, "category": i.category, "category_label": categories.get(i.category, i.category),
                  "price": round(i.price, 2), "is_new": i.is_new, "aim": i.aim, "tapping": i.tapping,
                  "ar_cap": i.ar_cap, "notes": note, "owned": i.owned, "equipped": i.equipped,
                  "available": i.available} for i, note in zip(items, notes)],
        "rivals": [{"name": r.name, "country": r.country, "rank": r.rank, "overall": r.overall, "heat": r.heat,
                    "since": r.since.isoformat(), "record": r.record, "user_id": osu_api.npc_user_id(r.npc_id)}
                   for r in rival_rows],
    }
    db.commit()
    return data


async def _life_call(request: Request, fn):
    try:
        raw = await request.body()
        return fn(json.loads(raw) if raw else {})
    except HTTPException as e:
        return _tycoon_error(e)
    except (ValueError, TypeError) as e:
        return JSONResponse({"error": translate.ru1(str(e))}, status_code=422)


@router.post("/api/v2/tycoon/life/occupation")
async def tycoon_occupation(request: Request, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    from app.routers import life as life_router
    from app.schemas import OccupationIn

    return await _life_call(request, lambda b: (life_router.set_occupation(player.id, OccupationIn(**b), db), {"ok": True})[1])


@router.post("/api/v2/tycoon/life/playstyle")
async def tycoon_playstyle(request: Request, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    from app.routers import life as life_router
    from app.schemas import PlaystyleIn

    return await _life_call(request, lambda b: (life_router.set_playstyle(player.id, PlaystyleIn(**b), db), {"ok": True})[1])


@router.post("/api/v2/tycoon/life/shop/{item_key}/{action}")
async def tycoon_shop(item_key: str, action: str, request: Request, player: Player = Depends(current_player),
                      db: Session = Depends(get_db)):
    from app.routers import life as life_router

    if action not in ("buy", "equip"):
        raise HTTPException(404, "unknown shop action")
    fn = life_router.buy if action == "buy" else life_router.equip
    return await _life_call(request, lambda _b: (fn(player.id, item_key, db), {"ok": True})[1])


# --- Beatmap listing: the tycoon's own index of ranked maps, as of the career's date ------------------------

SEARCH_PAGE = 50
COVER_URL = "https://assets.ppy.sh/beatmaps/{set_id}/covers/{kind}.jpg"
PREVIEW_URL = "https://b.ppy.sh/preview/{set_id}.mp3"


def _set_json(bset, beatmaps) -> dict:
    covers = {}
    for kind in ("cover", "card", "list", "slimcover"):
        covers[kind] = COVER_URL.format(set_id=bset.id, kind=kind)
        covers[f"{kind}@2x"] = COVER_URL.format(set_id=bset.id, kind=f"{kind}@2x")
    ranked = osu_api._when(bset.ranked_date)
    return {
        "id": bset.id, "title": bset.title, "title_unicode": bset.title, "artist": bset.artist,
        "artist_unicode": bset.artist, "creator": bset.creator, "user_id": 0, "source": bset.source,
        "tags": bset.tags, "status": bset.status,
        "covers": covers, "preview_url": PREVIEW_URL.format(set_id=bset.id),
        "play_count": bset.play_count, "favourite_count": bset.favourite_count, "bpm": bset.bpm,
        "ranked_date": ranked, "submitted_date": ranked, "last_updated": ranked,
        "nsfw": False, "video": False, "storyboard": False, "has_favourited": False, "hype": None,
        "availability": {"download_disabled": False, "more_information": None},
        "beatmaps": [{
            "id": b.id, "beatmapset_id": bset.id, "version": b.version, "mode_int": 0, "convert": False,
            "difficulty_rating": b.stars, "status": bset.status,
            "total_length": b.total_length, "hit_length": b.hit_length, "bpm": b.bpm, "cs": b.cs, "ar": b.ar,
            "accuracy": b.od, "drain": b.hp, "max_combo": b.max_combo, "count_circles": b.count_circles,
            "count_sliders": b.count_sliders, "count_spinners": 0, "playcount": b.play_count,
            "passcount": b.pass_count, "last_updated": ranked,
        } for b in sorted(beatmaps, key=lambda b: b.stars)],
    }


# Lazer's listing categories -> indexed statuses. Loved maps have leaderboards on osu!, so they count as such.
SEARCH_CATEGORIES = {"any": ("ranked", "approved", "loved"), "leaderboard": ("ranked", "approved", "loved"),
                     "ranked": ("ranked", "approved"), "loved": ("loved",)}

SEARCH_SORTS = {
    "title": BeatmapSet.title, "artist": BeatmapSet.artist, "plays": BeatmapSet.play_count,
    "favourites": BeatmapSet.favourite_count, "rating": BeatmapSet.favourite_count,
    "ranked": BeatmapSet.ranked_date, "updated": BeatmapSet.ranked_date, "relevance": BeatmapSet.play_count,
}


@router.get("/api/v2/beatmapsets/search")
def beatmapsets_search(request: Request, q: str = "", m: int | None = None, s: str = "leaderboard",
                       sort: str = "ranked_desc", player: Player = Depends(current_player),
                       db: Session = Depends(get_db)):
    """Lazer's beatmap listing over the career's world: only ranked maps that exist on the career's date."""
    empty = {"beatmapsets": [], "cursor": None, "total": 0}
    statuses = SEARCH_CATEGORIES.get(s.lower())
    if (m is not None and m != 0) or statuses is None:
        return empty  # the tycoon world only knows osu!standard ranked, approved and loved maps
    offset = int(request.query_params.get("cursor[offset]", 0) or 0)
    query = (select(BeatmapSet).where(BeatmapSet.ranked_date <= player.in_game_date,
                                      BeatmapSet.status.in_(statuses)))
    for term in q.lower().split():
        like = f"%{term}%"
        query = query.where(func.lower(BeatmapSet.artist).like(like) | func.lower(BeatmapSet.title).like(like)
                            | func.lower(BeatmapSet.creator).like(like) | func.lower(BeatmapSet.tags).like(like)
                            | func.lower(BeatmapSet.source).like(like))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    field, _, direction = sort.partition("_")
    if field == "difficulty":
        stars = select(func.max(Beatmap.stars)).where(Beatmap.beatmapset_id == BeatmapSet.id).scalar_subquery()
        order = stars
    else:
        order = SEARCH_SORTS.get(field, BeatmapSet.ranked_date)
    order = order.asc() if direction == "asc" else order.desc()
    sets = list(db.scalars(query.order_by(order, BeatmapSet.id.desc()).offset(offset).limit(SEARCH_PAGE)))
    by_set: dict[int, list] = {}
    if sets:
        for b in db.scalars(select(Beatmap).where(Beatmap.beatmapset_id.in_([x.id for x in sets]))):
            by_set.setdefault(b.beatmapset_id, []).append(b)
    more = offset + len(sets) < total
    return {"beatmapsets": [_set_json(x, by_set.get(x.id, [])) for x in sets],
            "cursor": {"offset": offset + len(sets)} if more else None, "total": total}


def _set_or_404(db: Session, player: Player, set_id: int | None):
    bset = db.get(BeatmapSet, set_id) if set_id else None
    if bset is None or bset.ranked_date > player.in_game_date:
        return None
    return bset


@router.get("/api/v2/beatmapsets/lookup")
def beatmapset_lookup(beatmap_id: int, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    beatmap = db.get(Beatmap, beatmap_id)
    bset = _set_or_404(db, player, beatmap.beatmapset_id if beatmap else None)
    if bset is None:
        raise HTTPException(404, "this map doesn't exist yet in the career's world")
    return _set_json(bset, list(bset.beatmaps))


@router.get("/api/v2/beatmapsets/{beatmapset_id}")
def beatmapset(beatmapset_id: int, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    bset = _set_or_404(db, player, beatmapset_id)
    if bset is None:
        raise HTTPException(404, "this map doesn't exist yet in the career's world")
    return _set_json(bset, list(bset.beatmaps))


@router.get("/api/v2/tycoon/date")
def tycoon_date(player: Player = Depends(current_player)):
    return {"date": player.in_game_date.isoformat(), "name": player.name}


# --- Beatmap identification and profile extras ---------------------------------------------------------------
# `early` is included before `router`: its paths would otherwise be swallowed by /users/{lookup}/{ruleset}.
early = APIRouter(tags=["osu-api"])


@early.get("/api/avatars/{name}.png")
def avatar(name: str, legend: int = 0):
    """A player's avatar: their own picture from data/avatars/ if there is one, otherwise a generated identicon.
    No login needed: lazer loads textures without the API token."""
    from fastapi.responses import Response
    from app.services import avatars

    data, media_type = avatars.avatar(name, bool(legend))
    return Response(data, media_type=media_type, headers={"Cache-Control": "max-age=86400"})


@early.get("/api/v2/beatmaps/lookup")
def beatmap_lookup(checksum: str | None = None, id: int | None = None, filename: str | None = None,
                   player: Player = Depends(current_player), db: Session = Depends(get_db)):
    """How lazer learns a map's online id and status from its md5; without it the map loses its leaderboard."""
    from app.services import beatmap_lookup as lookup_service

    found = lookup_service.lookup(db, checksum=checksum, beatmap_id=id)
    if found is None:
        raise HTTPException(404, "unknown beatmap")
    return found


@early.get("/api/v2/users/{user_id}/recent_activity")
@early.get("/api/v2/users/{user_id}/kudosu")
@early.get("/api/v2/users/{user_id}/beatmapsets/{kind}")
def user_empty_lists(user_id: int, player: Player = Depends(current_player)):
    return []  # profile sections the tycoon world has nothing for yet


# --- Watching played matches (multiplayer spectator) --------------------------------------------------------

@router.get("/api/v2/tycoon/watch")
def tycoon_watch_list(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    from app.services import match_watch

    items = match_watch.listing(db, player)
    stages = translate.ru([i["stage"] for i in items])
    return [i | {"stage": stage} for i, stage in zip(items, stages)]


@router.get("/api/v2/tycoon/watch/{kind}/{source_id}/{index}")
def tycoon_watch_map(kind: str, source_id: int, index: int, player: Player = Depends(current_player),
                     db: Session = Depends(get_db)):
    from app.services import match_watch

    try:
        view = match_watch.map_view(db, player, kind, source_id, index)
    except match_watch.WatchError as e:
        return JSONResponse({"error": translate.ru1(str(e))}, status_code=e.status_code)
    beatmap = db.get(Beatmap, view["beatmap_id"]) if view.get("beatmap_id") else None
    view["beatmapset_id"] = beatmap.beatmapset_id if beatmap else None
    [view["stage"]] = translate.ru([view["stage"]])
    return view
