"""Achievements: medal-like milestones, bilingual (en/ru), checked against a plain Snapshot of the career.

Most are families of thresholds ("Top 1,000", "Top 100"...); each has a rarity that feeds the legacy score.
Nothing here touches the database.
"""

import math
from dataclasses import dataclass

RARITY_POINTS = {"common": 1, "uncommon": 3, "rare": 8, "epic": 20, "legendary": 50}


@dataclass
class Snapshot:
    best_rank: int | None = None
    peak_pp: float = 0.0
    best_acc: float = 0.0
    play_count: int = 0
    followers_max: int = 0
    peak_money: float = 0.0
    years: float = 0.0
    best_streak: int = 0
    badges: int = 0
    tournament_wins: int = 0
    match_wins: int = 0
    injuries_survived: int = 0
    comebacks: int = 0
    rivals: int = 0
    goals_done: int = 0
    events_resolved: int = 0
    overall_max: float = 0.0
    top_sub_max: float = 0.0
    team_chemistry_max: float = 0.0
    teams_joined: int = 0
    loans_repaid: int = 0
    coaching_sessions: int = 0
    sub_months_max: int = 0
    tournaments_hosted: int = 0
    lan_visits: int = 0


@dataclass(frozen=True)
class Achievement:
    key: str
    category: str
    rarity: str
    name: tuple[str, str]
    desc: tuple[str, str]
    field: str
    target: float
    lower_is_better: bool = False

    def value(self, snap: Snapshot):
        return getattr(snap, self.field)

    def unlocked(self, snap: Snapshot) -> bool:
        v = self.value(snap)
        if v is None:
            return False
        return v <= self.target if self.lower_is_better else v >= self.target

    def progress(self, snap: Snapshot) -> float:
        v = self.value(snap)
        if self.lower_is_better:
            if not v:
                return 0.0
            if v <= self.target:
                return 1.0
            return max(0.0, min(0.99, math.log(1_000_000 / v) / math.log(1_000_000 / max(self.target, 1))))
        if not v:
            return 0.0
        return max(0.0, min(1.0, v / self.target))


def _n(x: float) -> str:
    return f"{int(x):,}" if float(x).is_integer() else f"{x:g}"


def _family(category, field_, targets, name, desc, lower=False) -> list[Achievement]:
    """name/desc are ((en, ru) template) pairs with {n}; targets are (value, rarity)."""
    out = []
    for target, rarity in targets:
        n = _n(target)
        out.append(Achievement(
            key=f"{field_}_{int(target) if float(target).is_integer() else target}", category=category, rarity=rarity,
            name=(name[0].format(n=n), name[1].format(n=n)), desc=(desc[0].format(n=n), desc[1].format(n=n)),
            field=field_, target=target, lower_is_better=lower,
        ))
    return out


CATALOG: tuple[Achievement, ...] = tuple(
    _family("rank", "best_rank", [(100_000, "common"), (50_000, "common"), (10_000, "uncommon"), (5_000, "uncommon"),
                                  (1_000, "rare"), (500, "rare"), (100, "epic"), (50, "epic"), (10, "legendary"),
                                  (1, "legendary")],
            ("Top {n}", "Топ-{n}"), ("Reach global rank #{n} or better.", "Достичь мирового места #{n} или выше."), True)
    + _family("pp", "peak_pp", [(1_000, "common"), (2_500, "uncommon"), (5_000, "rare"), (7_500, "rare"),
                                (10_000, "epic"), (15_000, "legendary")],
              ("{n}pp", "{n}pp"), ("Reach {n} total performance points.", "Набрать {n} суммарных pp."))
    + _family("accuracy", "best_acc", [(95, "common"), (97, "uncommon"), (98.5, "rare")],
              ("{n}% accuracy", "Точность {n}%"), ("Hold {n}% overall accuracy.", "Держать общую точность {n}%."))
    + _family("plays", "play_count", [(1, "common"), (25, "common"), (100, "uncommon"), (500, "rare"), (2_000, "epic")],
              ("{n} plays", "Плеев: {n}"), ("Set {n} scores.", "Набрать {n} скоров."))
    + _family("streak", "best_streak", [(7, "common"), (30, "uncommon"), (100, "rare")],
              ("{n}-day streak", "Серия {n} дней"), ("Train {n} days in a row.", "Тренироваться {n} дней подряд."))
    + _family("tournament", "match_wins", [(1, "common"), (10, "uncommon"), (50, "rare")],
              ("{n} match wins", "Побед в матчах: {n}"), ("Win {n} tournament matches.", "Выиграть матчей на турнирах: {n}."))
    + _family("tournament", "tournament_wins", [(1, "rare"), (3, "epic")],
              ("{n} tournament titles", "Титулов: {n}"), ("Win {n} tournaments.", "Выиграть турниров: {n}."))
    + _family("tournament", "badges", [(1, "epic")],
              ("Badge holder", "Обладатель бейджа"), ("Win a badge-awarding tournament.", "Выиграть турнир с бейджем."))
    + _family("rivalry", "rivals", [(1, "common"), (3, "uncommon")],
              ("{n} rival(s)", "Соперников: {n}"), ("Make {n} rival(s) who take it personally.",
                                                    "Нажить соперников, которые воспринимают всё лично: {n}."))
    + _family("health", "injuries_survived", [(1, "uncommon")],
              ("Survived tendonitis", "Пережил тендинит"), ("Come back from a severe injury.", "Вернуться после тяжёлой травмы."))
    + _family("health", "comebacks", [(1, "rare")],
              ("The comeback", "Возвращение"), ("Finish a Comeback storyline.", "Завершить сюжет «Возвращение»."))
    + _family("longevity", "years", [(1, "common"), (3, "uncommon"), (5, "rare"), (10, "epic")],
              ("{n} years in", "{n} лет в игре"), ("Stay active for {n} in-game years.",
                                                   "Играть {n} внутриигровых лет."))
    + _family("streaming", "followers_max", [(100, "common"), (1_000, "uncommon"), (10_000, "epic")],
              ("{n} followers", "{n} подписчиков"), ("Reach {n} followers.", "Набрать {n} подписчиков."))
    + _family("team", "team_chemistry_max", [(70, "uncommon")],
              ("Tight squad", "Сработанная команда"), ("Reach {n} team chemistry.", "Довести химию команды до {n}."))
    + _family("team", "teams_joined", [(1, "common")],
              ("Team player", "Командный игрок"), ("Join a team.", "Вступить в команду."))
    + _family("economy", "peak_money", [(1_000, "common"), (10_000, "uncommon"), (100_000, "epic")],
              ("${n} saved", "Накоплено ${n}"), ("Hold ${n} at once.", "Иметь на счету ${n}."))
    + _family("economy", "loans_repaid", [(1, "common")],
              ("Debt free", "Без долгов"), ("Pay off a loan in full.", "Полностью погасить кредит."))
    + _family("economy", "coaching_sessions", [(1, "common")],
              ("Taking coaching", "Под присмотром тренера"), ("Pay for a coaching session.", "Оплатить занятие с тренером."))
    + _family("economy", "sub_months_max", [(12, "uncommon")],
              ("A year of routine", "Год стабильности"), ("Keep one subscription for {n} months.", "Держать одну подписку {n} месяцев."))
    + _family("community", "tournaments_hosted", [(1, "rare")],
              ("Organiser", "Организатор"), ("Host a community tournament.", "Организовать комьюнити-турнир."))
    + _family("community", "lan_visits", [(1, "uncommon")],
              ("On the road", "В дороге"), ("Travel to a LAN final.", "Поехать на оффлайн-финал."))
    + _family("story", "goals_done", [(1, "common"), (10, "uncommon"), (25, "rare")],
              ("{n} goals met", "Целей достигнуто: {n}"), ("Complete {n} goals.", "Выполнить целей: {n}."))
    + _family("story", "events_resolved", [(10, "common"), (50, "uncommon")],
              ("{n} life decisions", "Решений в жизни: {n}"), ("Decide {n} life events.", "Принять решений по событиям: {n}."))
    + _family("skill", "overall_max", [(50, "common"), (75, "rare"), (90, "epic")],
              ("Overall {n}", "Общий уровень {n}"), ("Reach an overall skill of {n}.", "Достичь общего уровня {n}."))
    + _family("skill", "top_sub_max", [(90, "epic")],
              ("Master of one", "Мастер одного"), ("Raise a single skill to {n}.", "Прокачать один навык до {n}."))
)
BY_KEY = {a.key: a for a in CATALOG}
assert len(BY_KEY) == len(CATALOG)

CATEGORY_LABELS = {
    "rank": ("Ranks", "Ранги"), "pp": ("Performance", "Производительность"), "accuracy": ("Accuracy", "Точность"),
    "plays": ("Plays", "Плеи"), "streak": ("Streaks", "Серии"), "tournament": ("Tournaments", "Турниры"),
    "rivalry": ("Rivalries", "Соперничества"), "health": ("Health", "Здоровье"), "longevity": ("Longevity", "Стаж"),
    "streaming": ("Streaming", "Стриминг"), "team": ("Teams", "Команды"), "economy": ("Economy", "Экономика"),
    "story": ("Story", "Сюжет"), "skill": ("Skills", "Навыки"), "community": ("Community", "Сообщество"),
}


def legacy_score(unlocked: list[str], best_rank: int | None, peak_pp: float) -> int:
    """One number for the whole career: achievements by rarity plus how high the player climbed."""
    points = sum(RARITY_POINTS[BY_KEY[k].rarity] for k in unlocked if k in BY_KEY)
    if best_rank:
        points += max(0, round(10 * math.log10(1_000_000 / best_rank)))
    return points + round(peak_pp / 250)


def present(a: Achievement, lang: str) -> dict:
    i = 1 if lang == "ru" else 0
    return {"key": a.key, "category": a.category, "rarity": a.rarity, "name": a.name[i], "description": a.desc[i]}


RARITIES = tuple(RARITY_POINTS)
