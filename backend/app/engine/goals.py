"""Goals and story arcs: what the player is working towards, and the narrative the career is in.

Goals are measurable targets proposed from the player's situation (three active at a time). Arcs are
detected from the rank history and injuries; each collects dated chapters and closes with a short
epilogue. All text is bilingual (en/ru) and rendered at read time from keys + data.
"""

import math
import random
from dataclasses import dataclass, field

RANK_STEPS = [500_000, 250_000, 100_000, 50_000, 25_000, 10_000, 5_000, 2_500, 1_000, 500, 250, 100, 50, 25, 10, 5, 1]
GROUP_RU = {"aim": "Аим", "tapping": "Тэппинг", "reading": "Ридинг", "technical": "Техника",
            "mentality": "Психология", "physical": "Физика"}
GROUP_EN = {"aim": "Aim", "tapping": "Tapping", "reading": "Reading", "technical": "Technical",
            "mentality": "Mentality", "physical": "Physical"}

# key -> ((title en, title ru), (description en, description ru)); {target}, {group}, {item}, {rival}, {n}
TEXT: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "first_plays": (("Play your first {n} maps", "Сыграть первые {n} карт"),
                    ("Submit {n} scores to get on the ranking.", "Наберите {n} скоров, чтобы попасть в рейтинг.")),
    "rank": (("Break into the top {target}", "Войти в топ-{target}"),
             ("Reach global rank #{target} or better.", "Достичь мирового места #{target} или выше.")),
    "pp": (("Reach {target}pp", "Набрать {target}pp"),
           ("Get your total performance to {target}pp.", "Довести суммарные pp до {target}.")),
    "group": (("Raise {group} to {target}", "Прокачать «{group}» до {target}"),
              ("Bring the {group} composite up to {target}.", "Поднять композит «{group}» до {target}.")),
    "streak": (("Train {target} days in a row", "Тренироваться {target} дней подряд"),
               ("Build a routine: {target} straight days of practice, without burning out.",
                "Выработать режим: {target} дней практики подряд и без выгорания.")),
    "match_wins": (("Win {target} tournament matches", "Выиграть матчей на турнирах: {target}"),
                   ("Win matches in tournaments you enter.", "Побеждайте в матчах турниров, куда регистрируетесь.")),
    "overtake_rival": (("Overtake {rival}", "Обогнать {rival}"),
                       ("Climb above {rival} in the global ranking.", "Подняться в мировом рейтинге выше {rival}.")),
    "buy_gear": (("Get the {item}", "Купить: {item}"),
                 ("Save up and upgrade your setup.", "Накопить денег и улучшить сетап.")),
    "followers": (("Reach {target} followers", "Набрать {target} подписчиков"),
                  ("Grow your audience to {target} followers.", "Вырастить аудиторию до {target} подписчиков.")),
}

ARC_TEXT: dict[str, tuple[str, str]] = {
    "comeback": ("The comeback", "Возвращение"),
    "breakout": ("Breakout season", "Прорывной сезон"),
    "wall": ("Hitting the wall", "Стена"),
    "rivalry": ("A rivalry with {rival}", "Соперничество с {rival}"),
}
CHAPTER_TEXT: dict[str, tuple[str, str]] = {
    "comeback_start": ("A severe wrist injury forces a long hiatus. The future is uncertain.",
                       "Тяжёлая травма запястья вынуждает надолго уйти из игры. Будущее неясно."),
    "comeback_return": ("Back at the keyboard after the hiatus, cautious and hungry.",
                        "Возвращение за клавиатуру после перерыва: осторожно и с голодом."),
    "comeback_end": ("The ranking is regained: the comeback is complete.", "Рейтинг восстановлен: возвращение состоялось."),
    "comeback_fade": ("The road back was long; the player moves on.", "Путь назад вышел долгим, но игрок идёт дальше."),
    "breakout_start": ("The rank is climbing fast: #{rank}.", "Ранг быстро растёт: #{rank}."),
    "breakout_step": ("Another step up: #{rank}.", "Ещё шаг вверх: #{rank}."),
    "breakout_end": ("The surge settles at #{rank}.", "Рывок заканчивается на #{rank}."),
    "wall_start": ("Months of work and the rank barely moves (#{rank}).", "Месяцы работы, а ранг почти не движется (#{rank})."),
    "wall_break": ("The wall breaks: #{rank}!", "Стена пала: #{rank}!"),
    "wall_fade": ("The plateau fades into the background as other things take over.",
                  "Плато уходит на задний план: появились другие заботы."),
    "rivalry_start": ("{rival} and you keep ending up next to each other. It is getting personal.",
                      "Вы с {rival} постоянно оказываетесь рядом. Это становится личным."),
    "rivalry_end": ("The rivalry cools as your paths diverge.", "Соперничество остывает: ваши пути расходятся."),
}


@dataclass
class GoalCtx:
    on: object
    rank: int | None
    total_pp: float
    pp_era: bool
    composites: dict[str, float]
    followers: int
    money: float
    play_count: int
    streaming: bool
    consecutive_days: int
    rival_name: str | None
    rival_rank: int | None
    item: tuple[str, str, float] | None  # (key, name, price) of a sensible upgrade
    user_in_tournaments: bool
    active_keys: set[str] = field(default_factory=set)
    recently_done: set[str] = field(default_factory=set)


@dataclass
class Spec:
    key: str
    target: dict
    deadline_days: int
    reward: dict
    data: dict = field(default_factory=dict)


def next_rank_target(rank: int) -> int:
    candidates = [s for s in RANK_STEPS if s < rank * 0.75]
    return candidates[0] if candidates else 1


def next_pp_target(pp: float) -> int:
    for step in (500, 1000, 1500, 2000, 3000, 4000, 5000, 6000, 8000, 10000, 12000, 15000, 20000):
        if step > pp * 1.15:
            return step
    return int(pp * 1.3 // 1000 * 1000)


def next_group_target(value: float) -> int:
    target = (value // 5 + 1) * 5
    if target - value < 2:
        target += 5
    return int(min(99, target))


def prestige(rank: int | None) -> float:
    """0 (bottom of the ladder) .. 1 (the very top); scales rewards."""
    if not rank:
        return 0.0
    return max(0.0, min(1.0, 1 - math.log10(max(rank, 1)) / 6))


def reward_for(ctx: GoalCtx, size: float) -> dict:
    p = prestige(ctx.rank)
    reward = {"money": round((20 + 160 * p) * size), "motivation": round(6 + 6 * size), "morale": 3}
    if ctx.streaming and ctx.followers >= 50:
        reward["followers"] = round((10 + 60 * p) * size)
    if size >= 1.5:
        reward["mod"] = {"days": 14, "free_hours": 0.0, "learning": 1.1, "play": 1.0,
                         "label_en": "Inspired by a big goal", "label_ru": "Вдохновение от большой цели"}
    return reward


def propose(ctx: GoalCtx, rng: random.Random) -> Spec | None:
    """One new goal that fits the situation, or None when nothing sensible is left."""
    options: list[tuple[float, Spec]] = []

    def add(weight: float, spec: Spec) -> None:
        if spec.key not in ctx.active_keys and spec.key not in ctx.recently_done:
            options.append((weight, spec))

    if ctx.play_count < 10:
        n = 3 if ctx.play_count < 3 else 10
        add(4.0 if ctx.play_count < 3 else 1.5,
            Spec("first_plays", {"metric": "plays", "value": ctx.play_count + n, "start": ctx.play_count},
                 45, reward_for(ctx, 0.5), {"n": n}))
    if ctx.rank:
        target = next_rank_target(ctx.rank)
        size = 1.0 + (1.0 if target <= 1000 else 0.0) + (1.0 if target <= 100 else 0.0)
        add(3.0, Spec("rank", {"metric": "rank", "value": target, "start": ctx.rank},
                      150 + int(60 * size), reward_for(ctx, size)))
    if ctx.pp_era and ctx.total_pp > 0:
        target = next_pp_target(ctx.total_pp)
        add(2.0, Spec("pp", {"metric": "pp", "value": target, "start": round(ctx.total_pp)}, 180, reward_for(ctx, 1.0)))
    weakest = min(ctx.composites, key=lambda g: ctx.composites[g] - (0 if g != "physical" else 8))
    focus = rng.choice([weakest, max(ctx.composites, key=ctx.composites.get)])
    value = ctx.composites[focus]
    if value < 90:
        add(2.0, Spec("group", {"metric": "group", "group": focus, "value": next_group_target(value),
                                "start": round(value, 1)}, 150, reward_for(ctx, 0.8), {"group": focus}))
    if ctx.consecutive_days < 7:
        add(1.0, Spec("streak", {"metric": "streak", "value": 7}, 45, reward_for(ctx, 0.4)))
    if ctx.user_in_tournaments:
        add(2.5, Spec("match_wins", {"metric": "match_wins", "value": 2}, 120, reward_for(ctx, 1.2)))
    if ctx.rival_name and ctx.rival_rank and ctx.rank and ctx.rival_rank < ctx.rank:
        add(3.0, Spec("overtake_rival", {"metric": "overtake", "value": ctx.rival_rank, "start": ctx.rank},
                      120, reward_for(ctx, 1.3), {"rival": ctx.rival_name}))
    if ctx.item and ctx.money < ctx.item[2] * 3:
        add(2.0, Spec("buy_gear", {"metric": "gear", "item": ctx.item[0], "price": ctx.item[2]}, 120,
                      reward_for(ctx, 0.5), {"item": ctx.item[1]}))
    if ctx.streaming and ctx.followers >= 10:
        for step in (100, 250, 500, 1000, 2500, 5000, 10000, 25000):
            if step > ctx.followers * 1.3:
                add(1.2, Spec("followers", {"metric": "followers", "value": step, "start": ctx.followers},
                              150, reward_for(ctx, 0.7)))
                break
    if not options:
        return None
    return rng.choices([s for _, s in options], weights=[w for w, _ in options])[0]


def progress(spec_target: dict, *, rank: int | None, total_pp: float, composites: dict[str, float],
             followers: int, money: float, play_count: int, consecutive_days: int, best_streak: int,
             match_wins: int, owns_item: bool, rival_rank: int | None) -> float:
    """Progress 0..1 for a goal's target given the current state."""
    metric = spec_target["metric"]
    value, start = spec_target.get("value"), spec_target.get("start", 0)
    if metric == "rank":
        if not rank:
            return 0.0
        if rank <= value:
            return 1.0
        return max(0.0, min(0.99, math.log(start / rank) / math.log(start / value))) if start > value else 0.0
    if metric == "overtake":
        if not rank:
            return 0.0
        if rank < (rival_rank or value):
            return 1.0
        return max(0.0, min(0.99, math.log(start / rank) / math.log(start / max(value, 1)))) if start > value else 0.0
    if metric == "pp":
        return max(0.0, min(1.0, (total_pp - start) / max(value - start, 1)))
    if metric == "group":
        return max(0.0, min(1.0, (composites.get(spec_target["group"], 0) - start) / max(value - start, 0.5)))
    if metric == "plays":
        return max(0.0, min(1.0, (play_count - start) / max(value - start, 1)))
    if metric == "streak":
        return max(0.0, min(1.0, max(consecutive_days, best_streak) / value))
    if metric == "match_wins":
        return max(0.0, min(1.0, match_wins / value))
    if metric == "gear":
        return 1.0 if owns_item else max(0.0, min(0.99, money / max(spec_target["price"], 1)))
    if metric == "followers":
        return max(0.0, min(1.0, (followers - start) / max(value - start, 1)))
    return 0.0
