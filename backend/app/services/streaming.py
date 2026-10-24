"""Streaming: playing live for an audience (Twitch launched in June 2011).

Viewers come from followers, rank and the size of the community at the time; highlights
(new top plays, full combos) bring followers; donations and subs bring money. Playing live
also adds pressure: chokes get a little more likely.
"""

import math
import random
from datetime import date

from sqlalchemy.orm import Session

from app.engine import simulation
from app.models import ChatMessage, Player
from app.services import media

TWITCH_LAUNCH = date(2011, 6, 6)
LIVE_PRESSURE = 1.2
INCOME_PER_VIEWER_HOUR = 0.03
TWITCH_CHANNEL = "twitch"

CHAT = {
    "top_play": ["POGGERS {pp}pp", "NEW TOP PLAY LETS GO", "clip it", "{pp}pp holy", "PogChamp"],
    "fc": ["FC!!", "clean", "ez Clap", "no choke today"],
    "fail": ["F", "unlucky", "LUL", "tilt incoming", "it's ok you'll get it"],
    "idle": ["hi chat", "what's the next map?", "song name?", "skin pls", "tablet or mouse?"],
}


class StreamError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def available(on: date) -> bool:
    return on >= TWITCH_LAUNCH


def check(player: Player) -> None:
    if not available(player.in_game_date):
        raise StreamError(409, "Twitch doesn't exist yet (it launches in June 2011)")


def expected_viewers(player: Player) -> float:
    rank_pull = 20000 / (player.global_rank ** 0.6) if player.global_rank else 1.0
    return (2 + 0.04 * player.followers + rank_pull) * media.community_size(player.in_game_date)


def apply(db: Session, player: Player, plays, hours: float) -> list[simulation.Event]:
    """Settle a live session: viewers, followers, money, chat, and a highlight for SillyTavern."""
    on = player.in_game_date
    rng = random.Random(f"{player.seed}:stream:{on.isoformat()}")
    viewers = expected_viewers(player) * math.exp(0.1 * player.form) * rng.uniform(0.8, 1.2)

    era_top_play = media.era_top_play_pp(on)
    boost, highlight = 0.0, None
    chat: list[tuple[str, dict]] = [("idle", {})]
    for p in plays:
        if p.recorded and p.recorded.top_play_position == 1:
            significance = p.recorded.score.pp / era_top_play
            boost += 20 + 600 * significance
            chat.append(("top_play", {"pp": round(p.recorded.score.pp)}))
            if highlight is None or significance > highlight[1]:
                highlight = (p, significance)
        if any(a.attempt.passed and a.attempt.misses == 0 for a in p.attempts):
            boost += 3
            chat.append(("fc", {}))
        if all(not a.attempt.passed for a in p.attempts):
            chat.append(("fail", {}))

    new_followers = max(1, round(hours * (1 + viewers * 0.01) + boost))
    income = round(hours * viewers * INCOME_PER_VIEWER_HOUR, 2)
    player.followers += new_followers
    player.money += income

    names = media.usernames(db, player, rng, 20)
    for kind, fmt in chat[:6]:
        for _ in range(rng.randint(1, 3)):
            db.add(ChatMessage(player_id=player.id, date=on, channel=TWITCH_CHANNEL, author=rng.choice(names),
                               content=rng.choice(CHAT[kind]).format(**fmt), source="procedural"))

    if highlight and player.followers >= 50:
        p, _ = highlight
        media.private_event(db, player, "STREAM_HIGHLIGHT", {
            "viewers": round(viewers), "followers": player.followers,
            "moment": f"New top play live on stream: {p.meta.artist} - {p.meta.title} [{p.meta.version}] "
                      f"+{p.mods or 'NM'} {p.recorded.score.accuracy:.2f}% for {round(p.recorded.score.pp)}pp",
        }, channel=TWITCH_CHANNEL)

    return [simulation.Event(on, "STREAM", f"Streamed {hours:.1f}h to ~{round(viewers)} viewers: "
                                           f"+{new_followers} followers, ${income:,.2f}.",
                             {"viewers": round(viewers), "followers": new_followers, "income": income})]
