"""Prompts and JSON schemas the SillyTavern extension feeds to the LLM.

They live in the engine (not the extension) so tone and format can be tuned in one place.
"""

import json
from datetime import date

COUNTRY_CHANNELS = {"#russian", "#german", "#polish", "#korean", "#japanese", "#french", "#spanish", "#portuguese",
                    "#chinese", "#indonesian", "#filipino", "#finnish", "#swedish", "#dutch", "#italian", "#ukrainian"}

FORUM_SCHEMA = {
    "type": "object",
    "properties": {
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "author": {"type": "string"},
                    "content": {"type": "string"},
                    "upvotes": {"type": "integer"},
                    # Optional rather than a union type: Google's legacy response_schema
                    # represents type as a scalar protobuf enum and rejects type arrays.
                    "reply_to": {"type": "integer", "description": "Index of an earlier comment; omit for a top-level comment."},
                },
                "required": ["author", "content"],
            },
        }
    },
    "required": ["comments"],
}

IRC_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"author": {"type": "string"}, "content": {"type": "string"}},
                "required": ["author", "content"],
            },
        }
    },
    "required": ["lines"],
}


THREADS_SCHEMA = {
    "type": "object",
    "properties": {
        "threads": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "author": {"type": "string"},
                    "flair": {"type": "string"},
                    "upvotes": {"type": "integer"},
                    "comments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"author": {"type": "string"}, "content": {"type": "string"},
                                           "upvotes": {"type": "integer"}},
                            "required": ["author", "content"],
                        },
                    },
                },
                "required": ["title", "body", "author"],
            },
        }
    },
    "required": ["threads"],
}


def community_flavour(on: date) -> str:
    if on.year <= 2011:
        return ("the old osu! forums: small tight-knit community, phpBB-style posts, ranked score talk, "
                "'o.o', 'gz', early memes, Cookiezi worship starting")
    if on.year <= 2015:
        return ("early r/osugame and osu! forums: pp just arrived, scoreposts, 'when you see it', "
                "Korean players dominating, HD reading debates")
    if on.year <= 2020:
        return ("r/osugame in the farm era: scorepost meta, 'farm map', 'Sotarks', 'how is this legal', "
                "Twitch clips, 1000pp hype, copypastas")
    return ("modern r/osugame: rapid trigger, high BPM DT, 'mrekk diff', clip culture, deep pp discourse, "
            "jokes about hand pain and wooting keyboards")


def _pronoun_hint(event: dict) -> str:
    player = event.get("data", {}).get("player") or {}
    if not player.get("pronouns"):
        return ""
    return f"Refer to {player.get('name', 'the player')} as {player['pronouns']}.\n"


def forum_prompt(event: dict, thread: dict, on: date, usernames: list[str]) -> str:
    return (
        _pronoun_hint(event) +
        f"You are simulating the osu! community in {on.isoformat()} ({community_flavour(on)}).\n"
        f"A thread was posted on {thread['board']}:\n"
        f"TITLE: {thread['title']}\n"
        f"BODY: {thread['body'] or '(none)'}\n\n"
        f"Game event that caused it (JSON):\n{json.dumps(event, ensure_ascii=False)}\n\n"
        "Treat the supplied event as the only source of score facts. Do not invent records, beatmaps, pp values, "
        "or scores for real players. A player's total account pp is not a single-play pp record. "
        "Before 2012-07-24 pp did not exist: discuss ranked score, not new pp records.\n"
        "Write 5-9 realistic comments in the voice of that era's community: short, varied, a mix of "
        "praise, jokes, stats nerding, mild salt and memes. If npc_reactions_needed lists players, include "
        "a comment from each of them in character. Never break character or mention AI.\n"
        f"Prefer these usernames for random commenters: {', '.join(usernames)}.\n"
        "Answer with JSON only: {\"comments\": [{\"author\": str, \"content\": str, \"upvotes\": int, "
        "\"reply_to\": index-of-earlier-comment}]}. Omit reply_to for top-level comments."
    )


def _recent_block(recent: list[str] | None) -> str:
    if not recent:
        return ""
    return ("Recent lines in this channel (do NOT repeat or paraphrase them; move the conversation on):\n"
            + "\n".join(recent[-12:]) + "\n\n")


def irc_prompt(event: dict, channel: str, on: date, usernames: list[str], recent: list[str] | None = None) -> str:
    return (
        _pronoun_hint(event) +
        f"Simulate the osu! IRC channel {channel} on {on.isoformat()} ({community_flavour(on)}).\n"
        + _recent_block(recent) +
        f"Something just happened (JSON):\n{json.dumps(event, ensure_ascii=False)}\n\n"
        "Only discuss score facts in this event. Never invent records, maps or pp values, or credit real "
        "players with unprovided scores. Total account pp is not single-play pp. Before 2012-07-24 "
        "pp did not exist, so do not announce pp records.\n"
        "Write 4-8 chat lines reacting to it: lowercase, short, typos allowed, emoticons like o.o and :D, "
        "people talking over each other. Use the channel's language if it's a country channel. "
        f"Usernames to use: {', '.join(usernames)}. Never mention AI.\n"
        "Answer with JSON only: {\"lines\": [{\"author\": str, \"content\": str}]}"
    )


def dm_prompt(event: dict, on: date) -> str:
    data = event.get("data", {})
    npc = data.get("npc", {})
    history = "\n".join(f"{m['author']}: {m['content']}" for m in data.get("conversation", []))
    return (
        _pronoun_hint(event)
        + f"You are {npc.get('name')} ({npc.get('country')}), an osu! player"
        + (f" ranked #{npc['rank']:,}" if npc.get("rank") else "")
        + f", chatting in private messages on {on.isoformat()} ({community_flavour(on)}).\n"
        f"Who you are: {npc.get('profile', 'a regular player')}.\n"
        f"Your relationship with {data.get('player', {}).get('name', 'them')}: {npc.get('relationship', 'acquaintance')}.\n"
        f"Conversation so far:\n{history}\n\n"
        "Reply as yourself in 1-3 short chat messages: casual, lowercase is fine, stay in character, never mention AI, "
        "don't invent game results that aren't in the facts.\n"
        "Answer with JSON only: {\"lines\": [{\"author\": \"" + str(npc.get("name")) + "\", \"content\": str}]}"
    )


def narration_prompt(event: dict, on: date) -> str:
    return (
        _pronoun_hint(event) +
        f"As the narrator of an osu! career story set on {on.isoformat()}, describe this moment in 2-4 vivid "
        "sentences in second person, grounded strictly in the facts below. Do not invent results.\n"
        f"{json.dumps(event, ensure_ascii=False)}"
    )


def ambient_prompt(event: dict, channel: str, on: date, usernames: list[str], recent: list[str] | None = None) -> str:
    data = event.get("data", {})
    language = ("Write in the channel's language (country channels are mostly in that language, with English slang). "
                if channel in COUNTRY_CHANNELS else "")
    mode = data.get("mode", "topic")
    focus = {
        "topic": f"Today's loose topic: {data.get('topic_hint', 'whatever people feel like')}.",
        "news": "People are reacting to the supplied recent headlines (pick one or two; the rest of the chat wanders).",
        "spotlight": ("People are talking about this other player (JSON): "
                      f"{json.dumps(data.get('spotlight'), ensure_ascii=False)}. Use only the facts given."),
        "user": "People notice the new player named in the context; keep it light and varied, not worship.",
    }.get(mode, "")
    about = ("" if mode == "user" else
             "The chat is NOT about the player character: talk about other players, maps, news, the meta and everyday "
             "life, and do not mention or invent anything about them. ")
    ctx = {k: data.get(k) for k in ("recent_headlines", "tournaments", "player") if data.get(k)}
    return (
        f"Simulate everyday chatter in the osu! IRC channel {channel} on {on.isoformat()} ({community_flavour(on)}).\n"
        + _recent_block(recent) +
        f"{focus}\n"
        f"World context (JSON; use only if it fits): {json.dumps(ctx, ensure_ascii=False)}\n"
        "Write 6-12 chat lines from several different people with distinct personalities (a newbie, a grinder, "
        "a joker, someone helpful, someone salty). Mix topics: it is fine to wander off or answer an earlier message. "
        "Lowercase, short, typos and emoticons allowed. Don't make everyone agree. "
        f"{about}Never invent records, pp values or scores for real players, and never mention AI. "
        f"{language}Usernames to use: {', '.join(usernames)}.\n"
        "Answer with JSON only: {\"lines\": [{\"author\": str, \"content\": str}]}"
    )


def reply_prompt(event: dict, channel: str, on: date, usernames: list[str], recent: list[str] | None = None) -> str:
    data = event.get("data", {})
    msg = data.get("message", {})
    language = ("Reply in the channel's language. " if channel in COUNTRY_CHANNELS else "")
    return (
        f"Simulate the osu! IRC channel {channel} on {on.isoformat()} ({community_flavour(on)}).\n"
        + _recent_block(data.get("recent_chat") or recent) +
        f"The player {msg.get('author')} just wrote: \"{msg.get('text')}\"\n"
        f"What they are after: {data.get('intent', 'chat')}. Grounded facts you may use (JSON): "
        f"{json.dumps(data.get('facts') or {}, ensure_ascii=False)}\n"
        f"Draft replies from the engine (rewrite them in your own words, keep their meaning): "
        f"{json.dumps(data.get('suggested_replies') or [], ensure_ascii=False)}\n"
        "If a specific player is addressed, that player answers in character using their attitude. Recommend only maps "
        "and targets from the facts (never invent scores). If the player provokes, react like real people: salty, "
        "amused, defensive or dismissive. If a duel was created or declined, say so naturally. "
        "Write 1-4 natural replies from different people in the channel: answer questions honestly within what an "
        "osu! player of that era would know, joke, disagree or just say hi; someone may change the subject. Do not "
        "make everyone gush about the player. Short, lowercase, typos allowed. "
        f"{language}Never invent scores or records, never mention AI. Usernames: {', '.join(usernames)}.\n"
        "Answer with JSON only: {\"lines\": [{\"author\": str, \"content\": str}]}"
    )


def threads_prompt(event: dict, on: date, usernames: list[str]) -> str:
    data = event.get("data", {})
    return (
        f"You are simulating the osu! community forum on {data.get('board', 'the forums')} in {on.isoformat()} "
        f"({community_flavour(on)}).\n"
        f"Context (JSON): {json.dumps({k: data.get(k) for k in ('recent_headlines', 'tournaments')}, ensure_ascii=False)}\n"
        f"Threads that already exist (do NOT duplicate their topics): {json.dumps(data.get('existing_titles', []), ensure_ascii=False)}\n"
        "Write 2-3 NEW threads that real players of that time would post: help requests, setup or map discussions, "
        "tournament recruiting, opinions on the meta, mapping feedback, memes, community questions. Each needs a "
        "title, a short body (1-4 sentences), an author and 3-7 varied comments (agreements, jokes, disagreements, "
        "useful tips). Stay era-appropriate (before 2012-07-24 pp did not exist). Never invent records or scores for "
        "real players and never mention AI.\n"
        f"Prefer these usernames: {', '.join(usernames)}.\n"
        "Answer with JSON only: {\"threads\": [{\"title\": str, \"body\": str, \"author\": str, \"flair\": str, "
        "\"comments\": [{\"author\": str, \"content\": str}]}]}"
    )
