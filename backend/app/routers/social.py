"""Forum and IRC for the UI, plus the SillyTavern bridge.

SillyTavern has no inbound webhook, so the bridge is pull-based: the extension polls
/api/st/.../events, runs the bundled prompts through the LLM, and posts the results back.
"""

import random

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.engine import attributes as A
from app.engine import simulation
from app.models import ChatMessage, ForumComment, ForumThread, Player, StEvent, Tournament
from app.routers.players import get_player_or_404
from app.schemas import (
    ChatOut,
    DmIn,
    CommentOut,
    LlmCommentsIn,
    LlmLinesIn,
    StCareerOut,
    StContextOut,
    StEventOut,
    ThreadOut,
    ThreadSummaryOut,
)
from app.services import life, media, profile, rivals, st_prompts, world_service

router = APIRouter(prefix="/api/players/{player_id}", tags=["social"])
bridge = APIRouter(prefix="/api/st", tags=["sillytavern"])


def _summary(t: ForumThread, comment_count: int) -> ThreadSummaryOut:
    return ThreadSummaryOut(id=t.id, date=t.date, board=t.board, kind=t.kind, title=t.title, author=t.author,
                            flair=t.flair, upvotes=t.upvotes, comment_count=comment_count, llm_status=t.llm_status)


def _thread(db: Session, player: Player, thread_id: int) -> ForumThread:
    t = db.get(ForumThread, thread_id)
    if t is None or t.player_id != player.id:
        raise HTTPException(404, "thread not found")
    return t


def _thread_out(t: ForumThread) -> ThreadOut:
    return ThreadOut(
        **_summary(t, len(t.comments)).model_dump(),
        body=t.body,
        comments=[CommentOut(id=c.id, parent_id=c.parent_id, author=c.author, content=c.content,
                             upvotes=c.upvotes, source=c.source) for c in t.comments],
    )


@router.get("/forum", response_model=list[ThreadSummaryOut])
def forum(player_id: int, kind: str | None = None, limit: int = Query(default=30, le=100),
          db: Session = Depends(get_db)) -> list[ThreadSummaryOut]:
    player = get_player_or_404(db, player_id)
    counts = (select(ForumComment.thread_id, func.count().label("n")).group_by(ForumComment.thread_id).subquery())
    q = (select(ForumThread, func.coalesce(counts.c.n, 0))
         .outerjoin(counts, counts.c.thread_id == ForumThread.id)
         .where(ForumThread.player_id == player.id))
    if kind:
        q = q.where(ForumThread.kind == kind)
    rows = db.execute(q.order_by(ForumThread.date.desc(), ForumThread.id.desc()).limit(limit))
    return [_summary(t, n) for t, n in rows]


@router.get("/forum/{thread_id}", response_model=ThreadOut)
def thread(player_id: int, thread_id: int, db: Session = Depends(get_db)) -> ThreadOut:
    player = get_player_or_404(db, player_id)
    return _thread_out(_thread(db, player, thread_id))


@router.get("/irc", response_model=list[ChatOut])
def irc(player_id: int, channel: str | None = None, after_id: int = 0, limit: int = Query(default=100, le=300),
        db: Session = Depends(get_db)) -> list[ChatOut]:
    player = get_player_or_404(db, player_id)
    q = select(ChatMessage).where(ChatMessage.player_id == player.id, ChatMessage.id > after_id)
    if channel:
        q = q.where(ChatMessage.channel == channel)
    rows = list(db.scalars(q.order_by(ChatMessage.id.desc()).limit(limit)))
    return [ChatOut(id=m.id, date=m.date, channel=m.channel, author=m.author, content=m.content, source=m.source)
            for m in reversed(rows)]


@router.post("/dm", response_model=list[ChatOut])
def send_dm(player_id: int, body: DmIn, db: Session = Depends(get_db)) -> list[ChatOut]:
    """Write to an NPC; with the SillyTavern bridge running they answer in character."""
    player = get_player_or_404(db, player_id)
    world_service.ensure_world(db, player)
    if rivals.send_dm(db, player, body.to, body.text) is None:
        raise HTTPException(404, f"no player called {body.to} in this world")
    db.commit()
    rows = db.scalars(select(ChatMessage).where(ChatMessage.player_id == player.id,
                                                ChatMessage.channel == f"DM:{body.to}").order_by(ChatMessage.id))
    return [ChatOut(id=m.id, date=m.date, channel=m.channel, author=m.author, content=m.content, source=m.source)
            for m in rows]


@router.get("/irc/channels", response_model=list[str])
def irc_channels(player_id: int, db: Session = Depends(get_db)) -> list[str]:
    player = get_player_or_404(db, player_id)
    channels = set(db.scalars(select(ChatMessage.channel).where(ChatMessage.player_id == player.id).distinct()))
    return sorted(channels | {"#osu", media.channel_for(player.country)})


# --- SillyTavern bridge ------------------------------------------------------------------------


@bridge.get("/careers", response_model=list[StCareerOut])
def careers(db: Session = Depends(get_db)) -> list[StCareerOut]:
    return [StCareerOut(id=p.id, name=p.name, country=p.country, in_game_date=p.in_game_date)
            for p in db.scalars(select(Player).order_by(Player.id))]


def _event_out(db: Session, player: Player, e: StEvent) -> StEventOut:
    t = db.get(ForumThread, e.thread_id) if e.thread_id else None
    names = media.usernames(db, player, random.Random(f"{player.seed}:st:{e.id}"))
    thread_info = {"id": t.id, "board": t.board, "title": t.title, "body": t.body} if t else None
    if e.type == "DM_REPLY":  # a private conversation: only the NPC's reply is wanted
        prompts = {"dm": st_prompts.dm_prompt(e.payload, e.date)}
    else:
        prompts = {
            "irc": st_prompts.irc_prompt(e.payload, e.channel, e.date, names),
            "narration": st_prompts.narration_prompt(e.payload, e.date),
        }
    if thread_info:
        prompts["forum"] = st_prompts.forum_prompt(e.payload, thread_info, e.date, names)
    return StEventOut(id=e.id, date=e.date, type=e.type, handled=e.handled, channel=e.channel, payload=e.payload,
                      thread=thread_info, prompts=prompts,
                      schemas={"forum": st_prompts.FORUM_SCHEMA, "irc": st_prompts.IRC_SCHEMA,
                               "dm": st_prompts.IRC_SCHEMA})


@bridge.get("/careers/{player_id}/events", response_model=list[StEventOut])
def events(player_id: int, after: int = 0, include_handled: bool = False, limit: int = Query(default=10, le=50),
           db: Session = Depends(get_db)) -> list[StEventOut]:
    player = get_player_or_404(db, player_id)
    q = select(StEvent).where(StEvent.player_id == player.id, StEvent.id > after)
    if not include_handled:
        q = q.where(StEvent.handled.is_(False))
    return [_event_out(db, player, e) for e in db.scalars(q.order_by(StEvent.id).limit(limit))]


@bridge.post("/careers/{player_id}/events/{event_id}/ack", status_code=204)
def ack(player_id: int, event_id: int, db: Session = Depends(get_db)) -> None:
    player = get_player_or_404(db, player_id)
    e = db.get(StEvent, event_id)
    if e is None or e.player_id != player.id:
        raise HTTPException(404, "event not found")
    e.handled = True
    db.commit()


@bridge.post("/careers/{player_id}/threads/{thread_id}/comments", response_model=ThreadOut)
def add_comments(player_id: int, thread_id: int, body: LlmCommentsIn, db: Session = Depends(get_db)) -> ThreadOut:
    player = get_player_or_404(db, player_id)
    t = _thread(db, player, thread_id)
    created: list[ForumComment] = []
    for c in body.comments:
        parent = created[c.reply_to].id if c.reply_to is not None and 0 <= c.reply_to < len(created) else None
        comment = ForumComment(author=c.author, content=c.content, parent_id=parent, source="llm",
                               upvotes=c.upvotes if c.upvotes is not None else max(1, t.upvotes // 10))
        t.comments.append(comment)
        db.flush()
        created.append(comment)
    t.llm_status = "done"
    db.commit()
    return _thread_out(t)


@bridge.post("/careers/{player_id}/irc", response_model=list[ChatOut])
def add_irc(player_id: int, body: LlmLinesIn, db: Session = Depends(get_db)) -> list[ChatOut]:
    player = get_player_or_404(db, player_id)
    rows = [ChatMessage(player_id=player.id, date=player.in_game_date, channel=body.channel, author=line.author,
                        content=line.content, source="llm") for line in body.lines]
    db.add_all(rows)
    db.commit()
    return [ChatOut(id=m.id, date=m.date, channel=m.channel, author=m.author, content=m.content, source=m.source)
            for m in rows]


@bridge.get("/careers/{player_id}/context", response_model=StContextOut)
def context(player_id: int, db: Session = Depends(get_db)) -> StContextOut:
    """A compact state summary for SillyTavern's World Info / Author's Note."""
    player = get_player_or_404(db, player_id)
    world_service.ensure_world(db, player)
    db.commit()
    values = simulation.effective_values(player)
    comps = A.composites(values)
    prof = profile.to_profile(db, player)
    lines = [
        f"[osu! Tycoon] {player.name} [{player.country}] ({life.pronouns(player)}), in-game date "
        f"{player.in_game_date} ({prof.era_label}).",
        f"Global rank: {f'#{player.global_rank:,}' if player.global_rank else 'unranked'}, "
        f"{player.total_pp:,.0f}pp, accuracy {player.accuracy:.2f}%, play count {player.play_count}.",
        "Skills (1-99): " + ", ".join(f"{g.label} {comps[g.key]:.0f}" for g in A.GROUPS)
        + f"; overall {A.overall(values):.0f}.",
        f"Condition: fatigue {player.fatigue:.0f}/100, motivation {player.motivation:.0f}/100, "
        f"morale {player.morale:.0f}/100, health: {player.injury.replace('_', ' ')}.",
    ]
    if prof.traits:
        lines.append("Known traits: " + ", ".join(prof.traits) + ".")
    if prof.top_plays:
        lines.append("Top plays: " + "; ".join(
            f"{s.artist} - {s.title} [{s.difficulty_name}] +{s.mods or 'NM'} {s.accuracy:.2f}% {s.pp:.0f}pp"
            for s in prof.top_plays[:3]) + ".")
    registered = db.scalars(select(Tournament).where(
        Tournament.player_id == player.id, Tournament.user_registered.is_(True), Tournament.status != "finished"))
    tours = [f"{t.name} ({t.status}, starts {t.start_date})" for t in registered]
    if tours:
        lines.append("Tournaments: " + "; ".join(tours) + ".")
    top = world_service.leaderboard(db, player, limit=5)
    lines.append("Current global top 5: " + ", ".join(f"{r.name} [{r.country}]" for r in top if r.kind != "user") + ".")
    news = world_service.recent_news(db, player, limit=5, min_importance=2)
    if news:
        lines.append("Recent news: " + " | ".join(f"{n.date}: {n.message}" for n in news))
    return StContextOut(text="\n".join(lines))
