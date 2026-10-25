"""The social layer: forum threads, IRC chatter and SillyTavern events from game moments.

Every notable moment becomes (1) an outbox event in the plan's {event_type, data} shape for
SillyTavern, (2) a forum thread with a few procedural comments, and (3) a couple of IRC lines.
The LLM, when connected, adds the real conversation on top; without it the world still talks.
"""

import math
import random
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine import world
from app.models import ChatMessage, ForumComment, ForumThread, Npc, Player, StEvent
from app.services import life, ranking

COUNTRY_CHANNELS = {
    "RU": "#russian", "DE": "#german", "PL": "#polish", "KR": "#korean", "JP": "#japanese", "FR": "#french",
    "ES": "#spanish", "BR": "#portuguese", "CN": "#chinese", "TW": "#chinese", "ID": "#indonesian",
    "PH": "#filipino", "FI": "#finnish", "SE": "#swedish", "NL": "#dutch", "IT": "#italian", "UA": "#ukrainian",
}

COMMENTS = {
    "scorepost": ["{pp}pp?? on {map_short}? what", "how is this even legal", "{player} is actually insane",
                  "{acc}% is disgusting (compliment)", "the consistency on this is unreal", "farm map but still",
                  "first time hearing of {player}, now i'm scared", "gz!!", "o.o", "replay pls",
                  "this is what dedication looks like"],
    "scorepost_choke": ["{misses}x miss... pain", "so close to FC ;_;", "the FC would've been {fc_pp}pp",
                        "that miss is criminal", "choke of the year candidate"],
    "tournament": ["{winner} looked so calm", "that tiebreaker though", "{loser} will be back", "ref???",
                   "what a match", "best set of the tourney so far", "picks were 200 IQ"],
    "news": ["end of an era", "o7", "no way", "called it", "this community never sleeps", "goat"],
    "drama": ["replay or it didn't happen", "cursor movement looks legit to me", "this again...",
              "frame by frame analysis incoming", "witch hunt", "let the mods handle it"],
    "milestone": ["welcome to the club", "gz on {rank_label}!", "the grind pays off", "next stop: {next_label}"],
    "rework": ["my top play lost 80pp, i'm quitting (not really)", "aim players eating good", "rip speed",
               "{player} gained {delta}pp overnight lol", "the committee hates farm maps", "pp is fake anyway"],
    "snipe": ["{sniped} is not going to like this", "who even is {player}??", "rip {sniped}'s #1 ({age})",
              "the snipe heard around the world", "{sniped} takes it back within a week, calling it",
              "that score stood for {age}. respect to both"],
}

IRC_LINES = {
    "scorepost": ["{player} just set {pp}pp on {map_short} o.o", "gz {player}", "wtf {pp}pp", "farm map lol"],
    "tournament": ["{winner} beat {loser} {score}!!", "gg", "that tb was insane"],
    "news": ["did you see? {headline}", "o7", "wait what"],
    "drama": ["drama on reddit again lol", "not this again"],
    "milestone": ["{player} is {rank_label} now", "gz {player}"],
    "snipe": ["{player} just sniped {sniped} on {map_short} o.o", "rip {sniped}", "SNIPED"],
    "rework": ["did you see the pp changes", "my rank went down 2k", "pp rework lol"],
}

COMMENTS["scorepost"] += ["wait is that {player}? they were nowhere last month", "{pp}pp is a lot on {map_short}",
                          "my hands hurt just watching this", "legit question: how long did this take", "{player} cooking again",
                          "this map has no business being that fun", "that acc though", "congrats, now do it on stream"]
COMMENTS["tournament"] += ["{winner} deserved it", "{loser} choked the last map", "nobody expected that bracket",
                           "the commentary was better than the match", "i called {winner} in my bracket", "mappool diff"]
COMMENTS["news"] += ["interesting times", "the scene is changing", "i'll believe it when i see it", "every week something new",
                     "can't wait to see what happens next", "so what now?"]
COMMENTS["milestone"] += ["{player} is moving fast", "big grind, big reward", "remember when they were unranked?"]
IRC_LINES["scorepost"] += ["{player} again?", "{pp}pp lol", "anyone seen {player}'s replay", "ok that was clean"]
IRC_LINES["tournament"] += ["{winner} was on fire", "poor {loser}", "bo{score} was nuts", "who is next round"]
IRC_LINES["news"] += ["ok that's big", "{headline} lol", "didn't see that coming"]
IRC_LINES["milestone"] += ["{player} is flying", "{rank_label}!! gz", "o7 {player}"]


def board_for(on: date) -> str:
    return "osu! forums › General Discussion" if on < date(2013, 1, 1) else "r/osugame"


def channel_for(country: str) -> str:
    return COUNTRY_CHANNELS.get(country, "#osu")


def community_size(on: date) -> float:
    return max(0.08, ranking._era(on)[1])


def _rng(player: Player, *parts) -> random.Random:
    return random.Random(":".join(str(p) for p in (player.seed, *parts)))


def usernames(db: Session, player: Player, rng: random.Random, n: int = 12) -> list[str]:
    names = list(db.scalars(select(Npc.name).where(Npc.player_id == player.id, Npc.status == "active",
                                                    Npc.kind == "procedural").limit(200)))
    rng.shuffle(names)
    return names[:n] or ["peppy", "anon"]


def _player_block(player: Player) -> dict:
    return {"name": player.name, "country": player.country, "gender": player.gender,
            "pronouns": life.pronouns(player), "global_rank": player.global_rank,
            "previous_rank": player.previous_rank, "total_pp": round(player.total_pp, 2)}


def _attitude(npc: Npc) -> str:
    comps = world.composites(npc.overall, npc.style)
    if comps["mentality"] >= 60:
        return "Gracious and genuinely impressed; maybe a friendly challenge."
    return "A bit salty and dismissive, but trying to hide it."


def _reactions(db: Session, player: Player, rng: random.Random, count: int, context: str,
               npc_ids: list[int] | None = None) -> list[dict]:
    """NPCs who should react in character: the ones involved, otherwise rivals near the player's rank."""
    npcs: list[Npc] = []
    for npc_id in npc_ids or []:
        npc = db.get(Npc, npc_id)
        if npc:
            npcs.append(npc)
    if len(npcs) < count:
        ranked = list(db.scalars(select(Npc).where(Npc.player_id == player.id, Npc.rank.is_not(None))))
        target = player.global_rank or 1_000_000
        ranked.sort(key=lambda n: abs(math.log(max(n.rank, 1)) - math.log(target)))
        legends = [n for n in ranked if n.kind == "legend"][:2]
        pool = [n for n in ranked[:8] + legends if n not in npcs]
        rng.shuffle(pool)
        npcs += pool[: count - len(npcs)]
    out = []
    for npc in npcs[:count]:
        legend = world.LEGENDS_BY_NAME.get(npc.name) if npc.kind == "legend" else None
        note = f" ({legend.note})" if legend and legend.note else ""
        out.append({"name": npc.name, "attitude": _attitude(npc), "context": context + note})
    return out


def emit(
    db: Session,
    player: Player,
    event_type: str,
    data: dict,
    *,
    kind: str,
    title: str,
    body: str = "",
    flair: str = "",
    author: str | None = None,
    base_upvotes: float,
    tone: str,
    fmt: dict,
    reactions: list[dict] | None = None,
    event_date: date | None = None,
) -> StEvent:
    on = event_date or player.in_game_date
    rng = _rng(player, event_type, on.isoformat(), title)
    upvotes = max(1, round(base_upvotes * community_size(on) * rng.uniform(0.6, 1.5)))
    names = usernames(db, player, rng)

    payload = {"event_type": event_type, "data": {
        "in_game_date": on.isoformat(), "player": _player_block(player), **data,
        "npc_reactions_needed": reactions or [],
        "reddit_thread_spec": {"board": board_for(on), "upvotes": upvotes, "tone": tone},
    }}

    thread = ForumThread(player_id=player.id, date=on, board=board_for(on), kind=kind, title=title[:300],
                         body=body[:4000], author=author or names[0], flair=flair, upvotes=upvotes,
                         llm_status="pending")
    pool = COMMENTS[kind] + (COMMENTS["scorepost_choke"] if kind == "scorepost" and fmt.get("misses") else [])
    for text in rng.sample(pool, k=min(len(pool), rng.randint(2, 4))):
        thread.comments.append(ForumComment(author=rng.choice(names), content=text.format(**fmt),
                                            upvotes=max(1, round(upvotes * rng.uniform(0.02, 0.3))),
                                            source="procedural"))
    db.add(thread)
    db.flush()

    channel = channel_for(player.country) if kind in ("scorepost", "milestone") else "#osu"
    for text in rng.sample(IRC_LINES[kind], k=min(len(IRC_LINES[kind]), rng.randint(1, 3))):
        db.add(ChatMessage(player_id=player.id, date=on, channel=channel, author=rng.choice(names),
                           content=text.format(**fmt), source="procedural"))

    event = StEvent(player_id=player.id, date=on, type=event_type, payload=payload, thread_id=thread.id,
                    channel=channel, handled=False)
    db.add(event)
    db.flush()
    return event


# --- specific moments ------------------------------------------------------------------------


def _short(title: str) -> str:
    return title if len(title) <= 40 else title[:37] + "..."


# A scorepost needs a play worth at least this share of the era's best play (2016: ~375pp).
SCOREPOST_MIN_SIGNIFICANCE = 0.45
NOTABLE_SNIPE_RANK = 5000
NOTABLE_PLAYER_RANK = 5000  # below this the community doesn't know who you are
NOTABLE_TOURNAMENT_TIERS = ("open", "major", "owc")
POPULAR_MAP_PLAYS = 1_000_000


def era_top_play_pp(on: date) -> float:
    """Roughly the best single play in the game at the time: the #1's total pp / 18."""
    return ranking.top_pp(on) / 18


def score_submission(db: Session, player: Player, score, map_max_combo: int, fc_pp: float | None,
                     position: int) -> StEvent | None:
    """A scorepost, but only for plays the community of that era would actually care about."""
    from app.models import WorldEvent
    records = db.scalars(select(WorldEvent).where(WorldEvent.player_id == player.id,
                         WorldEvent.date == score.played_on,
                         WorldEvent.type.in_(("FIRST_1000PP", "NPC_SCORE_RECORD"))))
    if any(e.data.get("score_kind") == "user" and e.data.get("score_id") == score.id for e in records):
        return None  # the record already has its scorepost
    significance = score.pp / era_top_play_pp(player.in_game_date)
    if not ((position == 1 and significance >= SCOREPOST_MIN_SIGNIFICANCE)
            or (position <= 3 and significance >= SCOREPOST_MIN_SIGNIFICANCE + 0.15)):
        return None
    mods = f" +{score.mods}" if score.mods else ""
    fc = "FC" if score.misses == 0 else f"{score.misses}xMiss"
    fc_part = f" ({round(fc_pp)}pp if FC)" if score.misses and fc_pp else ""
    tag = "Their new top play!" if position == 1 else f"#{position} top play"
    title = (f"{player.name} | {score.artist} - {score.title} [{score.difficulty_name}]{mods} ({score.accuracy:.2f}%) "
             f"{score.max_combo}/{map_max_combo}x {fc} | {round(score.pp)}pp{fc_part} | {tag}")
    rng = _rng(player, "score", score.id)
    data = {"score": {
        "beatmap_id": score.beatmap_id, "beatmapset_id": score.beatmapset_id,
        "title": f"{score.artist} - {score.title}", "difficulty": score.difficulty_name,
        "mods": score.mods or "Nomod", "accuracy": round(score.accuracy, 2), "max_combo": score.max_combo,
        "map_max_combo": map_max_combo, "misses": score.misses, "pp_earned": round(score.pp, 2),
        "pp_if_fc": round(fc_pp, 2) if fc_pp else None, "is_new_top_play": position == 1,
        "top_play_position": position,
    }}
    fmt = {"player": player.name, "pp": round(score.pp), "map_short": _short(score.title), "acc": f"{score.accuracy:.2f}",
           "misses": score.misses, "fc_pp": round(fc_pp) if fc_pp else "?", "mods": score.mods or "NM"}
    tone = "hype and disbelief" if significance > 0.8 else "impressed" if significance > 0.4 else "friendly encouragement"
    return emit(db, player, "SCORE_SUBMISSION", data, kind="scorepost", title=title, flair="Gameplay",
                body=f"https://osu.ppy.sh/beatmaps/{score.beatmap_id}",
                base_upvotes=10 * math.exp(6 * min(significance, 1.5)) * (1.3 if not score.misses else 1.0),
                tone=tone, fmt=fmt,
                reactions=_reactions(db, player, rng, 1, f"Reacting to {player.name}'s {round(score.pp)}pp play."))


NPC_POST_MIN_SIGNIFICANCE = 0.3
NPC_POSTS_PER_WEEK = 3


def npc_scorepost(db: Session, player: Player, npc, score, beatmap, value: float, rng: random.Random,
                  user_best_pp: float = 0.0) -> StEvent | None:
    """A scorepost for a strong play by a generated player, so the forum isn't only about the user.
    Only plays the era's community would care about, or ones that rival the user's own best, get a thread."""
    from app.models import MapScore
    significance = value / era_top_play_pp(score.set_on)
    rivals_user = user_best_pp > 0 and value >= user_best_pp * 0.95
    if significance < NPC_POST_MIN_SIGNIFICANCE and not (rivals_user and significance >= 0.15):
        return None
    chance = min(0.85, max(0.0, (significance - 0.25) / 0.6)) + (0.3 if rivals_user else 0.0)
    if rng.random() > chance:
        return None
    previous = db.scalar(select(func.max(MapScore.pp)).where(MapScore.player_id == player.id, MapScore.npc_id == npc.id,
                                                              MapScore.id != score.id)) or 0.0
    tag = "Their new top play!" if value > previous else "Quick farm session"
    mods = f" +{score.mods}" if score.mods else ""
    fc = "FC" if score.misses == 0 else f"{score.misses}xMiss"
    map_title = f"{beatmap.beatmapset.artist} - {beatmap.beatmapset.title} [{beatmap.version}]"
    max_combo = beatmap.max_combo or score.max_combo
    title = (f"{npc.name} | {map_title}{mods} ({score.accuracy:.2f}%) {score.max_combo}/{max_combo}x {fc} | "
             f"{round(value)}pp | {tag}")
    data = {"score": {"player": npc.name, "beatmap_id": beatmap.id, "beatmapset_id": beatmap.beatmapset_id,
                      "title": f"{beatmap.beatmapset.artist} - {beatmap.beatmapset.title}", "difficulty": beatmap.version,
                      "mods": score.mods or "Nomod", "accuracy": round(score.accuracy, 2), "max_combo": score.max_combo,
                      "map_max_combo": max_combo, "misses": score.misses, "pp_earned": round(value, 2),
                      "is_new_top_play": value > previous, "better_than_the_user": rivals_user}}
    fmt = {"player": npc.name, "pp": round(value), "map_short": _short(beatmap.beatmapset.title), "acc": f"{score.accuracy:.2f}",
           "misses": score.misses, "fc_pp": "?", "mods": score.mods or "NM"}
    tone = "hype and disbelief" if significance > 0.8 else "impressed" if significance > 0.45 else "casual"
    return emit(db, player, "NPC_SCOREPOST", data, kind="scorepost", title=title, flair="Gameplay",
                body=f"https://osu.ppy.sh/beatmaps/{beatmap.id}",
                base_upvotes=10 * math.exp(6 * min(significance, 1.5)) * (1.3 if not score.misses else 1.0),
                tone=tone, fmt=fmt, event_date=score.set_on,
                reactions=_reactions(db, player, rng, 1, f"Reacting to {npc.name}'s own {round(value)}pp play.", [npc.id]))


TIER_UPVOTES = {"community6": 40, "community": 80, "open": 300, "major": 1500, "owc": 3000}


def tournament_match(db: Session, player: Player, t, m, user_entry, opponent, won: bool,
                     upset: bool) -> StEvent | None:
    if t.tier not in NOTABLE_TOURNAMENT_TIERS and not (upset and player.global_rank and player.global_rank <= 50_000):
        return None  # a 5/6-digit cup match isn't community news
    played = [x for x in m.maps if "slot" in x]
    deciding = played[-1] if played else {}
    moments = []
    for mp in played[-3:]:
        for p in mp.get("players", []):
            if p["kind"] == "user" or p.get("choked"):
                moments += [f"{p['name']}: {k}" for k in p.get("key_moments", [])[:1]]
    winner, loser = (user_entry.name, opponent.name) if won else (opponent.name, user_entry.name)
    score = f"{max(m.score_a, m.score_b)} - {min(m.score_a, m.score_b)}"
    npc_ids = [opponent.npc_id] if opponent.npc_id else [x.get("npc_id") for x in opponent.members if x.get("npc_id")]
    rng = _rng(player, "match", m.id)
    data = {
        "tournament_name": t.name, "stage": m.stage,
        "match_result": {"player_team": user_entry.name, "opponent_team": opponent.name,
                         "score": score if won else f"{min(m.score_a, m.score_b)} - {max(m.score_a, m.score_b)}",
                         "winner": winner,
                         "deciding_map": f"{deciding.get('title', '?')} ({deciding.get('slot', '?')})"},
        "key_moments": moments[:4],
    }
    event_type = "TOURNAMENT_UPSET" if upset else "TOURNAMENT_MATCH"
    title = (f"[{t.name}] {winner} defeats {loser} {score} in {m.stage}" + (" — huge upset!" if upset else ""))
    fmt = {"winner": winner, "loser": loser, "score": score, "player": player.name}
    context = f"Just {'lost to' if won else 'beat'} {player.name} {score} in {m.stage} of {t.name}."
    return emit(db, player, event_type, data, kind="tournament", title=title, flair="Tournament",
                base_upvotes=TIER_UPVOTES.get(t.tier, 100) * (1.8 if upset else 1.0),
                tone="complete disbelief, memes" if upset else "hyped match discussion", fmt=fmt,
                reactions=_reactions(db, player, rng, 1, context, [i for i in npc_ids if i]))


def world_headline(db: Session, player: Player, news) -> StEvent | None:
    """Big world news becomes a thread; a sudden rising star sometimes draws cheating accusations."""
    rng = _rng(player, "news", news.date.isoformat(), news.type, news.message)
    npc_ids = [news.data["npc_id"]] if news.data.get("npc_id") else []
    if news.type in ("FIRST_1000PP", "NPC_SCORE_RECORD"):
        from app.models import MapScore, Score
        from app.engine import pp_history
        data = news.data
        model = MapScore if data.get("score_kind") == "npc" else Score
        saved = db.get(model, data.get("score_id")) if data.get("score_id") else None
        if (saved is None or saved.player_id != player.id
                or saved.beatmap_id != data.get("beatmap_id")
                or pp_history.era_for(news.date).ranking != "pp"):
            return None
        npc = db.get(Npc, saved.npc_id) if model is MapScore else None
        if model is MapScore and (npc is None or npc.kind != "procedural"):
            return None
        return emit(db, player, "WORLD_NEWS", {"headline": news.message, "news_type": news.type, **data},
                    kind="scorepost", title=news.message,
                    body=f"{news.message}\nhttps://osu.ppy.sh/beatmaps/{saved.beatmap_id}",
                    flair="Gameplay", base_upvotes=4000, tone="excited discussion about this saved score",
                    fmt={"player": npc.name if npc else player.name, "pp": round(data["score_pp"]),
                         "map_short": data.get("map_title", ""), "misses": saved.misses, "fc_pp": "?",
                         "acc": f"{saved.accuracy:.2f}", "mods": saved.mods or "NM"},
                    event_date=news.date)
    if news.type == "RISING_STAR" and rng.random() < 0.25 and npc_ids:
        npc = db.get(Npc, npc_ids[0])
        title = f"Is {npc.name} legit? Went from nowhere to top {news.data.get('rank', 100)} in months"
        return emit(db, player, "COMMUNITY_DRAMA", {"topic": "cheating accusation", "subject": npc.name},
                    kind="drama", title=title, flair="Discussion", base_upvotes=800,
                    tone="suspicious, heated debate, defenders vs accusers", fmt={"headline": title},
                    reactions=_reactions(db, player, rng, 2, f"Debating whether {npc.name} is cheating.", npc_ids))
    if news.importance < 3 or news.type in USER_CENTRIC_NEWS:
        return None
    base = 4000 if news.type in ("RETIRED", "RETURN") else 1500
    return emit(db, player, "WORLD_NEWS", {"headline": news.message, "news_type": news.type},
                kind="news", title=news.message, flair="News", base_upvotes=base,
                tone="nostalgic and emotional" if news.type == "RETIRED" else "excited discussion",
                fmt={"headline": news.message},
                reactions=_reactions(db, player, rng, 2, f"Commenting on: {news.message}", npc_ids))


USER_CENTRIC_NEWS = {"TOURNAMENT_WIN", "TOURNAMENT_RESULT", "TOURNAMENT_UPSET", "OWC_SELECTED"}


def tournament_victory(db: Session, player: Player, t, user_entry) -> StEvent | None:
    if t.tier not in NOTABLE_TOURNAMENT_TIERS and (not player.global_rank or player.global_rank > 50_000):
        return None
    rng = _rng(player, "victory", t.id)
    title = f"{user_entry.name} wins {t.name}!" if t.team_size > 1 else f"{player.name} wins {t.name}!"
    return emit(db, player, "TOURNAMENT_VICTORY", {"tournament_name": t.name, "tier": t.tier},
                kind="tournament", title=title, flair="Tournament", base_upvotes=TIER_UPVOTES.get(t.tier, 100) * 2,
                tone="celebration, 'deserved', highlight clips",
                fmt={"winner": user_entry.name, "loser": "the field", "score": "", "player": player.name},
                reactions=_reactions(db, player, rng, 2, f"{player.name} just won {t.name}."))


# (highest rank that counts, label, base upvotes): most prestigious first.
MILESTONES = [(1, "#1", 15000), (10, "top 10", 4000), (100, "top 100", 1200), (999, "3 digits", 300),
              (9_999, "4 digits", 50)]


def rank_milestone(db: Session, player: Player, before: int | None, after: int | None) -> StEvent | None:
    if after is None:
        return None
    crossed = [(limit, label, ups) for limit, label, ups in MILESTONES
               if after <= limit and (before is None or before > limit)]
    if not crossed:
        return None
    limit, label, ups = crossed[0]  # the most prestigious threshold crossed
    if limit > 9_999:
        return None
    nxt = next((lbl for lim, lbl, _ in reversed(MILESTONES) if lim < limit), "#1")
    rng = _rng(player, "milestone", label)
    title = f"{player.name} [{player.country}] just reached {label} (#{after:,})"
    return emit(db, player, "RANK_MILESTONE", {"milestone": label, "rank": after, "previous_rank": before},
                kind="milestone", title=title, flair="Milestone", base_upvotes=ups,
                tone="congratulatory", fmt={"player": player.name, "rank_label": label, "next_label": nxt},
                reactions=_reactions(db, player, rng, 1, f"{player.name} just reached {label}."))


def player_injury(db: Session, player: Player, event) -> StEvent:
    rng = _rng(player, "injury", event.date.isoformat())
    if not player.global_rank or player.global_rank > NOTABLE_PLAYER_RANK:
        return private_event(db, player, "PLAYER_INJURY", {"injury": event.type, "details": event.message},
                             channel="#osu")  # nobody outside the top ranks writes about this
    title = f"{player.name} announces a forced break: {event.message}"
    return emit(db, player, "PLAYER_INJURY", {"injury": event.type, "details": event.message, **(event.data or {})},
                kind="news", title=title, flair="News", base_upvotes=120, tone="sympathetic, ergonomics advice",
                fmt={"headline": title},
                reactions=_reactions(db, player, rng, 1, f"{player.name} got injured."))


INJURY_EVENTS = {"INJURY_SEVERE_RSI", "PERMANENT_DAMAGE"}


def after_action(db: Session, player: Player, rank_before: int | None, sim_events=(), news=()) -> None:
    """Turn what just happened into social content: injuries, world headlines, rank milestones."""
    for e in sim_events:
        if e.type in INJURY_EVENTS:
            player_injury(db, player, e)
    for n in news:
        world_headline(db, player, n)
    rank_milestone(db, player, rank_before, player.global_rank)


def _age(set_on: date, now: date) -> str:
    days = (now - set_on).days
    if days >= 365:
        return f"{days // 365} year{'s' if days >= 730 else ''}"
    if days >= 60:
        return f"{days // 30} months"
    return f"{max(days, 1)} days"


def snipe_is_notable(db: Session, sniped, map_play_count: int) -> bool:
    if sniped.kind in ("legend", "anchor") or map_play_count >= POPULAR_MAP_PLAYS:
        return True
    npc = db.get(Npc, sniped.npc_id) if sniped.npc_id else None
    return bool(npc and npc.best_rank and npc.best_rank <= NOTABLE_SNIPE_RANK)


def snipe_first_place(db: Session, player: Player, map_title: str, sniped, user_entry,
                      map_play_count: int = 0) -> StEvent | None:
    """The user took #1 on a map. Obscure maps and unknown holders only get a line in IRC."""
    on = player.in_game_date
    if not snipe_is_notable(db, sniped, map_play_count):
        db.add(ChatMessage(player_id=player.id, date=on, channel=channel_for(player.country),
                           author=player.name, content=f"took #1 on {_short(map_title)} :D", source="procedural"))
        return None
    age = _age(sniped.set_on, on)
    legend = sniped.kind in ("legend", "anchor")
    title = f"{player.name} snipes {sniped.name}'s #1 on {map_title} (a {age} old score)"
    data = {
        "map": map_title, "sniped_player": sniped.name, "sniped_player_kind": sniped.kind,
        "sniped_score": {"score": sniped.score, "mods": sniped.mods or "Nomod", "accuracy": sniped.accuracy,
                         "set_on": sniped.set_on.isoformat()},
        "user_score": {"score": user_entry.score, "mods": user_entry.mods or "Nomod", "accuracy": user_entry.accuracy},
    }
    rng = _rng(player, "snipe", map_title, sniped.name)
    npc_ids = [sniped.npc_id] if sniped.npc_id else []
    fmt = {"player": player.name, "sniped": sniped.name, "age": age, "map_short": _short(map_title)}
    return emit(db, player, "SNIPE_FIRST_PLACE", data, kind="snipe", title=title, flair="Gameplay",
                base_upvotes=2500 if legend else 150, tone="shock and drama" if legend else "playful rivalry",
                fmt=fmt, reactions=_reactions(db, player, rng, 2,
                                              f"{sniped.name} just lost their #1 on {map_title} to {player.name}.",
                                              npc_ids))


def sniped_by_npc(db: Session, player: Player, npc, map_title: str, score) -> StEvent:
    """An NPC took the user's #1 back."""
    title = f"{npc.name} takes #1 on {map_title} back from {player.name}"
    rng = _rng(player, "sniped", map_title, npc.name, score.score)
    data = {"map": map_title, "sniper": npc.name, "sniper_score": {"score": score.score, "mods": score.mods or "Nomod",
                                                                   "accuracy": score.accuracy}}
    fmt = {"player": npc.name, "sniped": player.name, "age": "a while", "map_short": _short(map_title)}
    return emit(db, player, "SNIPED_BY_NPC", data, kind="snipe", title=title, flair="Gameplay",
                base_upvotes=600 if npc.kind == "legend" else 60, tone="banter, 'the rivalry continues'", fmt=fmt,
                reactions=_reactions(db, player, rng, 1, f"Just took back #1 on {map_title} from {player.name}.",
                                     [npc.id]))


def pp_rework(db: Session, player: Player, old_era, new_era, pp_before: float) -> StEvent:
    rng = _rng(player, "rework", new_era.key)
    delta = round(player.total_pp - pp_before)
    title = f"PP REWORK MEGATHREAD ({new_era.name}): WHAT HAPPENED TO MY pp / RANK???"
    data = {"from_system": old_era.name, "to_system": new_era.name, "summary": new_era.summary,
            "player_pp_before": round(pp_before, 2), "player_pp_after": round(player.total_pp, 2)}
    return emit(db, player, "PP_REWORK", data, kind="rework", title=title, body=new_era.summary, flair="News",
                base_upvotes=5000, tone="chaos, winners gloating, losers coping",
                fmt={"player": player.name, "delta": f"{delta:+d}"},
                reactions=_reactions(db, player, rng, 2, f"Reacting to the {new_era.name} pp changes."))


def private_event(db: Session, player: Player, event_type: str, data: dict, channel: str) -> StEvent:
    """An event for SillyTavern that isn't public news (no forum thread, no channel chatter)."""
    payload = {"event_type": event_type, "data": {"in_game_date": player.in_game_date.isoformat(),
                                                  "player": _player_block(player), **data}}
    event = StEvent(player_id=player.id, date=player.in_game_date, type=event_type, payload=payload,
                    thread_id=None, channel=channel, handled=False)
    db.add(event)
    db.flush()
    return event


def rival_overtake(db: Session, player: Player, npc, user_passed: bool) -> StEvent:
    return private_event(db, player, "RIVAL_OVERTAKE", {
        "rival": npc.name, "rival_country": npc.country, "rival_rank": npc.rank,
        "user_passed_rival": user_passed,
        "npc_reactions_needed": [{"name": npc.name, "attitude": _attitude(npc),
                                  "context": ("Just got overtaken in the rankings by their rival "
                                              if user_passed else "Just overtook their rival ") + player.name}],
    }, channel=f"DM:{npc.name}")


def duel_result(db: Session, player: Player, npc, duel, notable: bool) -> StEvent:
    """Every 1v1 reaches SillyTavern; only notable ones become forum threads."""
    played = [m for m in duel.maps if "slot" in m]
    moments = [k for m in played[-3:] for p in m.get("players", []) for k in p.get("key_moments", [])[:1]]
    score = f"{duel.score_user}-{duel.score_npc}"
    data = {
        "opponent": npc.name, "opponent_country": npc.country, "opponent_rank": npc.rank,
        "format": f"BO{duel.best_of}", "kind": duel.kind, "score": score, "won": duel.won,
        "deciding_map": played[-1].get("title") if played else None, "key_moments": moments[:4],
        "npc_reactions_needed": [{"name": npc.name, "attitude": _attitude(npc),
                                  "context": f"Just {'lost' if duel.won else 'won'} a BO{duel.best_of} 1v1 against "
                                             f"{player.name} ({score} from {player.name}'s side)."}],
    }
    if not notable:
        return private_event(db, player, "DUEL_RESULT", data, channel=f"DM:{npc.name}")
    winner, loser = (player.name, npc.name) if duel.won else (npc.name, player.name)
    big, small = max(duel.score_user, duel.score_npc), min(duel.score_user, duel.score_npc)
    title = f"[Showmatch] {winner} beats {loser} {big}-{small} in a BO{duel.best_of} 1v1"
    rng = _rng(player, "duel", duel.id)
    return emit(db, player, "DUEL_RESULT", data, kind="tournament", title=title, flair="Showmatch",
                base_upvotes=1200 if npc.kind == "legend" else 300, tone="hype, clips, 'rematch when'",
                fmt={"winner": winner, "loser": loser, "score": f"{big}-{small}", "player": player.name},
                reactions=_reactions(db, player, rng, 1, data["npc_reactions_needed"][0]["context"], [npc.id]))
