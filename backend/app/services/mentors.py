"""Mentors (story layer): ask a stronger player to coach a skill group, train with them, graduate."""

import random
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import mentors as M
from app.engine import psychology, simulation, world
from app.engine.training import Drill, Era
from app.models import Npc, Player
from app.services import life, media, rivals, story

LOG_KEEP = 20


class MentorError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _overall(player: Player) -> float:
    return A.overall(simulation.effective_values(player))


def available(player: Player) -> str | None:
    """Why mentoring isn't possible right now, or None."""
    if player.in_game_date.year < M.MENTOR_FROM_YEAR:
        return f"mentoring isn't a thing yet in {player.in_game_date.year}"
    years = life.age(player)
    if years is not None and years < M.MIN_AGE:
        return "you're too young to find a mentor"
    return None


def state(player: Player) -> dict | None:
    return story.get(player, "mentor")


def _log(player: Player, text: str) -> None:
    entries = [*story.get(player, "mentor_log", []), {"date": player.in_game_date.isoformat(), "text": text}]
    story.put(player, "mentor_log", entries[-LOG_KEEP:])


def _focus_group(npc: Npc) -> str:
    comps = world.composites(npc.overall, npc.style)
    return max(M.GROUP_LABELS, key=lambda g: comps[g] if g != "physical" else comps[g] - 6)


def _chance(db: Session, player: Player, npc: Npc, mine: float) -> tuple[float, str | None]:
    rival = rivals.rival_for(db, player, npc.id)
    chance = M.acceptance_chance(
        motivation=player.motivation, same_country=npc.country == player.country, followers=player.followers,
        gap=world.display_overall(npc.overall) - mine, rival_heat=rival.heat if rival else None,
        past_bond=float((story.get(player, "mentor_past", {}) or {}).get(str(npc.id), 0.0)))
    return chance, ("rivals don't coach each other" if rival and chance == 0.0 else None)


def candidates(db: Session, player: Player, limit: int = 8) -> list[dict]:
    mine = _overall(player)
    today = player.in_game_date
    cooldowns = story.get(player, "mentor_refused", {}) or {}
    rows = list(db.scalars(select(Npc).where(Npc.player_id == player.id, Npc.status == "active", Npc.rank.is_not(None))))
    pool = [n for n in rows if mine + 6 <= world.display_overall(n.overall) <= mine + 40 and (not player.global_rank or n.rank < player.global_rank)]
    pool.sort(key=lambda n: (n.country != player.country, abs(world.display_overall(n.overall) - mine - 16)))
    out = []
    for npc in pool[:limit]:
        chance, why = _chance(db, player, npc, mine)
        refused = cooldowns.get(str(npc.id))
        wait = (date.fromisoformat(refused) + timedelta(days=M.ASK_COOLDOWN_DAYS) - today).days if refused else 0
        out.append({"npc_id": npc.id, "name": npc.name, "country": npc.country, "rank": npc.rank,
                    "overall": round(world.display_overall(npc.overall), 1), "focus": _focus_group(npc), "chance": round(chance * 100),
                    "blocked": why or (f"asked recently, try again in {wait} days" if wait > 0 else None)})
    return out


def overview(db: Session, player: Player) -> dict:
    today = player.in_game_date
    st = state(player)
    mentor = None
    if st:
        npc = db.get(Npc, st["npc_id"])
        mentor = {**st, "rank": npc.rank if npc else None, "overall": round(world.display_overall(npc.overall), 1) if npc else None,
                  "boost_active": st.get("boost_until", "") >= today.isoformat(),
                  "gap": round(world.display_overall(npc.overall) - _overall(player), 1) if npc else None}
    why = available(player)
    return {"available": why is None, "reason": why, "mentor": mentor,
            "candidates": [] if st or why else candidates(db, player),
            "log": list(reversed(story.get(player, "mentor_log", []))),
            "mind": mind(db, player)}


def mind(db: Session, player: Player) -> dict:
    data = psychology.summary(player, player.in_game_date)
    names = {n.id: n.name for n in db.scalars(select(Npc).where(Npc.id.in_([f["npc_id"] for f in data["fear"]])))} if data["fear"] else {}
    data["fear"] = [{**f, "name": names.get(f["npc_id"], "?")} for f in data["fear"]]
    return data


def ask(db: Session, player: Player, npc_id: int) -> dict:
    why = available(player)
    if why:
        raise MentorError(409, why)
    if state(player):
        raise MentorError(409, "you already have a mentor")
    npc = db.get(Npc, npc_id)
    if npc is None or npc.player_id != player.id or npc.status != "active" or npc.rank is None:
        raise MentorError(404, "that player isn't available")
    today = player.in_game_date
    mine = _overall(player)
    if world.display_overall(npc.overall) < mine + 3:
        raise MentorError(409, f"{npc.name} has little to teach you at your level")
    refused = (story.get(player, "mentor_refused", {}) or {}).get(str(npc.id))
    if refused and (today - date.fromisoformat(refused)).days < M.ASK_COOLDOWN_DAYS:
        raise MentorError(409, f"{npc.name} was asked recently; try again later")
    chance, why_not = _chance(db, player, npc, mine)
    if M.roll(f"{player.seed}:mentor-ask:{npc.id}:{today.isoformat()}", chance):
        group = _focus_group(npc)
        story.put(player, "mentor", {
            "npc_id": npc.id, "name": npc.name, "country": npc.country, "group": group, "since": today.isoformat(),
            "bond": 30.0, "interest": 70.0, "sessions": 0, "last_session": today.isoformat(), "boost": 1.0,
            "boost_until": "", "overall_at_start": round(mine, 1), "ticked_on": today.isoformat()})
        _log(player, f"{npc.name} agreed to mentor you in {M.GROUP_LABELS[group]}.")
        media.private_event(db, player, "MENTOR_STARTED", {"mentor": npc.name, "rank": npc.rank, "focus": group}, channel=f"DM:{npc.name}")
        return {"accepted": True, "message": f"{npc.name} agreed to mentor you in {M.GROUP_LABELS[group]}."}
    refusals = dict(story.get(player, "mentor_refused", {}) or {})
    refusals[str(npc.id)] = today.isoformat()
    story.put(player, "mentor_refused", refusals)
    reason = why_not or "too busy right now"
    _log(player, f"{npc.name} turned you down: {reason}.")
    return {"accepted": False, "message": f"{npc.name} turned you down: {reason}."}


def end(db: Session, player: Player, reason: str = "ended") -> None:
    st = state(player)
    if not st:
        raise MentorError(409, "you have no mentor")
    past = dict(story.get(player, "mentor_past", {}) or {})
    past[str(st["npc_id"])] = st.get("bond", 0.0)
    story.put(player, "mentor_past", past)
    story.put(player, "mentor", None)
    texts = {"ended": f"You stopped training with {st['name']}.",
             "lost_interest": f"{st['name']} lost interest after you stopped showing up.",
             "gone": f"{st['name']} is no longer around to mentor you.",
             "graduated": f"{st['name']} says you've caught up: your mentorship is over."}
    _log(player, texts[reason])
    media.private_event(db, player, "MENTOR_ENDED", {"mentor": st["name"], "reason": reason, "sessions": st.get("sessions", 0)},
                        channel=f"DM:{st['name']}")
    if reason == "graduated":
        title = f"{player.name} [{player.country}] has caught up with their mentor {st['name']}"
        media.emit(db, player, "MENTOR_GRADUATION", {"mentor": st["name"], "sessions": st.get("sessions", 0)},
                   kind="milestone", title=title, flair="Milestone", base_upvotes=140, tone="warm, proud",
                   fmt={"player": player.name, "rank_label": "the student became the equal",
                        "next_label": "the next level"})


def session(db: Session, player: Player, hours: float):
    from app.routers.career import _run  # the same calendar path as training

    st = state(player)
    if not st:
        raise MentorError(409, "you have no mentor")
    npc = db.get(Npc, st["npc_id"])
    if npc is None or npc.status != "active":
        end(db, player, "gone")
        db.commit()
        raise MentorError(409, f"{st['name']} is no longer around")
    cost = M.PRO_COST_PER_HOUR * hours if player.occupation == "pro" else 0.0
    if player.money < cost:
        raise MentorError(409, f"a session costs ${cost:.0f}; you have ${player.money:.0f}")
    group = st["group"]
    subs = [s.key for s in A.GROUPS_BY_KEY[group].subs]
    drill = Drill("mentor_session", "Mentor session", f"Coaching with {st['name']}.",
                  {k: M.MENTOR_DRILL_SHARE for k in subs}, available_from=Era.OLD_SCHOOL, strain=0.6,
                  motivation_per_hour=0.2)
    today = player.in_game_date
    st = {**st, "boost": M.boost_for(st["bond"]), "boost_until": (today + timedelta(days=M.BOOST_DAYS)).isoformat()}
    story.put(player, "mentor", st)
    from app.services import condition

    learning, caps = condition.learning_extras(db, player)
    result = _run(db, player, simulation.DayPlan(drill=drill, hours=hours, learning=learning, caps=caps), 1)
    player.money -= cost
    current = state(player)  # the day's tick may already have ended the mentorship (graduation)
    if current:
        st = {**current, "bond": min(100.0, current["bond"] + 4), "interest": min(100.0, current["interest"] + 8),
              "sessions": current["sessions"] + 1, "last_session": today.isoformat()}
        story.put(player, "mentor", st)

    advice = None
    rng = random.Random(f"{player.seed}:mentor-advice:{today.isoformat()}")
    if rng.random() < 0.35:
        advice = rng.choice(M.ADVICE[group])
        attrs = [a for a in player.attributes if a.key in subs]
        weakest = min(attrs, key=lambda a: a.base)
        weakest.base = min(weakest.cap, weakest.base + 0.3)
        _log(player, f"Session with {st['name']}: {advice}")
    else:
        _log(player, f"Session with {st['name']} ({hours:g}h).")
    db.commit()
    return result, advice


def tick(db: Session, player: Player, news: list) -> None:
    st = state(player)
    if not st:
        return
    today = player.in_game_date
    if st.get("ticked_on") == today.isoformat():
        return
    last_tick = date.fromisoformat(st.get("ticked_on", today.isoformat()))
    elapsed = max(0, (today - last_tick).days)
    npc = db.get(Npc, st["npc_id"])
    if npc is None or npc.status != "active":
        end(db, player, "gone")
        return
    idle = (today - date.fromisoformat(st["last_session"])).days
    interest = st["interest"]
    if idle > M.IDLE_GRACE_DAYS:
        interest -= M.IDLE_DECAY_PER_DAY * min(elapsed, idle - M.IDLE_GRACE_DAYS)
    story.put(player, "mentor", {**st, "interest": round(interest, 2), "ticked_on": today.isoformat()})
    if _overall(player) >= world.display_overall(npc.overall) - M.GRADUATION_MARGIN:
        end(db, player, "graduated")
    elif interest <= 0:
        end(db, player, "lost_interest")
