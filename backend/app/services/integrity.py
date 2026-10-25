"""Integrity (story layer): reputation, accusations with a replay review, restrictions, world scandals."""

import random
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import integrity as I
from app.engine import simulation
from app.models import Npc, Player, Score
from app.services import media, story, streaming


class IntegrityError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


# --- state -------------------------------------------------------------------------------------


def _state(player: Player) -> dict:
    return dict(story.get(player, "integrity", {}))


def _save(player: Player, st: dict) -> None:
    st["cases"] = st.get("cases", [])[-I.KEEP_CASES:]
    st["log"] = st.get("log", [])[-I.KEEP_LOG:]
    story.put(player, "integrity", st)


def reputation(player: Player) -> float:
    return float(_state(player).get("rep", I.REPUTATION_START))


def adjust_reputation(player: Player, delta: float, reason: str = "") -> float:
    """The hook other systems use (life events, goals, tournaments): clamp to 0..100 and keep a short log."""
    st = _state(player)
    old = float(st.get("rep", I.REPUTATION_START))
    new = max(0.0, min(100.0, old + delta))
    st["rep"] = round(new, 2)
    if abs(new - old) >= 0.01:
        st["log"] = [*st.get("log", []), {"date": player.in_game_date.isoformat(), "delta": round(new - old, 1),
                                           "reason": reason}]
    _save(player, st)
    return new - old


def restricted_until(player: Player) -> date | None:
    raw = _state(player).get("restricted_until")
    return date.fromisoformat(raw) if raw else None


def check_unrestricted(player: Player) -> None:
    until = restricted_until(player)
    if until and player.in_game_date < until:
        raise IntegrityError(409, f"your account is restricted until {until}: ranked scores are disabled during the review")


def sponsor_factor(player: Player) -> float:
    return I.sponsor_factor(reputation(player))


def follower_factor(player: Player) -> float:
    return I.follower_factor(reputation(player))


# --- suspicion ---------------------------------------------------------------------------------


def _handled_stars(player: Player) -> float:
    return 2 * (0.6 + 0.04 * A.overall(simulation.effective_values(player)))


def suspicion(db: Session, player: Player) -> tuple[float, list[dict]]:
    """How suspicious the career looks from the outside, 0..1, with the reasons."""
    today = player.in_game_date
    factors: list[dict] = []
    rank = player.global_rank
    if rank:
        hist = [(date.fromisoformat(d), r) for d, r in story.get(player, "rank_hist", []) if r]
        then = next((r for d, r in reversed(hist) if (today - d).days >= 25), None)
        if then and rank < 100_000 and then / rank >= 3:
            factors.append({"kind": "rank_jump", "level": round(min(1.0, (then / rank - 2) / 6), 3),
                            "from_rank": then, "to_rank": rank})
        if rank <= 1000:
            factors.append({"kind": "routine", "level": 0.25 if rank <= 100 else 0.15})
    handled = _handled_stars(player)
    best = None
    for s in db.scalars(select(Score).where(Score.player_id == player.id,
                                            Score.played_on >= today - timedelta(days=21))):
        ratio = s.stars / handled
        level = max(0.0, (ratio - 1.3) / 0.7) + (0.2 if s.accuracy >= 99.0 and ratio > 1.05 else 0.0)
        if level > 0 and (best is None or level > best[0]):
            best = (level, s)
    if best:
        factors.append({"kind": "great_play", "level": round(min(1.0, best[0]), 3), "play": f"{best[1].artist} - {best[1].title} [{best[1].difficulty_name}]",
                        "pp": round(best[1].pp)})
    return I.suspicion_level(factors), factors


# --- cases -------------------------------------------------------------------------------------


def _open_case(db: Session, player: Player, factor: dict, today: date) -> dict:
    st = _state(player)
    cid = int(st.get("next_id", 1))
    case = {"id": cid, "kind": factor["kind"], "detail": {k: v for k, v in factor.items() if k not in ("kind", "level")},
            "opened": today.isoformat(), "expires": (today + timedelta(days=I.CASE_TTL_DAYS)).isoformat(),
            "status": "open", "response": None, "outcome": None, "resolved": None, "auto": False, "rep_delta": 0.0}
    st["next_id"] = cid + 1
    st["cases"] = [*st.get("cases", []), case]
    _save(player, st)
    # the random 'cheat_accusation' life event must not pile on top of a real case
    last = dict(story.get(player, "event_last", {}))
    last["cheat_accusation"] = today.isoformat()
    story.put(player, "event_last", last)
    media.private_event(db, player, "INTEGRITY_CASE", {"kind": case["kind"], "detail": case["detail"]}, channel="#osu")
    return case


def _case(player: Player, case_id: int) -> tuple[dict, dict]:
    st = _state(player)
    case = next((c for c in st.get("cases", []) if c["id"] == case_id), None)
    if case is None:
        raise IntegrityError(404, f"case {case_id} not found")
    return st, case


def respond(db: Session, player: Player, case_id: int, choice: str, auto: bool = False) -> dict:
    st, case = _case(player, case_id)
    if case["status"] != "open":
        raise IntegrityError(409, "this case is already closed")
    if choice not in I.OUTCOMES:
        raise IntegrityError(422, f"no such response '{choice}'")
    if choice == "stream" and not streaming.available(player.in_game_date):
        raise IntegrityError(409, "streaming doesn't exist yet (Twitch launches in June 2011)")
    rng = random.Random(f"{player.seed}:integrity:{case_id}:{choice}")
    options = I.OUTCOMES[choice]
    key, _, effects = rng.choices(options, weights=[w for _, w, _ in options])[0]

    delta, restricted_days = 0.0, None
    for stat in ("morale", "motivation", "fatigue"):
        if stat in effects:
            setattr(player, stat, max(0.0, min(100.0, getattr(player, stat) + effects[stat])))
    if "followers" in effects:
        gain = effects["followers"]
        player.followers = max(0, player.followers + (round(gain * follower_factor(player)) if gain > 0 else gain))
    if "reputation" in effects:
        delta = adjust_reputation(player, effects["reputation"], f"case:{case['kind']}")
    if "restrict_days" in effects:
        days = rng.randint(*effects["restrict_days"])
        until = player.in_game_date + timedelta(days=days)
        st = _state(player)
        st["restricted_until"] = until.isoformat()
        _save(player, st)
        restricted_days = days
    post = effects.get("post")
    if post:
        title = f"{player.name} [{player.country}]: {I.OUTCOME_TEXT[key][0]}"
        media.emit(db, player, "INTEGRITY_CASE", {"kind": case["kind"], "outcome": key}, kind=post, title=title,
                   flair="Drama" if post == "drama" else "News", base_upvotes=250, tone="split opinions, gossip",
                   fmt={"headline": title, "player": player.name})

    st, case = _case(player, case_id)  # adjust_reputation re-saved the state
    case.update({"status": "restricted" if key == "restriction" else "cleared" if key in ("cleared", "vindicated") else "closed",
                 "response": choice, "outcome": key, "resolved": player.in_game_date.isoformat(), "auto": auto,
                 "rep_delta": round(delta, 1), "restricted_days": restricted_days})
    if key == "restriction":
        case["status"] = "restricted"
    _save(player, st)
    media.private_event(db, player, "INTEGRITY_RESOLVED", {"kind": case["kind"], "response": choice,
                                                           "outcome": I.OUTCOME_TEXT[key][0]}, channel="#osu")
    return case


# --- weekly tick -------------------------------------------------------------------------------


def tick(db: Session, player: Player, news: list) -> None:
    from app.services import tournaments

    today = player.in_game_date
    st = _state(player)

    until = restricted_until(player)
    if until and today >= until:
        st["restricted_until"] = None
        _save(player, st)
        adjust_reputation(player, 3, "wrongly restricted")
        tournaments._news(db, player, until, "RESTRICTION_LIFTED",
                          "Your restriction was lifted: the review found nothing wrong.", 2, {}, news)

    for case in list(_state(player).get("cases", [])):
        if case["status"] == "open" and date.fromisoformat(case["expires"]) <= today:
            respond(db, player, case["id"], I.DEFAULT_RESPONSE, auto=True)

    last = story.get_date(player, "integrity_checked", today - timedelta(days=I.CHECK_EVERY_DAYS))
    weeks = (today - last).days // I.CHECK_EVERY_DAYS
    if weeks < 1:
        return
    story.put_date(player, "integrity_checked", today)
    weeks = min(weeks, 4)
    rng = random.Random(f"{player.seed}:integrity-week:{today.isoformat()}")

    # reputation settles back towards the middle
    st = _state(player)
    rep = float(st.get("rep", I.REPUTATION_START))
    step = I.REPUTATION_DRIFT_PER_WEEK * weeks
    st["rep"] = round(rep + max(-step, min(step, I.REPUTATION_DRIFT_TARGET - rep)), 2)
    _save(player, st)

    _maybe_accuse(db, player, today, weeks, rng)
    _maybe_npc_scandal(db, player, today, weeks, rng, news)


def _maybe_accuse(db: Session, player: Player, today: date, weeks: int, rng: random.Random) -> None:
    if today.year < 2009 or not player.global_rank:
        return
    st = _state(player)
    if any(c["status"] == "open" for c in st.get("cases", [])):
        return
    closed = [date.fromisoformat(c["resolved"]) for c in st.get("cases", []) if c.get("resolved")]
    if closed and (today - max(closed)).days < I.CASE_COOLDOWN_DAYS:
        return
    level, factors = suspicion(db, player)
    if not factors:
        return
    p = 0.02 + 0.30 * level
    p *= 1 + (55 - reputation(player)) / 100
    if rng.random() >= 1 - (1 - max(0.0, min(0.6, p))) ** weeks:
        return
    _open_case(db, player, max(factors, key=lambda f: f["level"]), today)


def _maybe_npc_scandal(db: Session, player: Player, today: date, weeks: int, rng: random.Random, news: list) -> None:
    from app.services import tournaments

    if today.year < 2010 or rng.random() >= 1 - (1 - I.NPC_SCANDAL_CHANCE) ** weeks:
        return
    pool = [n for n in db.scalars(select(Npc).where(Npc.player_id == player.id, Npc.kind == "procedural",
                                                    Npc.status == "active", Npc.rank.is_not(None)))
            if n.rank <= 1500]
    if not pool:
        return
    pool.sort(key=lambda n: n.id)
    npc = rng.choice(pool)
    npc.status = "hiatus"
    npc.away_until = today + timedelta(days=rng.randint(*I.NPC_SCANDAL_AWAY_DAYS))
    npc.motivation = max(0.0, npc.motivation - 25)
    npc.story = {**(npc.story or {}), "restricted": True}
    message = f"{npc.name} [{npc.country}] has been restricted after a community report."
    tournaments._news(db, player, today, "NPC_RESTRICTED", message, 2, {"npc_id": npc.id, "rank": npc.rank}, news)
    media.emit(db, player, "NPC_SCANDAL", {"npc": npc.name, "npc_rank": npc.rank}, kind="drama",
               title=f"{npc.name} restricted?? What do we actually know", flair="Discussion", base_upvotes=900,
               tone="heated, rumours, defenders vs accusers, calls for patience", fmt={"headline": message},
               reactions=media._reactions(db, player, rng, 2, f"Reacting to {npc.name} being restricted.", [npc.id]))


# --- presentation ------------------------------------------------------------------------------


def _text(case: dict, lang: str) -> tuple[str, str]:
    i = 1 if lang == "ru" else 0
    title, body = I.CASE_TEXT[case["kind"]][i], I.CASE_TEXT[case["kind"]][2 + i]
    detail = {"play": "", "pp": "", "from_rank": "?", "to_rank": "?", **case["detail"]}
    return title.format(**detail), body.format(**detail)


def present_case(case: dict, lang: str, today: date) -> dict:
    title, body = _text(case, lang)
    i = 1 if lang == "ru" else 0
    outcome = I.OUTCOME_TEXT[case["outcome"]][i] if case.get("outcome") else ""
    return {
        "id": case["id"], "kind": case["kind"], "title": title, "body": body, "status": case["status"],
        "opened": case["opened"], "expires": case["expires"], "resolved": case.get("resolved"),
        "days_left": (date.fromisoformat(case["expires"]) - today).days if case["status"] == "open" else None,
        "response": case.get("response"), "outcome": outcome, "auto": bool(case.get("auto")),
        "rep_delta": case.get("rep_delta", 0.0), "restricted_days": case.get("restricted_days"),
        "options": [{"key": k, "label": r[i], "hint": r[3 if i else 2]} for k, r in I.RESPONSES.items()]
        if case["status"] == "open" else [],
    }


def overview(db: Session, player: Player, lang: str) -> dict:
    today = player.in_game_date
    st = _state(player)
    level, factors = suspicion(db, player)
    rep = reputation(player)
    until = restricted_until(player)
    cases = [present_case(c, lang, today) for c in reversed(st.get("cases", []))]
    return {
        "reputation": round(rep, 1), "label": I.label(rep, lang),
        "restricted_until": until.isoformat() if until and until > today else None,
        "effects": {"sponsor": round(I.sponsor_factor(rep), 2), "followers": round(I.follower_factor(rep), 2)},
        "suspicion": {"level": level, "factors": [{"kind": f["kind"], "level": f["level"]} for f in factors]},
        "open": [c for c in cases if c["status"] == "open"],
        "history": [c for c in cases if c["status"] != "open"],
        "log": list(reversed(st.get("log", [])))[:15],
    }
