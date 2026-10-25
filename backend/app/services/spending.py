"""Spending: buying services, perks and subscriptions with their lasting effects.

State lives in Player.story_state: `owned` (list of keys), `subs` ({key: {since, last_charged, months}}), `spend_last`
({key: iso date of the last purchase}), `spend_stats` (counters for achievements). Perks are modifiers in the shared
store of services/story.py (tagged with `source`), so the simulation reads them like any other lasting effect.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import network, simulation
from app.engine import spending as S
from app.models import Player, Team, TeamMember, Tournament
from app.services import economy, events, media, setup, story, streaming

LAN_TIERS = ("open", "major", "owc")
LAN_WINDOW_DAYS = 45


class SpendingError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


# --- state ----------------------------------------------------------------------------------


def _owned(player: Player) -> list[str]:
    return list(story.get(player, "owned") or [])


def _subs(player: Player) -> dict:
    return dict(story.get(player, "subs") or {})


def _last(player: Player) -> dict:
    return dict(story.get(player, "spend_last") or {})


def _stats(player: Player) -> dict:
    return dict(story.get(player, "spend_stats") or {})


def _bump(player: Player, key: str, by: int = 1, maximum: bool = False) -> None:
    stats = _stats(player)
    stats[key] = max(stats.get(key, 0), by) if maximum else stats.get(key, 0) + by
    story.put(player, "spend_stats", stats)


def region(player: Player) -> str:
    return network.region(player.country)


def price(item: S.Item, player: Player) -> int:
    if item.handler == "isp":
        return round(setup.isp_price(player) or 0)
    return S.price_on(item, player.in_game_date, player.occupation, region(player))


def monthly_total(player: Player) -> int:
    return sum(price(S.BY_KEY[k], player) for k in _subs(player) if k in S.BY_KEY)


def _years(on: date) -> float:
    return on.year + (on.month - 1) / 12


def _team_ready(db: Session, player: Player) -> Team | None:
    team = db.scalar(select(Team).where(Team.player_id == player.id, Team.status == "active"))
    if team is None:
        return None
    mates = [m for m in team.members if m.left_on is None]
    return team if len(mates) >= 2 else None


def _lan_target(db: Session, player: Player) -> Tournament | None:
    today = player.in_game_date
    done = set(story.get(player, "lan_done") or [])
    rows = db.scalars(select(Tournament).where(
        Tournament.player_id == player.id, Tournament.user_registered.is_(True),
        Tournament.status.in_(("upcoming", "ongoing")), Tournament.tier.in_(LAN_TIERS)).order_by(Tournament.start_date))
    for t in rows:
        if t.id not in done and t.start_date <= today + timedelta(days=LAN_WINDOW_DAYS):
            return t
    return None


def _locked(db: Session, player: Player, item: S.Item) -> tuple[str, str] | None:
    """(en, ru) reason this can't be bought at all right now, or None."""
    on = player.in_game_date
    if _years(on) < item.from_year:
        year = int(item.from_year)
        return f"Not available before {year}", f"Недоступно до {year} года"
    age = None if player.birth_date is None else (on - player.birth_date).days / 365.25
    if age is not None and age < item.min_age:
        return f"From age {item.min_age:g}", f"С {item.min_age:g} лет"
    if item.min_followers and player.followers < item.min_followers:
        return f"Needs {item.min_followers} followers", f"Нужно {item.min_followers} подписчиков"
    if item.max_rank and (player.global_rank is None or player.global_rank > item.max_rank):
        return f"Needs a rank of #{item.max_rank:,} or better", f"Нужен ранг #{item.max_rank:,} или выше"
    for need in item.needs:
        if need == "team" and _team_ready(db, player) is None:
            return "Needs a team with two active teammates", "Нужна команда минимум с двумя активными товарищами"
        if need == "tournament" and _lan_target(db, player) is None:
            return ("Needs a registered Open, Major or World Cup within 45 days",
                    "Нужен турнир уровня Open, Major или World Cup в ближайшие 45 дней, куда вы записаны")
        if need == "tablet" and player.input_device != "tablet":
            return "For tablet players", "Для игроков на планшете"
        if need == "mouse" and player.input_device != "mouse":
            return "For mouse players", "Для игроков на мыши"
        if need == "streaming" and not streaming.available(on):
            return "Streaming doesn't exist yet", "Стримов ещё не существует"
    return None


def _active_mod(player: Player, key: str) -> dict | None:
    return next((m for m in story.mods(player) if m.get("source") == key), None)


def status(db: Session, player: Player, item: S.Item) -> dict:
    today = player.in_game_date
    out = {"status": "available", "reason_en": "", "reason_ru": "", "cooldown_left": 0}

    def block(code: str, en: str = "", ru: str = "") -> dict:
        out.update(status=code, reason_en=en, reason_ru=ru)
        return out

    if item.handler == "isp" and setup.isp_price(player) is None:
        return block("owned", "Your connection is as good as it gets", "Соединение уже лучше некуда")
    if item.kind == "owned" and item.key in _owned(player):
        return block("owned")
    if item.kind == "sub" and item.key in _subs(player):
        return block("subscribed")
    locked = _locked(db, player, item)
    if locked:
        return block("locked", *locked)
    if item.kind == "timed" and _active_mod(player, item.key):
        return block("active", "Its effect is still running", "Эффект ещё действует")
    last = _last(player).get(item.key)
    if item.cooldown and last:
        left = item.cooldown - (today - date.fromisoformat(last)).days
        if left > 0:
            out["cooldown_left"] = left
            return block("cooldown", f"Again in {left} d", f"Снова через {left} дн.")
    return out


# --- buying -----------------------------------------------------------------------------------


def _mod(item: S.Item, mods: dict, until: date | str, source: str, lang_names: tuple[str, str], start: date | None = None) -> dict:
    out = {"event_id": 0, "until": until if isinstance(until, str) else until.isoformat(), "free_hours": 0.0,
           "learning": 1.0, "play": 1.0, "label_en": lang_names[0], "label_ru": lang_names[1], "source": source, **mods}
    if start:
        out["from"] = start.isoformat()
    return out


def _resolve_choice(item: S.Item, choice: str | None) -> str | None:
    if item.choice != "group":
        return None
    if choice not in S.GROUPS:
        raise SpendingError(422, "choose a skill group: " + ", ".join(S.GROUPS))
    return choice


def buy(db: Session, player: Player, key: str, choice: str | None = None) -> dict:
    item = S.BY_KEY.get(key)
    if item is None:
        raise SpendingError(404, f"no such item '{key}'")
    st = status(db, player, item)
    if st["status"] != "available":
        raise SpendingError(409, st["reason_en"] or f"{item.name[0]} is {st['status']}")
    pick = _resolve_choice(item, choice)
    today = player.in_game_date
    cost = price(item, player)
    if player.money < cost:
        raise SpendingError(409, f"{item.name[0]} costs ${cost}; you have ${player.money:.0f}")

    # money
    if item.handler == "isp":
        setup.upgrade_isp(player)  # takes the money itself
        economy.record(player, "services", -cost, today)
    else:
        economy.spend(player, cost, "subscription" if item.kind == "sub" else "services", today)

    applied: dict = {}
    effects = dict(item.effects)
    if item.key == "replay_analysis":
        effects = {"skill": {pick: item.effects["skill"]}}
    if item.key == "coach_session":
        label_en = f"Coach: {S.GROUP_NAMES[pick][0]}"
        label_ru = f"Тренер: {S.GROUP_NAMES[pick][1]}"
    else:
        label_en, label_ru = item.name
    extra: dict = {}
    if item.handler:
        extra = _handle(db, player, item, effects, pick) or {}
    if effects:
        applied = events.apply_effects(db, player, effects, {}, 0)

    mods = {(f"learn_{pick}" if k == "learn_group" else k): v for k, v in item.mods.items()}
    if item.kind == "timed" and mods:
        story.add_mod(player, _mod(item, mods, today + timedelta(days=item.days), item.key, (label_en, label_ru)))
    elif item.kind == "sub":
        subs = _subs(player)
        subs[item.key] = {"since": today.isoformat(), "last_charged": today.strftime("%Y-%m"), "months": 1}
        story.put(player, "subs", subs)
        if mods:
            story.add_mod(player, _mod(item, mods, S.FOREVER, f"sub:{item.key}", item.name))
    elif item.kind == "owned":
        story.put(player, "owned", [*_owned(player), item.key])
        if mods:
            story.add_mod(player, _mod(item, mods, S.FOREVER, f"own:{item.key}", item.name))
    if item.cooldown:
        last = _last(player)
        last[item.key] = today.isoformat()
        story.put(player, "spend_last", last)
    if item.key in ("coach_session", "coach_retainer"):
        _bump(player, "coaching_sessions")
    if item.kind == "sub":
        _bump(player, "sub_months_max", 1, maximum=True)

    en, ru = S.text(item, "en")[0], S.text(item, "ru")[0]
    message = f"Bought: {en} (${cost})." + (f" {extra['note']}" if extra.get("note") else "")
    if cost >= 50:
        media.private_event(db, player, "PLAYER_SPENDING", {"item": en, "cost": cost, "choice": pick}, channel="#osu")
    db.flush()
    return {"key": key, "price": cost, "choice": pick, "applied": applied, "message": message,
            "message_ru": f"Куплено: {ru} (${cost}).", "extra": {k: v for k, v in extra.items() if k != "note"}}


def _handle(db: Session, player: Player, item: S.Item, effects: dict, pick: str | None) -> dict | None:
    """Special-case behaviour. May edit `effects`."""
    today = player.in_game_date
    h = item.handler
    if h == "massage":
        if player.injury == simulation.MINOR_STRAIN:
            player.injury, player.strain_recovery_days = simulation.HEALTHY, 0
            return {"note": "The minor strain is gone.", "healed": True}
    elif h == "vacation":
        story.add_mod(player, _mod(item, {"free_hours": -14.0}, today + timedelta(days=5), item.key, ("On vacation", "В отпуске")))
    elif h == "coffee":
        story.add_mod(player, _mod(item, {"play": 1.01}, today + timedelta(days=1), item.key, ("Caffeinated", "На кофеине")))
        tomorrow = today + timedelta(days=1)
        story.add_mod(player, _mod(item, {"play": 0.99, "recovery": 0.9}, today + timedelta(days=2), "crash",
                                   ("Caffeine crash", "Откат после кофеина"), start=tomorrow))
    elif h == "skates":
        cat = player.input_device if player.input_device in ("mouse", "tablet") else "mouse"
        state = setup.wear_state(player)
        state[cat] = round(max(0.0, state.get(cat, 0.0) - 0.25), 4)
        story.put(player, "wear", state)
    elif h == "switches":
        state = setup.wear_state(player)
        state["keyboard"] = round(max(0.0, state.get("keyboard", 0.0) - 0.5), 4)
        story.put(player, "wear", state)
    elif h == "comfort":
        story.put(player, "comfort", round(min(1.0, setup.comfort(player) + 0.12), 4))
    elif h == "contest":
        from app.services import integrity

        integrity.adjust_reputation(player, 1.5, "sponsored a mapping contest")
    elif h == "host":
        from app.services import integrity

        integrity.adjust_reputation(player, 4, "hosted a community tournament")
        title = f"{player.name} hosts the {player.name} Community Cup — registrations are open"
        media.emit(db, player, "COMMUNITY_TOURNAMENT_HOSTED", {"host": player.name}, kind="news", title=title, flair="News",
                   base_upvotes=120, tone="excited, grateful", fmt={"headline": title})
        _bump(player, "tournaments_hosted")
        return {"note": "A thread went up on the forum."}
    elif h == "lan":
        from app.services import integrity

        target = _lan_target(db, player)
        done = list(story.get(player, "lan_done") or [])
        if target is not None:
            done.append(target.id)
            story.put(player, "lan_done", done)
        integrity.adjust_reputation(player, 1, "travelled to a LAN")
        _bump(player, "lan_visits")
        return {"note": f"You are going to {target.name}." if target else "", "tournament_id": target.id if target else None}
    elif h == "bootcamp":
        team = _team_ready(db, player)
        if team is not None:
            team.chemistry = min(100.0, team.chemistry + 8)
            story.add_mod(player, _mod(item, {"free_hours": -6.0}, today + timedelta(days=2), item.key, ("Bootcamp", "Буткемп")))
            effects["fatigue"] = 8
            return {"note": f"Chemistry with {team.name} is now {team.chemistry:.0f}."}
    return None


def cancel(db: Session, player: Player, key: str) -> dict:
    subs = _subs(player)
    if key not in subs:
        raise SpendingError(404, "you are not subscribed to that")
    _end_sub(player, key)
    return {"key": key, "message": f"Cancelled: {S.BY_KEY[key].name[0]}.", "message_ru": f"Отменено: {S.BY_KEY[key].name[1]}."}


def _end_sub(player: Player, key: str) -> None:
    subs = _subs(player)
    subs.pop(key, None)
    story.put(player, "subs", subs)
    story.put(player, "mods", [m for m in (story.get(player, "mods") or []) if m.get("source") != f"sub:{key}"])


def charge_subscriptions(player: Player, on: date) -> list[simulation.Event]:
    """First of the month: every subscription is paid, or cancelled when the money isn't there."""
    out: list[simulation.Event] = []
    month = on.strftime("%Y-%m")
    for key, sub in list(_subs(player).items()):
        item = S.BY_KEY.get(key)
        if item is None:
            _end_sub(player, key)
            continue
        if sub.get("last_charged") == month:
            continue
        cost = S.price_on(item, on, player.occupation, region(player))
        if player.money < cost:
            _end_sub(player, key)
            out.append(simulation.Event(on, "SUBSCRIPTION", f"Couldn't pay for {item.name[0]}: the subscription was cancelled.",
                                        {"key": key}))
            continue
        economy.spend(player, cost, "subscription", on)
        subs = _subs(player)
        subs[key] = {**sub, "last_charged": month, "months": int(sub.get("months", 1)) + 1}
        story.put(player, "subs", subs)
        _bump(player, "sub_months_max", subs[key]["months"], maximum=True)
    return out


# --- presentation ---------------------------------------------------------------------------------


def _choices(item: S.Item, lang: str) -> list[dict]:
    if item.choice != "group":
        return []
    i = 1 if lang == "ru" else 0
    return [{"key": g, "label": S.GROUP_NAMES[g][i]} for g in S.GROUPS]


def overview(db: Session, player: Player, lang: str) -> dict:
    i = 1 if lang == "ru" else 0
    today = player.in_game_date
    categories = []
    for ckey, (cen, cru, icon) in S.CATEGORIES.items():
        cards = []
        for item in S.CATALOG:
            if item.category != ckey:
                continue
            st = status(db, player, item)
            if st["status"] == "locked" and _years(today) < item.from_year - 3:
                continue  # don't tease things that are far in the future
            name, desc, perk = S.text(item, lang)
            cost = price(item, player)
            cards.append({
                "key": item.key, "icon": item.icon, "kind": item.kind, "name": name, "description": desc, "perk": perk,
                "price": cost, "affordable": player.money >= cost, "status": st["status"],
                "reason": st["reason_ru" if i else "reason_en"], "cooldown_left": st["cooldown_left"], "days": item.days,
                "choices": _choices(item, lang),
            })
        categories.append({"key": ckey, "name": (cen, cru)[i], "icon": icon, "items": cards})
    subs = [{"key": k, "name": S.BY_KEY[k].name[i], "price": price(S.BY_KEY[k], player), "since": v["since"],
             "months": v.get("months", 1)} for k, v in _subs(player).items() if k in S.BY_KEY]
    label = "label_ru" if i else "label_en"
    active = [{"label": m[label], "days_left": (date.fromisoformat(m["until"]) - today).days, "source": m["source"]}
              for m in story.mods(player) if m.get("source") in S.BY_KEY or m.get("source") == "crash"]
    return {"money": round(player.money), "categories": categories, "subscriptions": subs,
            "monthly_total": sum(s["price"] for s in subs), "effects": active, "owned": _owned(player)}
