"""Ambient community life: chatter and forum discussions that aren't reactions to one specific moment.

Every couple of in-game days a channel gets some procedural lines about a seeded topic, plus an
`AMBIENT_CHATTER` event so SillyTavern can write the real conversation (grounded in headlines,
upcoming tournaments and what the channel said recently, so it doesn't repeat itself). About once a
week the same happens for the forum: a procedural discussion thread and a `FORUM_IDEAS` event asking
the LLM for a few fresh threads.
"""

import random
import time
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine import pp_history
from app.models import ChatMessage, ForumComment, ForumThread, Npc, StEvent, Team, Tournament, WorldEvent
from app.models import Player
from app.services import media, story

CHATTER_EVERY_DAYS = 2
FORUM_EVERY_DAYS = 7
MAX_PENDING_AMBIENT = 3

# topic -> (hint for the LLM, procedural lines). {name} is another user, {a}/{b} are skills or gear.
TOPICS: dict[str, tuple[str, list[str]]] = {
    "map_rec": ("someone asks for map recommendations around their level; others answer with different advice",
                ["any good maps for 4 digit players?", "what should i farm now", "try anything with simple rhythm and big spacing",
                 "depends what u want to train tbh", "just play whatever is fun, pp will come", "i got stuck at the same maps for weeks"]),
    "help_skill": ("a player is stuck on one skill (jumps, streams, reading, accuracy) and asks for tips",
                   ["how do i stop missing streams at 180bpm", "jumps feel impossible lol", "reading low ar is my weak spot",
                    "relax your hand, seriously", "you need more volume not harder maps", "i fixed mine by just playing slower"]),
    "gear": ("a mouse vs tablet / keyboard / monitor debate",
             ["tablet or mouse for jumps?", "mouse. fight me", "my mouse started double clicking again",
              "144hz changed everything for me", "what keyboard are you guys using", "chair matters more than people think"]),
    "memes": ("random jokes and in-jokes of the era, nothing about specific scores",
              ["o.o", "that one map that everybody has played 400 times", "me: one more map. 4am: one more map",
               "why do all the good songs have 3 star diffs", "lag spike at the worst moment as always", "it's not the mouse it's me"]),
    "tournament_talk": ("hype and speculation about an upcoming or running tournament from the provided list",
                        ["who are you picking this weekend", "the mappool looks brutal", "bracket is stacked",
                         "anyone playing quals?", "i'm just here for the matches", "hope the refs are fast this time"]),
    "world_news": ("people react to one of the supplied recent headlines",
                   ["did you guys see the news", "that was coming honestly", "wild week for the scene", "o7",
                    "i didn't expect that at all", "this is going to change the rankings"]),
    "pp_debate": ("a discussion about how pp works and whether it is fair (only after pp existed)",
                  ["pp is just farm maps in a trench coat", "aim pp is so overweighted", "accuracy needs more love",
                   "the weighting is fine, you just need more top plays", "ranked score was better lol"]),
    "score_grind": ("grinding ranked score and which maps give the most (only before pp existed)",
                    ["ranked score is a grind", "passing everything gives most points", "anyone else farming packs",
                     "who is first on the score ranking now", "gotta get that sv2 style acc"]),
    "streaming": ("streams and streamers (only after Twitch existed)",
                  ["anyone live right now?", "chat is so fast today", "that streamer has no chill", "clip that please",
                   "stream sniping again..."]),
    "audio_offset": ("audio latency, offset and why timing feels off", ["is your offset right? mine drifted again", "use wasapi if you can",
                                                                  "i swear the song is late", "mapper's offset is just wrong on that one"]),
    "newbies": ("welcoming newcomers and answering basic questions", ["welcome! stick around", "just click the circles lol",
                                                                     "what's the best skin for beginners", "ranked or loved?", "no one starts good, relax"]),
    "mappers": ("mapping talk: quality, bubble, nominations, favourite mappers", ["that set got bubbled in a day", "waiting for the mod queue is pain",
                                                                              "mapper is so underrated", "flow in this map is perfect", "nominators asleep again"]),
}
RU_LINES = ["кто тут сегодня играет?", "посоветуйте карты на фарм", "у меня опять мышка двоится", "гз всем, кто сегодня топ взял",
            "что за мета сейчас", "я просто пришёл за мемами", "а кто смотрел турнир на выходных?", "оффсет опять сбился, ужас",
            "сколько у вас часов в игре?", "скины — это отдельная религия", "о.о", "нужен совет по стримам, застрял на 180"]

THREAD_IDEAS = [
    ("What's your current setup? ({year} edition)", "gear", "Post your mouse/tablet, keyboard and monitor. What would you change?"),
    ("Weekly help thread: ask anything about improving", "help_skill", "No question too basic. Be nice."),
    ("Maps you replay when you need to feel good", "map_rec", "Mine is a short, easy-to-flow one. What about you?"),
    ("How long did it take you to reach your current rank?", "newbies", "Hours played vs rank, for people wondering if they are slow."),
    ("Unpopular opinions about the current meta", "pp_debate", "Keep it civil. Tell us what you think is overrated."),
    ("Tournament season: who is playing what?", "tournament_talk", "Find teammates, ask about rank ranges, share tips."),
    ("Show us your best clip or funniest fail", "memes", "Bonus points for self-deprecating stories."),
    ("What song got you into this game?", "memes", "Mine was a random anime opening on page 2."),
    ("Mapping corner: what are you working on?", "mappers", "Share WIPs and ask for mods."),
]
THREAD_COMMENTS = ["i'd say it depends on your goals", "this again lol", "good thread", "same here", "never thought about that",
                   "bookmarking this", "can confirm", "skill issue (jk)", "honestly yeah", "that is fair"]


def _era_topics(on: date, has_team: bool) -> list[str]:
    keys = list(TOPICS)
    if pp_history.era_for(on).ranking != "pp":
        keys.remove("pp_debate")
    else:
        keys.remove("score_grind")
    if on < date(2011, 6, 6):
        keys.remove("streaming")
    return keys


def _rng(player: Player, *parts) -> random.Random:
    return random.Random(":".join(str(p) for p in (player.seed, "chatter", *parts)))


def _channels(db: Session, player: Player) -> list[tuple[str, int]]:
    out = [("#osu", 3)]
    country = media.channel_for(player.country)
    if country != "#osu":
        out.append((country, 2))
    team = db.scalar(select(Team).where(Team.player_id == player.id, Team.status == "active"))
    if team:
        from app.services import teams

        out.append((teams.channel(team), 2))
    return out


def _recent_chat(db: Session, player: Player, channel: str, n: int = 12) -> list[str]:
    rows = db.scalars(select(ChatMessage).where(ChatMessage.player_id == player.id, ChatMessage.channel == channel)
                      .order_by(ChatMessage.id.desc()).limit(n))
    return [f"{m.author}: {m.content}" for m in reversed(list(rows))]


def _headlines(db: Session, player: Player, n: int = 4) -> list[str]:
    rows = db.scalars(select(WorldEvent).where(WorldEvent.player_id == player.id, WorldEvent.importance >= 2)
                      .order_by(WorldEvent.date.desc(), WorldEvent.id.desc()).limit(n))
    return [f"{e.date}: {e.message}" for e in rows]


def _upcoming(db: Session, player: Player, n: int = 3) -> list[str]:
    today = player.in_game_date
    rows = db.scalars(select(Tournament).where(Tournament.player_id == player.id, Tournament.status != "finished",
                                               Tournament.start_date <= today + timedelta(days=45))
                      .order_by(Tournament.start_date).limit(n))
    return [f"{t.name} ({t.status}, starts {t.start_date})" for t in rows]


def _pending(db: Session, player: Player, event_type: str) -> int:
    return db.scalar(select(func.count()).select_from(StEvent).where(
        StEvent.player_id == player.id, StEvent.type == event_type, StEvent.handled.is_(False))) or 0


def tick(db: Session, player: Player, news: list) -> None:
    today = player.in_game_date
    if player.birth_date and (today - player.birth_date).days < 365 * 8:
        return
    last = story.get_date(player, "chatter_last", today - timedelta(days=CHATTER_EVERY_DAYS))
    if (today - last).days >= CHATTER_EVERY_DAYS:
        story.put_date(player, "chatter_last", today)
        _ambient(db, player, today)
    if story.get(player, "forum_ideas_last") is None:  # first week: start the clock a few days in
        story.put_date(player, "forum_ideas_last", today - timedelta(days=FORUM_EVERY_DAYS // 2))
    last_forum = story.get_date(player, "forum_ideas_last", today)
    if (today - last_forum).days >= FORUM_EVERY_DAYS:
        story.put_date(player, "forum_ideas_last", today)
        _forum(db, player, today)


ST_ACTIVE_SECONDS = 180  # SillyTavern counts as connected if it polled this recently
NUDGE_MIN_SECONDS = 30
NUDGE_PER_DAY = 14

SPOTLIGHT_LINES = {
    "rising": ["{npc} keeps climbing, rank {rank} now", "{npc} is actually scary lately", "watch out for {npc}",
               "how did {npc} get so good so fast", "{npc} [{country}] going places"],
    "top": ["{npc} is just on another level", "is {npc} really that far ahead?", "{npc} would win that tourney in their sleep",
            "imagine being {npc}", "{npc} top {rank}, deserved"],
    "away": ["has anyone heard from {npc}?", "{npc} still on break?", "miss seeing {npc} around", "{npc} coming back soon?"],
    "legend": ["{npc} was something else back then", "the old {npc} replays are unreal", "{npc} changed how people play",
               "everyone copies {npc}'s style now", "people forget how good {npc} was"],
}
NEWS_LINES = ["did you see this? {news}", "{news}... wild", "so {news}", "{news} lol", "not surprised about this one: {news}"]
REPLIES_GREET = ["o/", "hey {user}", "hi!", "yo {user}", "welcome", "sup"]
REPLIES_QUESTION = ["depends tbh", "no idea, sorry", "try asking in #osu", "good question lol", "i think so? not sure",
                    "ask someone ranked higher", "google it (kidding)", "it varies a lot"]
REPLIES_ACK = ["lol", "true", "same", "haha", "agreed", "yeah that's fair", "o.o", "fr", "interesting"]
RU_REPLIES = ["привет!", "ну такое", "согласен", "хз, честно", "ха, да", "это точно", "о.о", "а я думаю иначе"]
DM_FALLBACK = ["hey :)", "lol", "busy grinding rn, talk later", "gl with your climb", "what's your rank now?", "o/",
               "haha yeah", "i'll think about it", "nice, keep it up"]


def mark_st_poll(player: Player) -> None:
    story.put(player, "st_poll_at", time.time())


def st_active(player: Player) -> bool:
    return time.time() - float(story.get(player, "st_poll_at", 0)) < ST_ACTIVE_SECONDS


def _spotlight(db: Session, player: Player, rng: random.Random) -> tuple[dict, str] | None:
    """Another player the chat can talk about: a top name, a rising star, someone on break or a legend."""
    npcs = list(db.scalars(select(Npc).where(Npc.player_id == player.id, Npc.rank.is_not(None)).order_by(Npc.pp.desc()).limit(80)))
    away = list(db.scalars(select(Npc).where(Npc.player_id == player.id, Npc.status.in_(("injured", "hiatus"))).limit(20)))
    legends = [n for n in db.scalars(select(Npc).where(Npc.player_id == player.id, Npc.kind == "legend"))]
    pools = [("top", npcs[:15]), ("rising", [n for n in npcs if n.best_rank and n.rank and n.rank <= n.best_rank * 1.1][:30] or npcs[15:60]),
             ("away", away), ("legend", legends)]
    pools = [(k, v) for k, v in pools if v]
    if not pools:
        return None
    kind, pool = rng.choice(pools)
    npc = rng.choice(pool)
    news = db.scalar(select(WorldEvent.message).where(WorldEvent.player_id == player.id, WorldEvent.message.contains(npc.name))
                     .order_by(WorldEvent.date.desc()).limit(1))
    facts = {"name": npc.name, "country": npc.country, "rank": npc.rank, "status": npc.status, "kind": npc.kind,
             "titles": npc.titles, "latest_news": news}
    return facts, kind


def _lines_for(db: Session, player: Player, rng: random.Random, mode: str, channel: str, today: date, names: list[str],
               pool: list[str]) -> tuple[list[str], dict]:
    extra: dict = {}
    if mode == "spotlight":
        found = _spotlight(db, player, rng)
        if found:
            facts, kind = found
            extra["spotlight"] = facts
            return [rng.choice(SPOTLIGHT_LINES[kind]).format(npc=facts["name"], rank=facts["rank"] or "?",
                                                           country=facts["country"]) for _ in range(rng.randint(2, 3))], extra
    if mode == "news":
        news = _headlines(db, player, 6)
        if news:
            text = rng.choice(news).split(": ", 1)[-1]
            return [rng.choice(NEWS_LINES).format(news=text), rng.choice(["o7", "wow", "didn't see that coming"])], extra
    if channel == "#russian" and rng.random() < 0.8:
        return rng.sample(RU_LINES, 3), extra
    return rng.sample(pool, min(len(pool), rng.randint(2, 4))), extra


def _ambient(db: Session, player: Player, today: date, salt: str = "") -> None:
    rng = _rng(player, today.isoformat(), salt)
    channels = _channels(db, player)
    channel = rng.choices([c for c, _ in channels], weights=[w for _, w in channels])[0]
    mode = rng.choices(["topic", "news", "spotlight", "user"], weights=[4, 2.5, 3, 0.7 if player.global_rank else 0])[0]
    topic = rng.choice(_era_topics(today, len(channels) > 2))
    hint, pool = TOPICS[topic]
    names = media.usernames(db, player, rng, 8)
    lines, extra = _lines_for(db, player, rng, mode, channel, today, names, pool)
    for text in lines:
        db.add(ChatMessage(player_id=player.id, date=today, channel=channel, author=rng.choice(names), content=text,
                           source="procedural"))
    if _pending(db, player, "AMBIENT_CHATTER") >= MAX_PENDING_AMBIENT:
        return
    data = {
        "in_game_date": today.isoformat(), "channel": channel, "mode": mode, "topic": topic, "topic_hint": hint,
        "recent_headlines": _headlines(db, player), "tournaments": _upcoming(db, player),
        "recent_chat": _recent_chat(db, player, channel)[-8:], **extra,
    }
    if mode == "user":  # the player is only part of the conversation now and then
        data["player"] = media._player_block(player)
    payload = {"event_type": "AMBIENT_CHATTER", "data": data}
    db.add(StEvent(player_id=player.id, date=today, type="AMBIENT_CHATTER", payload=payload, thread_id=None,
                   channel=channel, handled=False))
    db.flush()


def nudge(db: Session, player: Player) -> int:
    """Real-time life for an idle player: the chat keeps talking even while the calendar stands still."""
    now = time.time()
    today = player.in_game_date
    if now - float(story.get(player, "nudge_at", 0)) < NUDGE_MIN_SECONDS:
        return 0
    day, count = story.get(player, "nudge_day", [today.isoformat(), 0])
    if day != today.isoformat():
        count = 0
    if count >= NUDGE_PER_DAY:
        return 0
    story.put(player, "nudge_at", now)
    story.put(player, "nudge_day", [today.isoformat(), count + 1])
    before = db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.player_id == player.id))
    _ambient(db, player, today, salt=f"idle{count}")
    return (db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.player_id == player.id)) or 0) - (before or 0)


def respond(db: Session, player: Player, channel: str, text: str) -> int:
    """People answer what the player actually said (see chat_intents). With SillyTavern connected the LLM writes the
    words from the same facts; otherwise short grounded lines are posted straight away."""
    from app.services import chat_intents

    today = player.in_game_date
    rng = random.Random(f"{player.seed}:reply:{today}:{channel}:{text}:{time.time_ns() // 10**9}")
    names = [n for n in media.usernames(db, player, rng, 6) if n != player.name]
    reply = chat_intents.build(db, player, channel, text, rng, names)
    if st_active(player):
        payload = {"event_type": "CHAT_REPLY", "data": {
            "in_game_date": today.isoformat(), "channel": channel, "message": {"author": player.name, "text": text},
            "intent": reply.intent, "facts": reply.facts, "suggested_replies": [{"author": a, "content": c} for a, c in reply.lines],
            "recent_chat": _recent_chat(db, player, channel)[-10:], "player": media._player_block(player)}}
        db.add(StEvent(player_id=player.id, date=today, type="CHAT_REPLY", payload=payload, thread_id=None,
                       channel=channel, handled=False))
        db.flush()
        return 0
    for author, line in reply.lines:
        db.add(ChatMessage(player_id=player.id, date=today, channel=channel, author=author, content=line, source="procedural"))
    db.flush()
    return len(reply.lines)


def dm_fallback(db: Session, player: Player, npc_name: str, text: str) -> None:
    """An in-character answer from the person you wrote to when no LLM is connected."""
    if st_active(player):
        return
    from app.services import chat_intents

    rng = random.Random(f"{player.seed}:dmfb:{player.in_game_date}:{npc_name}:{text}")
    reply = chat_intents.build(db, player, f"DM:{npc_name}", text, rng, [npc_name], dm_with=npc_name)
    lines = [c for _, c in reply.lines][:2] or [rng.choice(DM_FALLBACK)]
    for line in lines:
        db.add(ChatMessage(player_id=player.id, date=player.in_game_date, channel=f"DM:{npc_name}", author=npc_name,
                           content=line, source="procedural"))
    db.flush()


def _forum(db: Session, player: Player, today: date) -> None:
    rng = _rng(player, "forum", today.isoformat())
    names = media.usernames(db, player, rng, 10)
    title, topic, body = rng.choice(THREAD_IDEAS)
    thread = ForumThread(player_id=player.id, date=today, board=media.board_for(today), kind="discussion",
                         title=title.format(year=today.year), body=body, author=rng.choice(names), flair="Discussion",
                         upvotes=max(1, round(rng.uniform(8, 80) * media.community_size(today))), llm_status="pending")
    lines = TOPICS[topic][1] + THREAD_COMMENTS
    for text in rng.sample(lines, 3):
        thread.comments.append(ForumComment(author=rng.choice(names), content=text, source="procedural",
                                            upvotes=max(1, round(thread.upvotes * rng.uniform(0.05, 0.4)))))
    db.add(thread)
    if _pending(db, player, "FORUM_IDEAS"):
        return
    recent = db.scalars(select(ForumThread.title).where(ForumThread.player_id == player.id)
                        .order_by(ForumThread.id.desc()).limit(12))
    payload = {"event_type": "FORUM_IDEAS", "data": {
        "in_game_date": today.isoformat(), "player": media._player_block(player), "board": media.board_for(today),
        "recent_headlines": _headlines(db, player, 5), "tournaments": _upcoming(db, player),
        "existing_titles": list(recent),
    }}
    db.add(StEvent(player_id=player.id, date=today, type="FORUM_IDEAS", payload=payload, thread_id=None,
                   channel="forum", handled=False))
    db.flush()
