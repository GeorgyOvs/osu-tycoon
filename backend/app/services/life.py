"""Life outside osu!: age, school/work, free time, money.

Free time caps how much you can play without paying for it in sleep. Income depends on what
you do (allowance, part-time job, salary; pros live off prizes, streams and sponsors), and
age shapes how fast you learn and how quick your reactions stay.
"""

from datetime import date, timedelta

from app.engine import simulation
from app.models import Player
from app.services import economy, media, story

OCCUPATIONS = ("school", "university", "work", "pro")
# (weekday, weekend) free hours.
FREE_HOURS = {"school": (5, 11), "university": (7, 11), "work": (4, 10), "pro": (14, 14)}
# Net of living costs: a job leaves ~$200 a week to spend on osu!; pros pay their own way.
WEEKLY_INCOME = {"school": 10, "university": 40, "work": 200, "pro": -150}
MAX_SLEEP_TRADE = 3  # hours you can steal from sleep
OVERTIME_FATIGUE, OVERTIME_FORM = 4.0, 0.1
SPONSOR_MONTHLY = [(10, 3000), (100, 800), (1000, 100)]


class LifeError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def age(player: Player, on: date | None = None) -> float | None:
    if player.birth_date is None:
        return None
    return ((on or player.in_game_date) - player.birth_date).days / 365.25


def _in_holidays(d: date) -> bool:
    return d.month in (7, 8) or (d.month == 12 and d.day >= 24) or (d.month == 1 and d.day <= 7)


def _in_exams(d: date) -> bool:
    return (d.month == 6 and d.day >= 10) or (d.month == 12 and 8 <= d.day < 24)


GENDER_PRONOUNS = {"male": "he/him", "female": "she/her", "nonbinary": "they/them", "unspecified": "they/them"}
CHILD_FREE_HOURS = (3, 6)  # under 12, parents decide how long the computer stays on


def pronouns(player: Player) -> str:
    return GENDER_PRONOUNS.get(player.gender, "they/them")


def free_hours(player: Player, d: date) -> float:
    weekday, weekend = FREE_HOURS[player.occupation]
    years = age(player, d)
    if years is not None and years < 12:
        weekday, weekend = CHILD_FREE_HOURS
    hours = float(weekend if d.weekday() >= 5 else weekday)
    if player.occupation in ("school", "university"):
        if _in_holidays(d):
            hours = max(hours, 11.0)
        elif _in_exams(d):
            hours = max(1.0, hours - 3)
    return max(0.0, hours + story.mod_sum(player, "free_hours", d))


def forced_rest(player: Player, d: date) -> str | None:
    """A life event (illness, family trip...) that rules out playing altogether on this day."""
    if story.mod_sum(player, "free_hours", d) <= -10:
        active = [m for m in story.mods(player, d) if m.get("free_hours", 0) <= -10]
        return active[0]["label_en"] if active else "resting"
    return None


def check_hours(player: Player, hours: float, days: int = 1) -> None:
    """Refuse plans that would need more than free time plus a few hours of sleep, on any day."""
    if hours <= 0:
        return
    if story.get(player, "retired"):
        raise LifeError(409, "this career is over")
    for i in range(days):
        d = player.in_game_date + timedelta(days=i)
        reason = forced_rest(player, d)
        if reason:
            raise LifeError(409, f"you can't play on {d}: {reason}")
        limit = free_hours(player, d) + MAX_SLEEP_TRADE
        if hours > limit + 1e-9:
            raise LifeError(422, f"on {d} you only have {free_hours(player, d):g}h of free time "
                                 f"(max {limit:g}h if you skip sleep)")


def learning_multiplier(player: Player) -> float:
    return _age_learning(player) * story.mod_product(player, "learning")


def _age_learning(player: Player) -> float:
    a = age(player)
    if a is None:
        return 1.0
    if a < 12:
        return 0.9
    if a <= 19:
        return 1.0 + 0.1 * (1 - abs(a - 16) / 4)  # teenage peak
    if a <= 24:
        return 1.0
    return max(0.6, 1.0 - 0.03 * (a - 24))


def reaction_multiplier(player: Player) -> float:
    a = age(player)
    return 1.0 if a is None or a <= 25 else max(0.8, 1 - 0.01 * (a - 25))


def default_occupation(years: float) -> str:
    return "school" if years < 18 else "university" if years < 22 else "work"


def apply_days(player: Player, start: date, end: date, hours_per_day: float) -> list[simulation.Event]:
    """Money, overtime, and life milestones for every day in [start, end)."""
    events: list[simulation.Event] = []
    d = start
    overtime_total = 0.0
    while d < end:
        overtime_total += max(0.0, hours_per_day - free_hours(player, d))
        if d.weekday() == 6:
            economy.weekly(player, d)
            player.followers = int(player.followers * 0.995)
        if d.day == 1:
            for limit, amount in SPONSOR_MONTHLY:
                if player.global_rank and player.global_rank <= limit:
                    from app.services import integrity

                    pay = round(amount * media.community_size(d) * integrity.sponsor_factor(player)
                                * story.mod_product(player, "income", d))
                    economy.earn(player, pay, "sponsor", d)
                    events.append(simulation.Event(d, "SPONSOR", f"Sponsorship deal pays ${pay:,} this month.", {}))
                    break
            if player.followers >= 1000:
                pay = round(player.followers * 0.02)
                economy.earn(player, pay, "stream", d)
                events.append(simulation.Event(d, "SPONSOR", f"Streaming sponsor pays ${pay:,} this month.", {}))
            from app.services import spending

            events += spending.charge_subscriptions(player, d)
            events += [simulation.Event(d, "BUDGET", line, {}) for line in economy.monthly(player, d)]
        events += _milestones(player, d)
        d += timedelta(days=1)
    if overtime_total:
        player.fatigue = min(100.0, player.fatigue + OVERTIME_FATIGUE * overtime_total)
        player.form = max(-2.5, player.form - OVERTIME_FORM * overtime_total)
        events.append(simulation.Event(end, "SLEEP_DEBT", f"Stayed up late: {overtime_total:g}h of sleep lost.",
                                       {"hours": overtime_total}))
    if economy.realistic(player) and player.money < 0 and player.occupation != "pro":
        player.motivation = max(0.0, player.motivation - 1)  # bills you can't pay weigh on you
    if player.occupation == "pro" and player.money < 0:
        player.motivation = max(0.0, player.motivation - 2)
        if player.money < -1000:
            player.occupation = "work"
            events.append(simulation.Event(end, "LIFE", "Broke: you had to take a job again.", {}))
    return events


def _milestones(player: Player, d: date) -> list[simulation.Event]:
    if player.birth_date is None or (d.month, d.day) != (player.birth_date.month, player.birth_date.day):
        return []
    years = round(age(player, d))
    out = [simulation.Event(d, "BIRTHDAY", f"Happy birthday! You're {years} now.", {"age": years})]
    if years == 18 and player.occupation == "school":
        player.occupation = "university"
        out.append(simulation.Event(d, "LIFE", "You finished school and started university.", {}))
    elif years == 22 and player.occupation == "university":
        player.occupation = "work"
        out.append(simulation.Event(d, "LIFE", "You graduated and got a full-time job.", {}))
    return out


def set_occupation(player: Player, occupation: str) -> None:
    if occupation not in OCCUPATIONS:
        raise LifeError(422, f"occupation must be one of {', '.join(OCCUPATIONS)}")
    years = age(player)
    if occupation == "pro" and years is not None and years < 16:
        raise LifeError(409, "too young to go full-time; finish school first")
    if occupation == "school" and years is not None and years >= 18:
        raise LifeError(409, "you've already finished school")
    player.occupation = occupation

