"""Life events: rolling them as days pass, presenting the choice, and applying the consequences.

Events never block the calendar. A pending event waits a few days; if the player doesn't decide, the
default option happens (usually the passive or the careless one), so neglect has a cost too.
"""

import random
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import life_events as LE
from app.engine import simulation
from app.engine.training import era_for
from app.models import LifeEvent, Npc, Player
from app.services import economy, integrity, life, media, rivals, setup, story, streaming

MONEY_SCALE = {"school": 1.0, "university": 1.5, "work": 3.0, "pro": 3.0}
STUCK_PLATEAU = 25.0


class EventError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


# --- rolling ------------------------------------------------------------------------------------


def _ctx(db: Session, player: Player, on: date) -> tuple[LE.Ctx, dict]:
    values = simulation.effective_values(player)
    rival = next(iter(rivals.active(db, player)), None)
    rival_npc = db.get(Npc, rival.npc_id) if rival else None
    wall = max(player.attributes, key=lambda a: a.plateau)
    stuck = wall.key if wall.plateau >= STUCK_PLATEAU and wall.base < wall.cap - 5 and values[wall.key] < 90 else None
    age = life.age(player, on)
    ctx = LE.Ctx(
        on=on, age=age, occupation=player.occupation, rank=player.global_rank, money=player.money,
        followers=player.followers, fatigue=player.fatigue, motivation=player.motivation, injury=player.injury,
        era=era_for(on).value, year=on.year, month=on.month, device=player.input_device,
        rival=rival_npc.name if rival_npc else None, in_exams=life._in_exams(on), in_holidays=life._in_holidays(on),
        birthday=bool(player.birth_date and (on.month, on.day) == (player.birth_date.month, player.birth_date.day)),
        stuck=stuck, streaming=streaming.available(on),
        wear=setup.worst_wear(player), reputation=integrity.reputation(player),
    )
    data = {"rival": rival_npc.name if rival_npc else "", "rival_id": rival_npc.id if rival_npc else None,
            "stuck_key": stuck, "device_key": player.input_device}
    return ctx, data


def pending_count(db: Session, player: Player) -> int:
    return db.scalar(select(func.count()).select_from(LifeEvent)
                     .where(LifeEvent.player_id == player.id, LifeEvent.status == "pending")) or 0


def tick(db: Session, player: Player, news: list) -> None:
    target = player.in_game_date
    start = story.get_date(player, "events_rolled_through", target)
    story.prune_mods(player, target)
    if start < target:
        ctx, data = _ctx(db, player, target)
        last_fired = dict(story.get(player, "event_last", {}))
        pending = pending_count(db, player)
        day = start
        while day < target:
            day += timedelta(days=1)
            rng = random.Random(f"{player.seed}:events:{day.isoformat()}")
            if pending >= LE.MAX_PENDING:
                continue
            on_ctx = _on(ctx, day, player)
            options = LE.eligible(on_ctx, last_fired, day, set())
            if not options:
                continue
            guaranteed = [t for t in options if t.guaranteed]
            if guaranteed:
                template = guaranteed[0]
            elif rng.random() < LE.DAILY_CHANCE:
                template = rng.choices(options, weights=[t.weight for t in options])[0]
            else:
                continue
            _create(db, player, template, day, data)
            last_fired[template.key] = day.isoformat()
            pending += 1
        story.put(player, "event_last", last_fired)
        story.put_date(player, "events_rolled_through", target)
    _expire(db, player, target)


def _on(ctx: LE.Ctx, day: date, player: Player) -> LE.Ctx:
    from dataclasses import replace

    return replace(
        ctx, on=day, year=day.year, month=day.month, age=life.age(player, day), era=era_for(day).value,
        in_exams=life._in_exams(day), in_holidays=life._in_holidays(day), streaming=streaming.available(day),
        birthday=bool(player.birth_date and (day.month, day.day) == (player.birth_date.month, player.birth_date.day)),
    )


def _text_data(data: dict, lang: str) -> dict:
    i = 1 if lang == "ru" else 0
    out = dict(data)
    if data.get("stuck_key"):
        out["stuck"] = LE.STAT_RU[data["stuck_key"]] if i else A.SUBSTATS[data["stuck_key"]].label
    device = LE.DEVICE_NAMES.get(data.get("device_key", "mouse"), ("mouse", "мышь"))
    out["device"] = device[i]
    return out


def _create(db: Session, player: Player, template: LE.Template, day: date, data: dict) -> LifeEvent:
    en = LE.render(template, _text_data(data, "en"), "en")
    event = LifeEvent(
        player_id=player.id, key=template.key, category=template.category, title=en["title"][:160],
        body=en["body"][:1200], created_on=day, expires_on=day + timedelta(days=template.ttl), status="pending",
        options=en["options"], data=dict(data),
    )
    db.add(event)
    db.flush()
    return event


def _expire(db: Session, player: Player, today: date) -> None:
    due = db.scalars(select(LifeEvent).where(
        LifeEvent.player_id == player.id, LifeEvent.status == "pending", LifeEvent.expires_on <= today))
    for event in list(due):
        template = LE.BY_KEY.get(event.key)
        if template is None:
            event.status = "expired"
            continue
        resolve(db, player, event, template.default, auto=True)


# --- resolving ----------------------------------------------------------------------------------


def resolve(db: Session, player: Player, event: LifeEvent, choice: str, auto: bool = False) -> LifeEvent:
    template = LE.BY_KEY.get(event.key)
    if template is None:
        raise EventError(404, f"unknown event '{event.key}'")
    if event.status != "pending":
        raise EventError(409, "this event is already settled")
    option = next((o for o in template.options if o.key == choice), None)
    if option is None:
        raise EventError(422, f"no such option '{choice}'")

    rng = random.Random(f"{player.seed}:evres:{event.id}")
    idx = rng.choices(range(len(option.outcomes)), weights=[o.weight for o in option.outcomes])[0]
    outcome = option.outcomes[idx]
    applied = apply_effects(db, player, outcome.effects, event.data, event.id)
    if auto and (player.character_build or {}).get("hardcore"):
        player.motivation = max(0.0, player.motivation - 3)  # hardcore: hesitating costs you
        player.morale = max(0.0, player.morale - 2)

    event.status = "expired" if auto else "resolved"
    event.choice = option.key
    event.data = {**event.data, "outcome_idx": idx, "applied": applied, "auto": auto}
    event.outcome = outcome.en
    mod = applied.get("mod")
    if mod:
        event.modifiers = mod
        event.active_until = date.fromisoformat(mod["until"])

    media.private_event(db, player, "LIFE_EVENT", {
        "event": template.key, "category": template.category, "situation": event.body,
        "choice": option.en, "outcome": outcome.en, "decided_in_time": not auto,
    }, channel="#osu")
    if outcome.effects.get("post"):
        _post(db, player, outcome, outcome.effects["post"])
    db.flush()
    return event


def _post(db: Session, player: Player, outcome: LE.Out, kind: str) -> None:
    title = f"{player.name} [{player.country}]: {outcome.en}"
    media.emit(db, player, "LIFE_EVENT_POST", {"outcome": outcome.en}, kind=kind, title=title,
               flair="Drama" if kind == "drama" else "News", base_upvotes=60 if kind == "drama" else 90,
               tone="gossip, split opinions" if kind == "drama" else "excited",
               fmt={"headline": title, "player": player.name})


def apply_effects(db: Session, player: Player, effects: dict, data: dict, source_id: int = 0) -> dict:
    """Apply an outcome to the player. Returns what actually changed, for the UI."""
    applied: dict = {}
    clamp = lambda v: max(0.0, min(100.0, v))  # noqa: E731

    for key in ("motivation", "morale", "fatigue"):
        if key in effects:
            old = getattr(player, key)
            setattr(player, key, clamp(old + effects[key]))
            applied[key] = round(getattr(player, key) - old, 1)
    if "form" in effects:
        player.form = max(-2.5, min(2.5, player.form + effects["form"]))
        applied["form"] = effects["form"]
    if "money" in effects:
        amount = round(effects["money"] * MONEY_SCALE.get(player.occupation, 1.0))
        player.money += amount
        economy.record(player, "event" if amount > 0 else "event_cost", amount, player.in_game_date)
        applied["money"] = amount
    if "followers" in effects:
        before = player.followers
        player.followers = max(0, player.followers + effects["followers"])
        applied["followers"] = player.followers - before

    if "reputation" in effects:
        applied["reputation"] = round(integrity.adjust_reputation(player, effects["reputation"], "life event"), 1)
    if "wear" in effects:
        before = setup.worst_wear(player)
        setup.adjust_wear(player, effects["wear"])
        applied["wear"] = round(setup.worst_wear(player) - before, 3)
    if effects.get("skill"):
        gains = _skill_gains(player, effects["skill"], data.get("stuck_key"))
        if gains:
            applied["skill"] = gains
    if effects.get("rival_heat") and data.get("rival_id"):
        rival = rivals.rival_for(db, player, data["rival_id"])
        if rival:
            rivals.bump(rival, effects["rival_heat"])
            applied["rival_heat"] = effects["rival_heat"]
    if effects.get("injury") == simulation.MINOR_STRAIN and player.injury == simulation.HEALTHY:
        player.injury = simulation.MINOR_STRAIN
        player.strain_recovery_days = 0
        applied["injury"] = simulation.MINOR_STRAIN
    if effects.get("mod"):
        m = effects["mod"]
        en_data = _text_data(data, "en")
        ru = _text_data(data, "ru")
        mod = {"event_id": source_id, "until": (player.in_game_date + timedelta(days=m["days"])).isoformat(),
               "free_hours": m["free_hours"], "learning": m["learning"], "play": m["play"],
               "label_en": m["label_en"].format(**en_data), "label_ru": m["label_ru"].format(**ru)}
        story.add_mod(player, mod)
        applied["mod"] = mod
    return applied


def _skill_gains(player: Player, skill: dict, stuck_key: str | None) -> dict[str, float]:
    gains: dict[str, float] = {}
    by_key = {a.key: a for a in player.attributes}
    for target, gain in skill.items():
        if target == "$stuck":
            target = stuck_key or ""
        keys = [target] if target in by_key else [s.key for s in A.GROUPS_BY_KEY[target].subs] if target in A.GROUPS_BY_KEY else []
        for key in keys:
            attr = by_key[key]
            new = min(attr.cap, attr.base + gain)
            if new > attr.base:
                gains[key] = round(new - attr.base, 2)
                attr.base = new
    return gains


# --- presentation -------------------------------------------------------------------------------


def present(event: LifeEvent, lang: str) -> dict:
    template = LE.BY_KEY.get(event.key)
    i = 1 if lang == "ru" else 0
    if template is None:
        return {"id": event.id, "key": event.key, "category": event.category, "title": event.title, "body": event.body,
                "created_on": event.created_on, "expires_on": event.expires_on, "status": event.status,
                "options": event.options, "choice": event.choice, "outcome": event.outcome, "applied": {}, "auto": False,
                "default": ""}
    text = LE.render(template, _text_data(event.data, lang), lang)
    outcome = ""
    if event.choice:
        option = next(o for o in template.options if o.key == event.choice)
        out = option.outcomes[min(event.data.get("outcome_idx", 0), len(option.outcomes) - 1)]
        outcome = out.ru if i else out.en
    applied = dict(event.data.get("applied", {}))
    if applied.get("mod"):
        applied["mod"] = {**applied["mod"], "label": applied["mod"]["label_ru" if i else "label_en"]}
    return {
        "id": event.id, "key": event.key, "category": event.category, "title": text["title"], "body": text["body"],
        "created_on": event.created_on, "expires_on": event.expires_on, "status": event.status,
        "options": text["options"], "choice": event.choice, "outcome": outcome, "applied": applied,
        "auto": bool(event.data.get("auto")), "default": template.default,
    }


def active_effects(player: Player, lang: str) -> list[dict]:
    today = player.in_game_date
    label = "label_ru" if lang == "ru" else "label_en"
    return [{"label": m[label], "until": m["until"], "days_left": (date.fromisoformat(m["until"]) - today).days,
             "free_hours": m.get("free_hours", 0.0), "learning": m.get("learning", 1.0), "play": m.get("play", 1.0)}
            for m in story.mods(player, today) if not str(m.get("source", "")).startswith(("sub:", "own:"))]


def history(db: Session, player: Player, limit: int = 40) -> list[LifeEvent]:
    return list(db.scalars(select(LifeEvent).where(LifeEvent.player_id == player.id)
                           .order_by(LifeEvent.created_on.desc(), LifeEvent.id.desc()).limit(limit)))
