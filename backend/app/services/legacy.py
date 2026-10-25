"""Legacy: career records, achievements, retirement with an epilogue, the hall of fame, and hardcore endings.

State lives in Player.story_state: `records` (personal bests and counters), `achievements` (key -> unlock
date), `retired` ({on, reason, epilogue}), plus the economy ledger (see economy.py).
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine import achievements as AC
from app.engine import attributes as A
from app.engine import simulation
from app.models import Goal, LifeEvent, Match, Npc, Player, Rival, StoryArc, Team, Tournament, TournamentEntry
from app.services import economy, media, story

BANKRUPT_DAYS = 90  # hardcore: this long in the red ends the career
FATAL_CAP_LOSS = 15.0  # hardcore: stamina ceiling lost for good that ends the career
REASONS = {
    "manual": ("You decided it was time to stop.", "Вы решили, что пора остановиться."),
    "bankrupt": ("Months in the red ended the career.", "Месяцы в долгах положили конец карьере."),
    "injury": ("A career-ending injury.", "Травма, закончившая карьеру."),
}
RECORD_LABELS = {
    "best_rank": ("Best global rank", "Лучший мировой ранг"),
    "peak_pp": ("Peak performance", "Пик pp"),
    "best_acc": ("Best accuracy", "Лучшая точность"),
    "best_streak": ("Longest training streak (days)", "Самая длинная серия тренировок (дней)"),
    "followers_max": ("Most followers", "Максимум подписчиков"),
    "peak_money": ("Most money held", "Максимум денег"),
    "best_placement": ("Best tournament placement", "Лучшее место на турнире"),
    "tournament_wins": ("Tournaments won", "Выиграно турниров"),
    "match_wins": ("Tournament matches won", "Выиграно матчей"),
}


def is_retired(player: Player) -> bool:
    return bool(story.get(player, "retired"))


# --- records and snapshot ---------------------------------------------------------------------------


def _placements(db: Session, player: Player) -> tuple[int, int | None, list[int]]:
    """(titles won, best placement, ids of the user's entries)."""
    rows = db.execute(select(TournamentEntry.id, TournamentEntry.placement)
                      .join(Tournament, Tournament.id == TournamentEntry.tournament_id)
                      .where(Tournament.player_id == player.id, TournamentEntry.includes_user.is_(True))).all()
    best, wins = None, 0
    for _, placement in rows:
        if not placement:
            continue
        digits = "".join(ch for ch in placement.split("–")[0] if ch.isdigit())
        if digits:
            n = int(digits)
            best = n if best is None else min(best, n)
            wins += n == 1
    return wins, best, [r[0] for r in rows]


def _update_records(db: Session, player: Player, today: date) -> dict:
    r = dict(story.get(player, "records") or {})
    r.setdefault("started_on", today.isoformat())
    rank = player.global_rank
    if rank and (r.get("best_rank") is None or rank < r["best_rank"]):
        r["best_rank"], r["best_rank_on"] = rank, today.isoformat()
    if player.total_pp > r.get("peak_pp", 0.0):
        r["peak_pp"], r["peak_pp_on"] = round(player.total_pp, 1), today.isoformat()
    if player.play_count >= 20 and player.accuracy > r.get("best_acc", 0.0):
        r["best_acc"] = round(player.accuracy, 2)
    r["best_streak"] = max(r.get("best_streak", 0), player.consecutive_training_days)
    r["followers_max"] = max(r.get("followers_max", 0), player.followers)
    if player.money > r.get("peak_money", 0.0):
        r["peak_money"], r["peak_money_on"] = round(player.money, 1), today.isoformat()
    previous = r.get("injury", simulation.HEALTHY)
    if previous == simulation.SEVERE_RSI and player.injury != simulation.SEVERE_RSI:
        r["injuries_survived"] = r.get("injuries_survived", 0) + 1
    r["injury"] = player.injury
    values = simulation.effective_values(player)
    r["overall_max"] = max(r.get("overall_max", 0.0), round(A.overall(values), 1))
    r["top_sub_max"] = max(r.get("top_sub_max", 0.0), round(max(values.values()), 1))
    wins, best, entries = _placements(db, player)
    r["tournament_wins"] = wins
    if best is not None:
        r["best_placement"] = best
    r["match_wins"] = db.scalar(select(func.count()).select_from(Match).where(Match.winner.in_(entries))) if entries else 0
    team = db.scalar(select(Team).where(Team.player_id == player.id, Team.status == "active"))
    if team:
        r["team_chemistry_max"] = max(r.get("team_chemistry_max", 0.0), round(team.chemistry, 1))
    if "cap_baseline" not in r:
        r["cap_baseline"] = {a.key: a.cap for a in player.attributes if a.key in simulation.STAMINA_CEILING_KEYS}
    story.put(player, "records", r)
    return r


def snapshot(db: Session, player: Player, r: dict) -> AC.Snapshot:
    started = date.fromisoformat(r["started_on"])
    return AC.Snapshot(
        best_rank=r.get("best_rank"), peak_pp=r.get("peak_pp", 0.0), best_acc=r.get("best_acc", 0.0),
        play_count=player.play_count, followers_max=r.get("followers_max", 0), peak_money=r.get("peak_money", 0.0),
        years=(player.in_game_date - started).days / 365.25, best_streak=r.get("best_streak", 0),
        badges=len(player.badges or []), tournament_wins=r.get("tournament_wins", 0), match_wins=r.get("match_wins", 0),
        injuries_survived=r.get("injuries_survived", 0),
        comebacks=db.scalar(select(func.count()).select_from(StoryArc).where(
            StoryArc.player_id == player.id, StoryArc.key == "comeback", StoryArc.status == "resolved")) or 0,
        rivals=db.scalar(select(func.count()).select_from(Rival).where(Rival.player_id == player.id)) or 0,
        goals_done=db.scalar(select(func.count()).select_from(Goal).where(
            Goal.player_id == player.id, Goal.status == "done")) or 0,
        events_resolved=db.scalar(select(func.count()).select_from(LifeEvent).where(
            LifeEvent.player_id == player.id, LifeEvent.status != "pending")) or 0,
        overall_max=r.get("overall_max", 0.0), top_sub_max=r.get("top_sub_max", 0.0),
        team_chemistry_max=r.get("team_chemistry_max", 0.0),
        teams_joined=db.scalar(select(func.count()).select_from(Team).where(
            Team.player_id == player.id, Team.status != "invited")) or 0,
        loans_repaid=story.get(player, "loans_repaid") or 0,
        **{k: int((story.get(player, "spend_stats") or {}).get(k, 0))
           for k in ("coaching_sessions", "sub_months_max", "tournaments_hosted", "lan_visits")},
    )


# --- tick ---------------------------------------------------------------------------------------


def tick(db: Session, player: Player, news: list) -> None:
    today = player.in_game_date
    if is_retired(player) or story.get(player, "legacy_checked_on") == today.isoformat():
        return
    last = story.get_date(player, "legacy_checked_on", today)
    days = max(1, (today - last).days) if story.get(player, "legacy_checked_on") else 0
    story.put(player, "legacy_checked_on", today.isoformat())

    r = _update_records(db, player, today)
    unlocked = dict(story.get(player, "achievements") or {})
    snap = snapshot(db, player, r)
    for a in AC.CATALOG:
        if a.key not in unlocked and a.unlocked(snap):
            unlocked[a.key] = today.isoformat()
            _announce(db, player, a, today, news)
    story.put(player, "achievements", unlocked)

    if economy.hardcore(player):
        r = dict(story.get(player, "records") or {})
        r["negative_days"] = (r.get("negative_days", 0) + days) if player.money < 0 else 0
        story.put(player, "records", r)
        lost = max((r["cap_baseline"].get(a.key, a.cap) - a.cap for a in player.attributes
                    if a.key in simulation.STAMINA_CEILING_KEYS), default=0.0)
        reason = "bankrupt" if r["negative_days"] >= BANKRUPT_DAYS else "injury" if lost >= FATAL_CAP_LOSS else None
        if reason:
            retire(db, player, reason, news)


def _announce(db: Session, player: Player, a: AC.Achievement, today: date, news: list) -> None:
    from app.services import tournaments

    media.private_event(db, player, "ACHIEVEMENT", {
        "achievement": a.name[0], "description": a.desc[0], "rarity": a.rarity, "category": a.category},
                        channel="#osu")
    if a.rarity in ("rare", "epic", "legendary"):  # smaller medals only show up in the Legacy tab
        tournaments._news(db, player, today, "ACHIEVEMENT", f"Achievement unlocked: {a.name[0]}.",
                          2 if a.rarity in ("epic", "legendary") else 1, {"key": a.key, "rarity": a.rarity}, news)
    if a.rarity in ("epic", "legendary"):
        title = f"{player.name} [{player.country}] unlocked '{a.name[0]}'"
        media.emit(db, player, "ACHIEVEMENT_RARE", {"achievement": a.name[0], "description": a.desc[0], "rarity": a.rarity},
                   kind="milestone", title=title, flair="Milestone", base_upvotes=90, tone="impressed",
                   fmt={"player": player.name, "rank_label": a.name[0], "next_label": "the next medal"})


# --- retirement -------------------------------------------------------------------------------------


def retire(db: Session, player: Player, reason: str, news: list | None = None) -> dict:
    from app.services import tournaments

    if is_retired(player):
        raise ValueError("this career is already over")
    today = player.in_game_date
    r = _update_records(db, player, today)
    unlocked = story.get(player, "achievements") or {}
    legends = _legend_comparison_for(db, player, r.get("best_rank"))
    epilogue = {
        "reason": reason, "retired_on": today.isoformat(), "age": round(_age(player, today), 1) if player.birth_date else None,
        "started_on": r["started_on"], "years": round((today - date.fromisoformat(r["started_on"])).days / 365.25, 1),
        "best_rank": r.get("best_rank"), "best_rank_on": r.get("best_rank_on"), "peak_pp": r.get("peak_pp", 0.0),
        "play_count": player.play_count, "tournament_wins": r.get("tournament_wins", 0),
        "badges": len(player.badges or []), "followers_max": r.get("followers_max", 0),
        "achievements": len(unlocked), "score": AC.legacy_score(list(unlocked), r.get("best_rank"), r.get("peak_pp", 0.0)),
        "hardcore": economy.hardcore(player), **legends,
    }
    story.put(player, "retired", {"on": today.isoformat(), "reason": reason, "epilogue": epilogue})
    if player.occupation == "pro":
        player.occupation = "work"
    player.motivation = min(player.motivation, 50.0)

    text = present_epilogue(db, player, "en")
    media.private_event(db, player, "CAREER_RETIRED", {"reason": REASONS.get(reason, REASONS["manual"])[0],
                                                       "summary": text["lines"], "legacy_score": epilogue["score"]},
                        channel="#osu")
    title = f"{player.name} [{player.country}] has retired from competitive osu!"
    media.emit(db, player, "CAREER_RETIRED_POST", {"summary": text["lines"]}, kind="news", title=title,
               body=" ".join(text["lines"])[:1500], flair="News", base_upvotes=400, tone="nostalgic, respectful",
               fmt={"headline": title, "player": player.name})
    if news is not None:
        tournaments._news(db, player, today, "CAREER_END", f"Career over: {REASONS.get(reason, REASONS['manual'])[0]}", 3,
                          {"reason": reason}, news)
    db.flush()
    return epilogue


def _legend_comparison_for(db: Session, player: Player, best_rank: int | None) -> dict:
    legends = [n for n in db.scalars(select(Npc).where(Npc.player_id == player.id, Npc.kind == "legend")) if n.best_rank]
    if not best_rank or not legends:
        return {}
    out: dict = {}
    below = sorted((n for n in legends if n.best_rank > best_rank), key=lambda n: n.best_rank)
    above = sorted((n for n in legends if n.best_rank <= best_rank), key=lambda n: -n.best_rank)
    if below:
        out["outpeaked"] = {"name": below[0].name, "best_rank": below[0].best_rank}
    if above:
        out["behind"] = {"name": above[0].name, "best_rank": above[0].best_rank}
    return out


def _age(player: Player, on: date) -> float:
    return (on - player.birth_date).days / 365.25 if player.birth_date else 0.0


def present_epilogue(db: Session, player: Player, lang: str) -> dict:
    data = (story.get(player, "retired") or {}).get("epilogue")
    if not data:
        return {}
    ru = lang == "ru"
    i = 1 if ru else 0
    from app.services import goals as goals_service

    arcs = [goals_service.present_arc(a, lang)["title"] for a in db.scalars(
        select(StoryArc).where(StoryArc.player_id == player.id).order_by(StoryArc.id))]
    rivals = [n.name for n in (db.get(Npc, rv.npc_id) for rv in db.scalars(select(Rival).where(Rival.player_id == player.id)))
              if n]
    best = data.get("best_rank")
    lines = [REASONS.get(data["reason"], REASONS["manual"])[i]]
    if ru:
        lines.append(f"{data['years']:g} лет в игре, {data['play_count']} плеев"
                     + (f", лучший ранг #{best:,}" if best else ", так и без ранга") + f" ({data.get('best_rank_on') or '—'}).")
        lines.append(f"Пик: {data['peak_pp']:,.0f}pp. Достижений: {data['achievements']}. Титулов: {data['tournament_wins']}.")
        if data.get("outpeaked"):
            lines.append(f"Вы поднялись выше, чем {data['outpeaked']['name']} (лучший ранг #{data['outpeaked']['best_rank']:,}).")
        if data.get("behind"):
            lines.append(f"Но {data['behind']['name']} добрался до #{data['behind']['best_rank']:,}.")
        if arcs:
            lines.append("Сюжетные линии: " + ", ".join(arcs) + ".")
        if rivals:
            lines.append("Соперники: " + ", ".join(rivals) + ".")
        if data.get("hardcore"):
            lines.append("Хардкор-карьера: второго шанса не будет.")
    else:
        lines.append(f"{data['years']:g} years in, {data['play_count']} plays"
                     + (f", best rank #{best:,}" if best else ", never ranked") + f" ({data.get('best_rank_on') or '-'}).")
        lines.append(f"Peak: {data['peak_pp']:,.0f}pp. Achievements: {data['achievements']}. Titles: {data['tournament_wins']}.")
        if data.get("outpeaked"):
            lines.append(f"You peaked higher than {data['outpeaked']['name']} (best rank #{data['outpeaked']['best_rank']:,}).")
        if data.get("behind"):
            lines.append(f"But {data['behind']['name']} reached #{data['behind']['best_rank']:,}.")
        if arcs:
            lines.append("Storylines: " + ", ".join(arcs) + ".")
        if rivals:
            lines.append("Rivals: " + ", ".join(rivals) + ".")
        if data.get("hardcore"):
            lines.append("A hardcore career: there are no second chances.")
    return {**data, "lines": lines, "arcs": arcs, "rivals": rivals}


# --- presentation --------------------------------------------------------------------------------


def overview(db: Session, player: Player, lang: str) -> dict:
    r = dict(story.get(player, "records") or {})
    if "started_on" not in r:
        r = _update_records(db, player, player.in_game_date)
    snap = snapshot(db, player, r)
    unlocked = story.get(player, "achievements") or {}
    done = [{**AC.present(AC.BY_KEY[k], lang), "unlocked_on": d} for k, d in sorted(unlocked.items(), key=lambda kv: kv[1])
            if k in AC.BY_KEY]
    locked = [(a, a.progress(snap)) for a in AC.CATALOG if a.key not in unlocked]
    locked.sort(key=lambda t: -t[1])
    nxt = [{**AC.present(a, lang), "progress": round(p, 3)} for a, p in locked[:8]]
    i = 1 if lang == "ru" else 0
    records = []
    for key, (en, ru) in RECORD_LABELS.items():
        if key in r and r[key] not in (None, 0, 0.0):
            records.append({"key": key, "label": (en, ru)[i], "value": r[key], "date": r.get(f"{key}_on")})
    retired = story.get(player, "retired")
    return {
        "status": {
            "retired": bool(retired), "retired_on": retired["on"] if retired else None,
            "reason": retired["reason"] if retired else None, "hardcore": economy.hardcore(player),
            "economy": "realistic" if economy.realistic(player) else "simple",
            "started_on": r.get("started_on"),
        },
        "score": AC.legacy_score(list(unlocked), r.get("best_rank"), r.get("peak_pp", 0.0)),
        "records": records,
        "achievements": {"unlocked": done, "next": nxt, "total": len(AC.CATALOG), "unlocked_count": len(done),
                         "categories": {k: v[i] for k, v in AC.CATEGORY_LABELS.items()}},
        "budget": budget(player),
        "epilogue": present_epilogue(db, player, lang) if retired else None,
    }


def budget(player: Player) -> dict:
    owed = story.get(player, "loan") or 0.0
    return {
        "realistic": economy.realistic(player), "money": round(player.money, 2), "loan": round(owed, 2),
        "loan_limit": round(economy.loan_limit(player), 2), "months": economy.statement(player),
        "runway": economy.runway(player), "occupation": player.occupation,
    }


def hall_of_fame(db: Session) -> list[dict]:
    out = []
    for p in db.scalars(select(Player)):
        retired = story.get(p, "retired")
        if not retired:
            continue
        e = retired["epilogue"]
        out.append({"id": p.id, "name": p.name, "country": p.country, "hardcore": e.get("hardcore", False),
                    "reason": retired["reason"], "retired_on": retired["on"], "best_rank": e.get("best_rank"),
                    "peak_pp": e.get("peak_pp", 0.0), "achievements": e.get("achievements", 0), "score": e.get("score", 0),
                    "years": e.get("years", 0.0)})
    out.sort(key=lambda row: -row["score"])
    return out
