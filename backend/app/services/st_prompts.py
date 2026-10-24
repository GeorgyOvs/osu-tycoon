"""Prompts and JSON schemas the SillyTavern extension feeds to the LLM.

They live in the engine (not the extension) so tone and format can be tuned in one place.
"""

import json
from datetime import date

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


def irc_prompt(event: dict, channel: str, on: date, usernames: list[str]) -> str:
    return (
        _pronoun_hint(event) +
        f"Simulate the osu! IRC channel {channel} on {on.isoformat()} ({community_flavour(on)}).\n"
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
