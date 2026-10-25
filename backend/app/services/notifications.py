"""What deserves the player's attention right now, as a feed of items with stable ids.

The client shows each id once as a toast and keeps a read-state for the bell. Sources: user-centric world
news, notable outbox moments (milestones, goals, integrity cases), new top plays, the next tournament match,
life events waiting for a decision, and tournaments whose registration is open for you.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LifeEvent, Player, Score, StEvent, Tournament, WorldEvent
from app.services import events, ranking, tournaments

LOOKBACK_DAYS = 21
CLOSING_DAYS = 3
MAX_ITEMS = 40

# world news type -> (kind, tab to open, priority)
USER_NEWS = {
    "SNIPED": ("snipe", "world", 3),
    "OWC_SELECTED": ("tournament", "tournaments", 3),
    "TOURNAMENT_WIN": ("tournament", "tournaments", 3),
    "TOURNAMENT_RESULT": ("tournament", "tournaments", 2),
    "QUALIFIERS": ("tournament", "tournaments", 2),
    "POOL_RELEASED": ("tournament", "tournaments", 1),
    "PRIZE": ("tournament", "tournaments", 1),
    "FORFEIT": ("tournament", "tournaments", 2),
    "PP_DECAY": ("rank", "profile", 1),
    "TEAM_INVITE": ("team", "team", 2),
    "TEAM_MEMBER_JOINED": ("team", "team", 1),
    "TEAM_MEMBER_LEFT": ("team", "team", 1),
    "TEAM_CUP_RESULT": ("team", "team", 2),
    "ACHIEVEMENT": ("achievement", "legacy", 2),
    "RESTRICTION_LIFTED": ("integrity", "life", 2),
    "CAREER_END": ("legacy", "legacy", 3),
}

TEXT = {
    "milestone": ("You reached {label} (#{rank:,}).", "Вы достигли {label} (#{rank:,})."),
    "goal": ("Goal completed: {goal}.", "Цель выполнена: {goal}."),
    "integrity": ("Someone questions one of your plays: answer in the Life tab.",
                  "Кто-то сомневается в вашем плее: ответьте во вкладке «Жизнь»."),
    "top": ("New top play #{pos}: {map} ({pp:.0f}pp).", "Новый топ-плей #{pos}: {map} ({pp:.0f}pp)."),
    "match_today": ("Tournament match today: {stage} at {name}.", "Сегодня турнирный матч: {stage}, {name}."),
    "match_soon": ("Tournament match on {due}: {stage} at {name}.", "Турнирный матч {due}: {stage}, {name}."),
    "decision": ("Decision needed: {title}", "Нужно решение: {title}"),
    "reg_open": ("Registration is open: {name} (until {until}).", "Открыта регистрация: {name} (до {until})."),
    "reg_closing": ("Last days to register for {name} (closes {until}).",
                    "Последние дни регистрации на {name} (закрывается {until})."),
}


def _text(key: str, lang: str, **kw) -> str:
    return TEXT[key][1 if lang == "ru" else 0].format(**kw)


def _item(id_: str, kind: str, on: date, message: str, tab: str, priority: int = 1, action: dict | None = None) -> dict:
    return {"id": id_, "kind": kind, "date": on.isoformat(), "message": message, "tab": tab,
            "priority": priority, "action": action}


def registrations(db: Session, player: Player, lang: str = "en") -> list[dict]:
    """Tournaments you could sign up for today, plus a reminder a few days before registration closes."""
    today = player.in_game_date
    out = []
    rows = db.scalars(select(Tournament).where(
        Tournament.player_id == player.id, Tournament.status == "upcoming", Tournament.user_registered.is_(False),
        Tournament.registration_opens <= today, Tournament.start_date > today))
    for t in rows:
        if t.tier == "owc":
            continue
        if t.tier == "clan":
            from app.services import teams

            if teams.cup_squad(db, player) is None:
                continue
        elif not tournaments.eligible(player, t):
            continue
        until = (t.start_date - timedelta(days=1)).isoformat()
        action = {"type": "register", "tournament_id": t.id, "name": t.name}
        out.append(_item(f"reg:{t.id}:open", "registration", t.registration_opens, _text("reg_open", lang, name=t.name, until=until),
                         "tournaments", 2, action))
        if (t.start_date - today).days <= CLOSING_DAYS:
            out.append(_item(f"reg:{t.id}:closing", "registration", today,
                             _text("reg_closing", lang, name=t.name, until=until), "tournaments", 2, action))
    return out


def feed(db: Session, player: Player, lang: str = "en") -> list[dict]:
    today = player.in_game_date
    since = today - timedelta(days=LOOKBACK_DAYS)
    items: list[dict] = []

    for e in db.scalars(select(WorldEvent).where(
            WorldEvent.player_id == player.id, WorldEvent.type.in_(tuple(USER_NEWS)), WorldEvent.date >= since,
            WorldEvent.date <= today).order_by(WorldEvent.id.desc()).limit(MAX_ITEMS)):
        kind, tab, priority = USER_NEWS[e.type]
        items.append(_item(f"we:{e.id}", kind, e.date, e.message, tab, priority))

    for st in db.scalars(select(StEvent).where(
            StEvent.player_id == player.id, StEvent.type.in_(("RANK_MILESTONE", "GOAL_COMPLETED", "INTEGRITY_CASE")),
            StEvent.date >= since).order_by(StEvent.id.desc()).limit(20)):
        data = (st.payload or {}).get("data", {})
        if st.type == "RANK_MILESTONE" and data.get("rank"):
            items.append(_item(f"st:{st.id}", "milestone", st.date,
                               _text("milestone", lang, label=data.get("milestone", ""), rank=int(data["rank"])), "profile", 3))
        elif st.type == "GOAL_COMPLETED":
            items.append(_item(f"st:{st.id}", "goal", st.date, _text("goal", lang, goal=data.get("goal", "")), "story", 2))
        elif st.type == "INTEGRITY_CASE":
            items.append(_item(f"st:{st.id}", "integrity", st.date, _text("integrity", lang), "life", 3))

    scores = list(db.scalars(select(Score).where(Score.player_id == player.id)))
    for pos, s in enumerate(ranking.top_plays(scores)[:5], start=1):
        if s.played_on >= since:
            items.append(_item(f"top:{s.id}", "top_play", s.played_on,
                               _text("top", lang, pos=pos, map=f"{s.artist} - {s.title} [{s.difficulty_name}]", pp=s.pp),
                               "profile", 3 if pos == 1 else 2))

    pending = tournaments.pending_user_match(db, player)
    if pending:
        t, m = pending
        due = tournaments.due_date(t, m.week)
        if (due - today).days <= 1:
            key = "match_today" if due <= today else "match_soon"
            items.append(_item(f"match:{m.id}:{key}", "match", today,
                               _text(key, lang, stage=m.stage, name=t.name, due=due.isoformat()), "tournaments", 3))

    for ev in db.scalars(select(LifeEvent).where(LifeEvent.player_id == player.id, LifeEvent.status == "pending")):
        title = events.present(ev, lang)["title"]
        items.append(_item(f"event:{ev.id}", "decision", ev.created_on, _text("decision", lang, title=title), "story", 2))

    items += registrations(db, player, lang)
    items.sort(key=lambda i: (i["date"], i["priority"]), reverse=True)
    return items[:MAX_ITEMS]
