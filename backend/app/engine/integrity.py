"""Community integrity: accusations, replay review, restrictions and reputation.

Everything in the simulation is honest, so a review usually clears the player, but the process costs
reputation, mood and sometimes a short wrongful restriction. Text is bilingual (en/ru) and rendered
at read time from keys + data.
"""

REPUTATION_START = 60.0
REPUTATION_DRIFT_TARGET = 55.0
REPUTATION_DRIFT_PER_WEEK = 0.4
CASE_TTL_DAYS = 7
CASE_COOLDOWN_DAYS = 45
CHECK_EVERY_DAYS = 7
NPC_SCANDAL_CHANCE = 0.05
NPC_SCANDAL_AWAY_DAYS = (60, 200)
KEEP_CASES = 12
KEEP_LOG = 25

LABELS = [(15, ("Disgraced", "Опозорен")), (35, ("Distrusted", "Под подозрением")), (55, ("Questionable", "Неоднозначная")),
          (75, ("Respected", "Уважаемый")), (101, ("Beloved", "Любимец сообщества"))]

# trigger -> (title en, title ru, body en, body ru); {play}, {pp}, {from_rank}, {to_rank}
CASE_TEXT = {
    "rank_jump": (
        "Accusations after a sudden climb", "Обвинения после резкого взлёта",
        "You went from #{from_rank} to #{to_rank} in a few weeks and a thread asks how that is possible. "
        "People want to see a replay.",
        "Вы поднялись с #{from_rank} на #{to_rank} за пару недель, и в теме спрашивают, как такое возможно. "
        "Люди хотят увидеть реплей."),
    "great_play": (
        "Is this play legit?", "Этот плей вообще легитимный?",
        "Your recent play on {play} is far above what your profile suggests. Someone posted frame-by-frame "
        "screenshots of the cursor.",
        "Ваш недавний плей на {play} сильно выше того, чего ждут от вашего профиля. Кто-то выложил "
        "покадровые скриншоты курсора."),
    "routine": (
        "Routine reports", "Типичные жалобы",
        "Top players always get reported. A few people filed reports on you and moderators want a reply.",
        "На топов всегда жалуются. Несколько человек отправили жалобу на вас, и модераторам нужен ответ."),
}

# response key -> (label en, label ru, hint en, hint ru)
RESPONSES = {
    "replay": ("Publish the replay", "Выложить реплей", "Safe and boring", "Скучно, но безопасно"),
    "stream": ("Replay it live on stream", "Переиграть в прямом эфире", "Convincing if you hold your nerves",
               "Убедительно, если не дрогнут нервы"),
    "appeal": ("Appeal to the moderators", "Обратиться к модераторам", "Fair, but a review can freeze your account",
               "Честно, но проверка может заморозить аккаунт"),
    "ignore": ("Ignore it", "Игнорировать", "Silence is read as guilt", "Молчание читают как вину"),
}

# outcome key -> text en/ru
OUTCOME_TEXT = {
    "cleared": ("The analysts check it and the case is closed in your favour.",
                "Аналитики проверили, и дело закрыто в вашу пользу."),
    "lingering": ("The replay holds up, but the doubts linger in the comments.",
                  "Реплей выдерживает проверку, но сомнения остаются в комментариях."),
    "vindicated": ("You replay it live. The doubters go quiet and chat explodes.",
                   "Вы переигрываете в эфире. Скептики замолкают, чат взрывается."),
    "shaky": ("Nerves get you on stream and the doubt grows.", "Нервы подводят в эфире, и сомнения растут."),
    "restriction": ("The review freezes your account for a few days. It turns out to be a mistake, but it hurts.",
                    "Проверка замораживает аккаунт на несколько дней. Это окажется ошибкой, но неприятно."),
    "fades": ("Nobody got an answer; the story slowly fades, with a bad taste.",
              "Ответа никто не получил; история затихает, осадок остался."),
}

# (response, [(outcome, weight, effects)]); effects: reputation, morale, motivation, followers, fatigue,
# restrict_days (min, max), post
OUTCOMES = {
    "replay": [("cleared", 85, {"reputation": 3, "followers": 20, "morale": 3}),
               ("lingering", 15, {"reputation": -2, "morale": -4})],
    "stream": [("vindicated", 70, {"reputation": 6, "followers": 80, "morale": 6, "fatigue": 6, "post": "drama"}),
               ("shaky", 30, {"reputation": -3, "morale": -5, "fatigue": 6})],
    "appeal": [("cleared", 88, {"reputation": 2, "morale": 1}),
               ("restriction", 12, {"reputation": -5, "morale": -10, "motivation": -6, "restrict_days": (3, 7),
                                    "post": "drama"})],
    "ignore": [("fades", 85, {"reputation": -6, "morale": -5, "followers": -10}),
               ("restriction", 15, {"reputation": -8, "morale": -10, "motivation": -6, "restrict_days": (3, 7),
                                    "post": "drama"})],
}
DEFAULT_RESPONSE = "ignore"


def label(rep: float, lang: str) -> str:
    i = 1 if lang == "ru" else 0
    return next(text[i] for limit, text in LABELS if rep < limit)


def sponsor_factor(rep: float) -> float:
    return 0.4 + 0.01 * rep if rep <= 60 else 1.0 + (rep - 60) * 0.0075


def follower_factor(rep: float) -> float:
    return 0.6 + rep / 150


def suspicion_level(factors: list[dict]) -> float:
    out = 1.0
    for f in factors:
        out *= 1 - f["level"]
    return round(1 - out, 3)
