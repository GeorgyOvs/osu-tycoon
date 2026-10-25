"""Goals and story arcs (story layer): keep three goals alive, measure progress, detect the arc the career is in."""

import random
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import gear, pp_history, simulation
from app.engine import goals as G
from app.models import Goal, Match, Npc, Player, StoryArc, Tournament, TournamentEntry
from app.services import condition, events, media, rivals, story, streaming

MAX_ACTIVE = 3
ARC_SAMPLE_DAYS = 7
HISTORY_KEEP = 60


# --- context -----------------------------------------------------------------------------------


def _rival(db: Session, player: Player) -> tuple[str | None, int | None, float, bool]:
    rival = next(iter(sorted(rivals.active(db, player), key=lambda r: -r.heat)), None)
    npc = db.get(Npc, rival.npc_id) if rival else None
    return (npc.name if npc else None, npc.rank if npc else None, rival.heat if rival else 0.0, rival is not None)


def _upgrade(db: Session, player: Player) -> tuple[str, str, float] | None:
    owned = {i.item_key for i in condition.inventory(db, player)}
    on = player.in_game_date
    best, best_score = None, 0.0
    for item in gear.CATALOG.values():
        if item.key in owned or not item.available(on) or item.category not in ("mouse", "tablet", "keyboard", "monitor", "chair"):
            continue
        if item.requires and item.requires != player.input_device:
            continue
        price = item.price_on(on)
        if not (player.money * 0.5 < price <= player.money * 5 + 80):
            continue
        score = (item.aim - 1) + (item.tapping - 1) + 0.2 * (item.ergonomics or 0)
        if score > best_score:
            best, best_score = item, score
    return (best.key, best.name, best.price_on(on)) if best else None


def _match_wins(db: Session, player: Player, since: date) -> int:
    entry_ids = list(db.scalars(
        select(TournamentEntry.id).join(Tournament, Tournament.id == TournamentEntry.tournament_id)
        .where(Tournament.player_id == player.id, TournamentEntry.includes_user.is_(True))))
    if not entry_ids:
        return 0
    return db.scalar(select(func.count()).select_from(Match)
                     .where(Match.winner.in_(entry_ids), Match.played_on >= since)) or 0


def _in_tournaments(db: Session, player: Player) -> bool:
    return bool(db.scalar(select(func.count()).select_from(Tournament)
                          .where(Tournament.player_id == player.id, Tournament.user_registered.is_(True),
                                 Tournament.status != "finished")))


def _goal_ctx(db: Session, player: Player, active: list[Goal], done: list[Goal]) -> G.GoalCtx:
    comps = A.composites(simulation.effective_values(player))
    name, rank, _, _ = _rival(db, player)
    on = player.in_game_date
    recent = {g.key for g in done if g.finished_on and g.key not in ("rank", "pp")
              and (on - g.finished_on).days < (21 if g.status == "done" else 75)}
    return G.GoalCtx(
        on=on, rank=player.global_rank, total_pp=player.total_pp, pp_era=pp_history.era_for(on).ranking == "pp",
        composites=comps, followers=player.followers, money=player.money, play_count=player.play_count,
        streaming=streaming.available(on), consecutive_days=player.consecutive_training_days,
        rival_name=name, rival_rank=rank, item=_upgrade(db, player), user_in_tournaments=_in_tournaments(db, player),
        active_keys={g.key for g in active}, recently_done=recent,
    )


def _measure(db: Session, player: Player, goal: Goal) -> float:
    target = goal.target
    comps = A.composites(simulation.effective_values(player))
    _, rival_rank, _, _ = _rival(db, player)
    owns = target.get("item") in {i.item_key for i in condition.inventory(db, player)} if target.get("metric") == "gear" else False
    best = max(goal.data.get("best_streak", 0), player.consecutive_training_days)
    goal.data = {**goal.data, "best_streak": best}
    return G.progress(
        target, rank=player.global_rank, total_pp=player.total_pp, composites=comps, followers=player.followers,
        money=player.money, play_count=player.play_count, consecutive_days=player.consecutive_training_days,
        best_streak=best, match_wins=_match_wins(db, player, goal.created_on) if target.get("metric") == "match_wins" else 0,
        owns_item=owns, rival_rank=rival_rank if target.get("metric") == "overtake" else None,
    )


# --- tick ---------------------------------------------------------------------------------------


def tick(db: Session, player: Player, news: list) -> None:
    today = player.in_game_date
    if story.get(player, "goals_checked_on") == today.isoformat():
        return
    story.put(player, "goals_checked_on", today.isoformat())
    goals = list(db.scalars(select(Goal).where(Goal.player_id == player.id).order_by(Goal.id)))
    active = [g for g in goals if g.status == "active"]
    for goal in active:
        goal.progress = round(_measure(db, player, goal), 3)
        if goal.progress >= 1.0:
            _complete(db, player, goal, today)
        elif goal.deadline and goal.deadline < today:
            goal.status, goal.finished_on = "failed", today
            player.motivation = max(0.0, player.motivation - 2)
    active = [g for g in active if g.status == "active"]
    done = [g for g in goals if g.status != "active"]

    n = len(goals)
    while len(active) < MAX_ACTIVE:
        rng = random.Random(f"{player.seed}:goals:{today.isoformat()}:{n}")
        spec = G.propose(_goal_ctx(db, player, active, done), rng)
        if spec is None:
            break
        goal = Goal(player_id=player.id, key=spec.key, title=spec.key, created_on=today,
                    deadline=today + timedelta(days=spec.deadline_days), status="active", progress=0.0,
                    target=spec.target, reward=spec.reward, data=spec.data)
        db.add(goal)
        active.append(goal)
        n += 1
    db.flush()
    _arcs(db, player, today)


def _complete(db: Session, player: Player, goal: Goal, today: date) -> None:
    goal.status, goal.finished_on, goal.progress = "done", today, 1.0
    applied = events.apply_effects(db, player, goal.reward, goal.data, goal.id)
    goal.data = {**goal.data, "applied": applied}
    en_title, _ = _text(goal, "en")
    media.private_event(db, player, "GOAL_COMPLETED", {"goal": en_title, "reward": {k: v for k, v in applied.items() if k != "mod"}},
                        channel="#osu")


# --- presentation ------------------------------------------------------------------------------


def _text(goal: Goal, lang: str) -> tuple[str, str]:
    i = 1 if lang == "ru" else 0
    title, desc = G.TEXT[goal.key]
    vars_ = {"target": goal.target.get("value", ""), "rival": goal.data.get("rival", ""),
             "item": goal.data.get("item", ""), "n": goal.data.get("n", ""),
             "group": (G.GROUP_RU if i else G.GROUP_EN).get(goal.data.get("group") or goal.target.get("group", ""), "")}
    if goal.key == "rank" or goal.key == "overtake_rival":
        vars_["target"] = f"{goal.target.get('value'):,}".replace(",", " " if i else ",")
    if goal.key in ("pp", "followers"):
        vars_["target"] = f"{goal.target.get('value'):,}".replace(",", " " if i else ",")
    return title[i].format(**vars_), desc[i].format(**vars_)


def present_goal(goal: Goal, lang: str, today: date) -> dict:
    title, desc = _text(goal, lang)
    reward = {k: v for k, v in goal.reward.items() if k != "mod"}
    return {
        "id": goal.id, "key": goal.key, "title": title, "description": desc, "status": goal.status,
        "progress": goal.progress, "created_on": goal.created_on.isoformat(),
        "deadline": goal.deadline.isoformat() if goal.deadline else None,
        "days_left": (goal.deadline - today).days if goal.deadline and goal.status == "active" else None,
        "finished_on": goal.finished_on.isoformat() if goal.finished_on else None,
        "reward": reward, "inspired": "mod" in goal.reward,
    }


def present_arc(arc: StoryArc, lang: str) -> dict:
    i = 1 if lang == "ru" else 0
    title = G.ARC_TEXT[arc.key][i].format(**arc.data)
    return {
        "id": arc.id, "key": arc.key, "title": title, "status": arc.status, "started_on": arc.started_on.isoformat(),
        "ended_on": arc.ended_on.isoformat() if arc.ended_on else None,
        "chapters": [{"date": c["date"], "text": G.CHAPTER_TEXT[c["key"]][i].format_map(_Safe({**arc.data, **c.get("data", {})}))}
                     for c in arc.chapters],
    }


def overview(db: Session, player: Player, lang: str) -> dict:
    today = player.in_game_date
    goals = list(db.scalars(select(Goal).where(Goal.player_id == player.id).order_by(Goal.id.desc())))
    arcs = list(db.scalars(select(StoryArc).where(StoryArc.player_id == player.id).order_by(StoryArc.id.desc())))
    return {
        "active": [present_goal(g, lang, today) for g in reversed([g for g in goals if g.status == "active"])],
        "finished": [present_goal(g, lang, today) for g in goals if g.status != "active"][:20],
        "arcs": [present_arc(a, lang) for a in arcs][:12],
    }


# --- arcs ---------------------------------------------------------------------------------------


class _Safe(dict):
    def __missing__(self, key):
        return "?"


def _chapter(arc: StoryArc, key: str, on: date, **data) -> None:
    arc.chapters = [*arc.chapters, {"date": on.isoformat(), "key": key, "data": data}]


def _open(db: Session, player: Player, key: str, on: date, first: str, **data) -> StoryArc:
    arc = StoryArc(player_id=player.id, key=key, title=key, started_on=on, status="active", chapters=[], data=data)
    _chapter(arc, first, on, **({"rank": player.global_rank} if player.global_rank else {}))
    db.add(arc)
    db.flush()
    return arc


def _close(db: Session, player: Player, arc: StoryArc, key: str, on: date, thread: bool = False) -> None:
    _chapter(arc, key, on, rank=player.global_rank or 0)
    arc.status, arc.ended_on = "resolved", on
    if thread:
        title_en = G.ARC_TEXT[arc.key][0].format(**arc.data)
        media.emit(db, player, "STORY_ARC", {"arc": arc.key, "title": title_en,
                                             "chapters": [c["key"] for c in arc.chapters]},
                   kind="milestone", title=f"{player.name} [{player.country}]: {title_en}",
                   body=G.CHAPTER_TEXT[key][0].format_map(_Safe({**arc.data, "rank": player.global_rank or "?"})),
                   flair="Story", base_upvotes=150, tone="warm, proud",
                   fmt={"player": player.name, "rank_label": title_en, "next_label": "the next chapter"})


def _arcs(db: Session, player: Player, today: date) -> None:
    hist = list(story.get(player, "rank_hist", []))
    if not hist or (today - date.fromisoformat(hist[-1][0])).days >= ARC_SAMPLE_DAYS:
        hist.append([today.isoformat(), player.global_rank or 0])
        story.put(player, "rank_hist", hist[-HISTORY_KEEP:])
    arcs = {a.key: a for a in db.scalars(select(StoryArc).where(StoryArc.player_id == player.id,
                                                                StoryArc.status == "active"))}
    rank = player.global_rank

    # Comeback: opens with a severe injury, ends when the old rank is regained.
    arc = arcs.get("comeback")
    if arc is None and player.injury == simulation.SEVERE_RSI:
        _open(db, player, "comeback", today, "comeback_start", rank_before=rank or 0)
    elif arc is not None:
        if player.injury != simulation.SEVERE_RSI and not arc.data.get("returned"):
            arc.data = {**arc.data, "returned": True}
            _chapter(arc, "comeback_return", today)
        before = arc.data.get("rank_before") or 0
        if arc.data.get("returned") and rank and (not before or rank <= before):
            _close(db, player, arc, "comeback_end", today, thread=True)
        elif (today - arc.started_on).days > 150 and player.injury != simulation.SEVERE_RSI:
            _close(db, player, arc, "comeback_fade", today)

    samples = [(date.fromisoformat(d), r) for d, r in hist if r]
    old = next((r for d, r in samples if (today - d).days >= 80), None)

    # Breakout: the rank halves within ~3 months.
    arc = arcs.get("breakout")
    if arc is None and rank and old and rank <= old * 0.5 and old > 200:
        _open(db, player, "breakout", today, "breakout_start", best=rank)
    elif arc is not None and rank:
        best = arc.data.get("best", rank)
        if rank <= best * 0.7:
            arc.data = {**arc.data, "best": rank, "stale": 0}
            _chapter(arc, "breakout_step", today, rank=rank)
        elif rank > best * 0.95:
            stale = arc.data.get("stale", 0) + 1
            arc.data = {**arc.data, "stale": stale}
            if stale >= 5:
                _close(db, player, arc, "breakout_end", today, thread=best <= 5000)

    # The wall: months of training with the rank stuck.
    arc = arcs.get("wall")
    recent = [r for d, r in samples if (today - d).days <= 90]
    stuck = len(recent) >= 10 and max(recent) <= min(recent) * 1.08 and player.play_count >= 20
    if arc is None and stuck and rank and "breakout" not in arcs and "comeback" not in arcs:
        _open(db, player, "wall", today, "wall_start", base=rank)
    elif arc is not None and rank:
        if rank <= arc.data.get("base", rank) * 0.85:
            player.motivation = min(100.0, player.motivation + 10)
            _close(db, player, arc, "wall_break", today, thread=rank <= 10000)
        elif (today - arc.started_on).days > 240:
            _close(db, player, arc, "wall_fade", today)

    # Rivalry: a hot rival becomes a storyline.
    name, _, heat, has = _rival(db, player)
    arc = arcs.get("rivalry")
    if arc is None and name and heat >= 55:
        _open(db, player, "rivalry", today, "rivalry_start", rival=name)
    elif arc is not None and (not has or heat < 20):
        _close(db, player, arc, "rivalry_end", today)
    db.flush()
