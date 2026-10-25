"""The catalogue of life events: little dilemmas that make a career feel lived in.

Every event is a template with bilingual text (en/ru), optional placeholders ({rival}, {stuck}...), a
condition on the player's situation and 1-3 options. An option has one or more weighted outcomes; each
outcome carries effects (see services/events.apply_effects):

  motivation / morale / fatigue / form   deltas
  money        dollars for a teenager (scaled up for students and workers)
  followers    delta
  skill        {sub_stat_or_group: gain}; "$stuck" is the skill the player has hit a wall on
  rival_heat   delta on the rival named in the event
  injury       "minor_strain"
  mod          lasting effect: {days, free_hours, learning, play, label_en, label_ru}
  reputation   delta on the community reputation (services/integrity.adjust_reputation)
  wear         delta on the wear of the input device in use (negative = repaired/replaced)
  post         "drama" | "news": the outcome also becomes a forum thread

Nothing here touches the database; conditions read a plain Ctx.
"""

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Ctx:
    on: object  # datetime.date
    age: float | None
    occupation: str
    rank: int | None
    money: float
    followers: int
    fatigue: float
    motivation: float
    injury: str
    era: str  # old_school | competitive | farm | modern
    year: int
    month: int
    device: str
    rival: str | None
    in_exams: bool
    in_holidays: bool
    birthday: bool
    stuck: str | None  # sub-stat with the biggest plateau, if it is a real wall
    streaming: bool  # streaming exists in this year
    has_team: bool = False
    wear: float = 0.0  # worst wear of the gear in use, 0..1
    reputation: float = 60.0


@dataclass(frozen=True)
class Out:
    en: str
    ru: str
    effects: dict = field(default_factory=dict)
    weight: float = 1.0


@dataclass(frozen=True)
class Opt:
    key: str
    en: str
    ru: str
    hint_en: str
    hint_ru: str
    outcomes: tuple[Out, ...]


@dataclass(frozen=True)
class Template:
    key: str
    category: str  # family | school | work | health | gear | community | fame
    title: tuple[str, str]
    body: tuple[str, str]
    options: tuple[Opt, ...]
    default: str
    when: Callable[[Ctx], bool] = lambda c: True
    weight: float = 1.0
    cooldown: int = 30
    ttl: int = 7
    once: bool = False
    guaranteed: bool = False  # fires whenever eligible (birthdays), bypassing the daily chance


def _mod(days, label_en, label_ru, free_hours=0.0, learning=1.0, play=1.0):
    return {"days": days, "free_hours": free_hours, "learning": learning, "play": play,
            "label_en": label_en, "label_ru": label_ru}


def _ok(en: str, ru: str, effects: dict, hint_en: str = "", hint_ru: str = "") -> tuple[Opt, ...]:
    return (Opt("ok", "OK", "Ясно", hint_en, hint_ru, (Out(en, ru, effects),)),)


def _young(c: Ctx) -> bool:
    return c.age is not None and c.age < 16


def _student(c: Ctx) -> bool:
    return c.occupation in ("school", "university")


T = Template  # shorthand for the table below

CATALOG: tuple[Template, ...] = (
    T("parents_limit", "family", ("Parents want the computer off", "Родители требуют выключить компьютер"),
      ("Your parents say you spend too much time on that circle-clicking game. Dinner is cold and the screen time is up.",
       "Родители говорят, что вы слишком много сидите за этой игрой с кружочками. Ужин остыл, а время вышло."),
      (Opt("negotiate", "Negotiate a deal", "Договориться", "Safer, costs some hours", "Надёжнее, но съест часы",
           (Out("They agree to shorter sessions if your grades stay up.", "Они согласны на более короткие сессии, пока вы держите оценки.",
                {"morale": 3, "mod": _mod(14, "Deal with parents", "Договорённость с родителями", free_hours=-1)}, 3),
            Out("They won't budge and you leave the table in a mood.", "Они непреклонны, и вы уходите из-за стола в плохом настроении.",
                {"motivation": -4}, 1))),
       Opt("sneak", "Play after lights out", "Играть ночью", "Risky", "Рискованно",
           (Out("Grounded: they found the glow under your door.", "Вас застукали по свету из-под двери: домашний арест.",
                {"motivation": -6, "morale": -4, "mod": _mod(7, "Grounded", "Домашний арест", free_hours=-3)}, 45),
            Out("You get away with it and squeeze in extra practice, if a little sleepy.", "Сошло с рук: лишняя практика, пусть и в полусне.",
                {"fatigue": 8, "skill": {"tapping": 0.25, "aim": 0.25}}, 55))),
       Opt("accept", "Switch it off", "Выключить", "Calm", "Спокойно",
           (Out("You help with dinner. Rest is good for the hands too.", "Вы помогаете с ужином. Руки тоже отдохнули.",
                {"motivation": -2, "morale": 1, "fatigue": -5}),))),
      "accept", when=lambda c: _young(c) and c.occupation == "school", weight=1.4, cooldown=60),

    T("exam_season", "school", ("Exam season", "Сессия"),
      ("Exams are around the corner. Everyone says to study; the leaderboard says otherwise.",
       "Скоро экзамены. Все говорят «учись», а рейтинг говорит обратное."),
      (Opt("study", "Hit the books", "Сесть за учёбу", "Fewer hours for a while", "Меньше часов на игру",
           (Out("You pass comfortably and the pressure is off.", "Экзамены сданы уверенно, давление спало.",
                {"morale": 3, "mod": _mod(10, "Studying for exams", "Подготовка к экзаменам", free_hours=-3)}),)),
       Opt("wing_it", "Wing it", "Понадеяться на удачу", "Keeps your hours, risks your mood", "Часы целы, нервы нет",
           (Out("You scrape through. Lucky.", "Еле-еле сдали. Повезло.", {"morale": 1}, 60),
            Out("A bad grade. Your parents are not amused.", "Плохая оценка. Родители не в восторге.",
                {"morale": -8, "motivation": -6, "mod": _mod(7, "Retake pressure", "Пересдача", free_hours=-2)}, 40)))),
      "study", when=lambda c: _student(c) and c.in_exams, weight=3.0, cooldown=40),

    T("friends_hangout", "family", ("Friends invite you out", "Друзья зовут гулять"),
      ("Your friends are heading out. They've stopped asking you to join, because you always say no.",
       "Друзья идут гулять. Они уже почти перестали звать, потому что вы вечно отказываетесь."),
      (Opt("go", "Go along", "Пойти", "Rest and mood, a lost afternoon", "Отдых и настроение, потерянный день",
           (Out("A great evening. Your hands thank you, and you feel human again.", "Отличный вечер. Руки отдохнули, вы снова чувствуете себя человеком.",
                {"fatigue": -10, "motivation": 6, "morale": 4, "form": 0.2}),)),
       Opt("stay", "Stay and grind", "Остаться играть", "More practice, a little lonelier", "Больше практики, чуть одиноко",
           (Out("You stay in. The room is quiet; so is your motivation.", "Вы остаётесь дома. В комнате тихо, мотивации тоже.",
                {"motivation": -2, "skill": {"tapping": 0.15}}),))),
      "stay", when=lambda c: c.age is None or c.age >= 10, weight=0.8, cooldown=40),

    T("caught_cold", "health", ("You caught a cold", "Вы простудились"),
      ("Sore throat, heavy head. Your cursor feels about as sharp as your thoughts.",
       "Больное горло, тяжёлая голова. Курсор ощущается так же вяло, как и мысли."),
      (Opt("rest", "Rest up", "Отлежаться", "A few days of lost play", "Пара дней без игры",
           (Out("Three days in bed and you are back, restored.", "Три дня в постели, и вы как новенький.",
                {"fatigue": -15, "morale": -1, "mod": _mod(3, "Recovering from a cold", "Выздоровление", free_hours=-4)}),)),
       Opt("push", "Play through it", "Играть, несмотря ни на что", "Hurts your learning", "Страдает обучение",
           (Out("You grind sick. It feels like swimming in syrup.", "Вы играете больным. Как плыть в сиропе.",
                {"fatigue": 12, "form": -0.4, "mod": _mod(4, "Sick but playing", "Играете больным", learning=0.8)}),))),
      "rest", weight=0.9, cooldown=45),

    T("family_trip", "family", ("Family trip", "Семейная поездка"),
      ("A week away with the family is planned. There is no gaming rig where you are going.",
       "Запланирована неделя с семьёй. Игрового компьютера там не будет."),
      (Opt("go", "Go and enjoy it", "Поехать и отдохнуть", "No play for a week, but a recharge", "Неделя без игры, зато перезарядка",
           (Out("A perfect week. You return with fresh eyes.", "Прекрасная неделя. Вы возвращаетесь со свежим взглядом.",
                {"motivation": 8, "morale": 5, "fatigue": -15, "mod": _mod(6, "Family trip", "Семейная поездка", free_hours=-8)}),)),
       Opt("laptop", "Take the laptop", "Взять ноутбук", "A little play, half the benefit", "Немного игры и половина пользы",
           (Out("You practise on the balcony, much to everyone's annoyance.", "Вы тренируетесь на балконе, к неудовольствию всех.",
                {"motivation": 2, "mod": _mod(6, "Laptop on holiday", "Ноутбук в отпуске", free_hours=-4)}),)),
       Opt("skip", "Stay home", "Остаться дома", "Everyone is disappointed", "Все разочарованы",
           (Out("Quiet house, full schedule, guilty conscience.", "Тихий дом, плотный график, нечистая совесть.",
                {"motivation": -3, "morale": -3}),))),
      "go", when=lambda c: c.in_holidays and (c.age is None or c.age < 24) and c.occupation != "pro",
      weight=1.5, cooldown=250, ttl=10),

    T("part_time_offer", "work", ("A part-time job offer", "Предложение подработки"),
      ("A neighbour offers you part-time work. The pay is real money; the hours are real hours.",
       "Сосед предлагает подработку. Деньги настоящие, и часы тоже настоящие."),
      (Opt("accept", "Take the job", "Согласиться", "Money now, fewer free hours for a month", "Деньги сейчас, меньше свободных часов",
           (Out("The first pay comes in and the wallet feels good.", "Первая зарплата пришла, и кошелёк радует.",
                {"money": 70, "motivation": -2, "mod": _mod(30, "Part-time job", "Подработка", free_hours=-1.5)}),)),
       Opt("decline", "Decline", "Отказаться", "Keep the time", "Сохранить время",
           (Out("You keep your afternoons for osu!.", "Вы бережёте дни для osu!.", {}),))),
      "decline", when=lambda c: c.age is not None and 15 <= c.age <= 26 and _student(c) and c.money < 400,
      weight=1.0, cooldown=120),

    T("overtime_request", "work", ("Boss asks for overtime", "Начальник просит задержаться"),
      ("A deadline is looming and your boss asks you to stay late all week.",
       "Горит дедлайн, и начальник просит остаться допоздна всю неделю."),
      (Opt("accept", "Stay late", "Задержаться", "Money, tired", "Деньги, но усталость",
           (Out("A fat bonus and a worn-out wrist.", "Хорошая премия и уставшее запястье.",
                {"money": 80, "fatigue": 8, "mod": _mod(7, "Overtime", "Сверхурочные", free_hours=-2)}),)),
       Opt("refuse", "Politely refuse", "Вежливо отказаться", "Keep your hours", "Часы остаются при вас",
           (Out("Your boss sighs and moves on. Your evenings are yours.", "Начальник вздыхает и находит другого. Вечера ваши.",
                {"morale": -1}),))),
      "refuse", when=lambda c: c.occupation == "work", weight=1.6, cooldown=60),

    T("burnout_warning", "health", ("You feel burned out", "Накатило выгорание"),
      ("Every session feels like a chore. The fun is gone and your hands feel heavy.",
       "Каждая сессия как обязанность. Удовольствие пропало, руки тяжёлые."),
      (Opt("break", "Take a real break", "Взять настоящий перерыв", "Costs a few days, saves a lot", "Пара дней, но поможет",
           (Out("A few days away from the screen and the fire returns.", "Несколько дней вдали от экрана, и огонь вернулся.",
                {"fatigue": -25, "motivation": 15, "form": 0.3, "mod": _mod(4, "Taking a break", "Перерыв", free_hours=-6)}),)),
       Opt("talk", "Talk to a friend", "Поговорить с другом", "Helps your mood", "Улучшит настроение",
           (Out("Venting helps more than you expected.", "Выговориться оказалось полезнее, чем казалось.",
                {"motivation": 8, "morale": 4}),)),
       Opt("grind", "Grind through it", "Продолжать давить", "Dangerous for the wrists", "Опасно для запястий",
           (Out("You power through and feel worse.", "Вы продавливаете себя и чувствуете себя хуже.",
                {"motivation": -6, "fatigue": 10}, 70),
            Out("The pain is real: a wrist strain.", "Боль настоящая: растяжение запястья.",
                {"motivation": -6, "fatigue": 10, "injury": "minor_strain"}, 30)))),
      "grind", when=lambda c: c.motivation < 35 and c.fatigue > 45, weight=4.0, cooldown=40),

    T("peripheral_wear", "gear", ("Your {device} is acting up", "Сбои в работе: {device}"),
      ("Double clicks, jitter, lag: the {device} you rely on is wearing out.",
       "Двойные клики, дрожание, лаги: вашему устройству ввода ({device}) приходит конец."),
      (Opt("replace", "Buy a replacement", "Купить новый", "Costs money, no worries", "Деньги, зато без проблем",
           (Out("A new one arrives. It feels amazing.", "Приезжает новый. Ощущения прекрасные.",
                {"money": -35, "motivation": 3, "wear": -1.0}),)),
       Opt("patch", "Patch it up", "Подлатать", "Cheap, might not hold", "Дёшево, но может не помочь",
           (Out("A bit of tape and a click-fix. Holds up fine.", "Немного изоленты и подпилить кнопку. Держится.",
                {"money": -8, "wear": -0.3}, 55),
            Out("The fix doesn't hold; misclicks follow you for days.", "Починка не держится; промахи преследуют несколько дней.",
                {"money": -8, "mod": _mod(10, "Faulty {device}", "Неисправность: {device}", play=0.97)}, 45))),
       Opt("ignore", "Ignore it", "Не обращать внимания", "Hurts your play", "Вредит игре",
           (Out("You play on with a worsening setup.", "Вы играете дальше, пока ситуация только хуже.",
                {"mod": _mod(14, "Failing {device}", "Умирающее устройство: {device}", play=0.97)}),))),
      "patch", when=lambda c: c.wear >= 0.3, weight=1.6, cooldown=120),

    T("internet_outage", "gear", ("The internet is down", "Пропал интернет"),
      ("The router died. No online play, no downloads, no forum.",
       "Роутер сдох. Ни игры онлайн, ни загрузок, ни форума."),
      (Opt("wait", "Wait it out", "Ждать", "A few lost days", "Несколько потерянных дней",
           (Out("Two quiet days, then everything is back.", "Два тихих дня, и всё вернулось.",
                {"motivation": -2, "mod": _mod(3, "No internet", "Нет интернета", free_hours=-3)}),)),
       Opt("hotspot", "Use phone data", "Раздать с телефона", "Pay a bit, keep playing", "Немного заплатить и играть",
           (Out("Slow, pricey, but you keep up the routine.", "Медленно и дорого, но режим сохранён.",
                {"money": -10, "mod": _mod(3, "Slow connection", "Медленный интернет", free_hours=-1)}),)),
       Opt("upgrade", "Get a better provider", "Сменить провайдера", "Costs money, mood boost", "Дороже, но приятно",
           (Out("Faster than ever. Lag is a thing of the past.", "Быстрее, чем когда-либо. Лаги в прошлом.",
                {"money": -40, "morale": 3}),))),
      "wait", weight=0.9, cooldown=90),

    T("rival_trash_talk", "community", ("{rival} is talking", "{rival} провоцирует"),
      ("{rival} posted a mocking comment about your ranking. People are watching to see how you answer.",
       "{rival} оставил язвительный комментарий о вашем рейтинге. Все смотрят, как вы ответите."),
      (Opt("reply", "Fire back", "Ответить в тон", "Heats the rivalry", "Раскочегарит вражду",
           (Out("Your reply gets passed around. The chat loves it.", "Ваш ответ разошёлся по чатам. Публика в восторге.",
                {"rival_heat": 12, "followers": 10, "morale": 3, "reputation": -1}, 60),
            Out("It comes out wrong and you regret it.", "Получилось неудачно, и вы жалеете.",
                {"rival_heat": 12, "morale": -4, "reputation": -3}, 40))),
       Opt("ignore", "Ignore it", "Не реагировать", "Stay focused", "Сохранить концентрацию",
           (Out("You say nothing and let the plays talk.", "Вы молчите и даёте говорить игре.",
                {"form": 0.1, "motivation": 2, "reputation": 1}),)),
       Opt("challenge", "Challenge to a duel", "Бросить вызов", "Big stakes", "Высокие ставки",
           (Out("The challenge is public. Now you have to deliver.", "Вызов публичный. Теперь придётся оправдывать.",
                {"rival_heat": 20, "motivation": 8, "followers": 15}),))),
      "ignore", when=lambda c: c.rival is not None, weight=2.0, cooldown=45),

    T("fan_message", "fame", ("A fan message", "Сообщение от фаната"),
      ("Someone wrote that your plays got them into osu!. What do you say?",
       "Кто-то написал, что ваши плеи затянули его в osu!. Что ответите?"),
      (Opt("reply", "Write back", "Ответить", "Builds goodwill", "Хорошо для репутации",
           (Out("Your kind reply earns a new follower and a good feeling.", "Тёплый ответ даёт нового подписчика и хорошее настроение.",
                {"followers": 8, "morale": 3, "reputation": 1}),)),
       Opt("ignore", "Skip it", "Пропустить", "Nothing happens", "Ничего не случится",
           (Out("The message sinks below the fold.", "Сообщение утонуло в ленте.", {}),))),
      "ignore", when=lambda c: c.followers >= 60, weight=1.0, cooldown=60),

    T("streamer_collab", "fame", ("A streamer wants to collab", "Стример зовёт на коллаб"),
      ("A bigger streamer wants to play a few maps with you live.",
       "Стример побольше предлагает сыграть вместе несколько карт в эфире."),
      (Opt("accept", "Do it", "Согласиться", "Followers, tiring", "Подписчики, но устанете",
           (Out("The stream goes great and chat floods in.", "Эфир удался, и чат ломится от зрителей.",
                {"followers": 90, "money": 20, "fatigue": 6}, 70),
            Out("An awkward evening; your nerves show.", "Неловкий вечер, нервы видны.",
                {"followers": 20, "morale": -3, "fatigue": 6}, 30))),
       Opt("decline", "Not now", "Не сейчас", "Nothing changes", "Ничего не меняется",
           (Out("Maybe another time.", "Может быть, в другой раз.", {}),))),
      "decline", when=lambda c: c.streaming and c.followers >= 300, weight=1.0, cooldown=90),

    T("mapper_request", "community", ("A mapper needs a test-player", "Маппер ищет тестера"),
      ("A mapper is polishing a new set and wants a high-level player to test it.",
       "Маппер дорабатывает новый сет и ищет тестера высокого уровня."),
      (Opt("test", "Test-play it", "Протестировать", "A little practice, a little time", "Немного практики, немного времени",
           (Out("The map teaches you something new about rhythm.", "Карта учит чему-то новому о ритме.",
                {"skill": {"rhythm_reading": 0.4, "awkward_angles": 0.2}, "followers": 5,
                 "mod": _mod(4, "Test-playing a map", "Тест карты", free_hours=-1)}),)),
       Opt("decline", "Pass", "Отказать", "Nothing", "Ничего",
           (Out("They find someone else.", "Они находят другого.", {}),))),
      "decline", when=lambda c: c.rank is not None and c.rank < 30000, weight=1.0, cooldown=60),

    T("cheat_accusation", "community", ("Someone calls your play suspicious", "Ваш плей назвали подозрительным"),
      ("A thread accuses you of using assistance on a recent play. The replay is out there; people want an answer.",
       "В теме вас обвиняют в читерстве на недавнем плее. Реплей в открытом доступе, народ ждёт ответа."),
      (Opt("stream", "Prove it on stream", "Доказать на стриме", "Risky but convincing", "Рискованно, но убедительно",
           (Out("You replay it live. The doubters go quiet.", "Вы переигрываете плей в прямом эфире. Скептики замолкают.",
                {"followers": 80, "morale": 6, "reputation": 5, "post": "drama"}, 75),
            Out("Nerves get you; the doubt lingers.", "Нервы подводят, сомнения остаются.",
                {"followers": 10, "morale": -4, "reputation": -2}, 25))),
       Opt("replay", "Post your replay file", "Выложить реплей", "Safe and boring", "Скучно, но безопасно",
           (Out("Analysts check it and the case closes.", "Аналитики разбирают реплей, дело закрыто.",
                {"followers": 20, "morale": 2, "reputation": 2}, 85),
            Out("The drama drags on for weeks.", "Драма тянется неделями.", {"morale": -5, "reputation": -2, "post": "drama"}, 15))),
       Opt("ignore", "Ignore it", "Игнорировать", "It festers", "Нарывает",
           (Out("Silence reads as guilt to some.", "Молчание кто-то читает как вину.",
                {"morale": -6, "motivation": -4, "followers": -10, "reputation": -5}),))),
      "ignore", when=lambda c: c.rank is not None and c.rank < 5000 and c.year >= 2011, weight=0.7, cooldown=150, ttl=10),

    T("sponsor_pitch", "fame", ("A sponsor makes an offer", "Предложение от спонсора"),
      ("A small company offers to sponsor you in exchange for posts and a logo on your stream.",
       "Небольшая компания предлагает спонсорство за посты и логотип на стриме."),
      (Opt("accept", "Accept", "Согласиться", "Money, with strings", "Деньги, но с обязательствами",
           (Out("A signed deal and a cheque.", "Контракт подписан, чек получен.",
                {"money": 150, "followers": 20, "mod": _mod(30, "Sponsor obligations", "Обязательства перед спонсором", free_hours=-1)}),)),
       Opt("negotiate", "Negotiate", "Поторговаться", "Might pay more, or fall through", "Может выйти лучше или сорваться",
           (Out("They come up with a better offer.", "Они поднимают ставку.",
                {"money": 300, "followers": 20, "mod": _mod(30, "Sponsor obligations", "Обязательства перед спонсором", free_hours=-1)}, 60),
            Out("They walk away and find someone cheaper.", "Они уходят и находят дешевле.", {"morale": -2}, 40))),
       Opt("decline", "Decline", "Отказаться", "Stay independent", "Остаться независимым",
           (Out("You keep your freedom.", "Вы сохраняете свободу.", {"morale": 1}),))),
      "decline", when=lambda c: ((c.rank is not None and c.rank < 3000) or c.followers >= 800) and c.year >= 2011
         and c.reputation >= 30,
      weight=0.9, cooldown=120),

    T("top_player_dm", "community", ("A top player messages you", "Вам пишет топ-игрок"),
      ("A much stronger player noticed your progress and offers to play a few maps together.",
       "Заметивший ваш прогресс сильнейший игрок предлагает поиграть вместе несколько карт."),
      (Opt("practice", "Play together", "Сыграть вместе", "Great practice, tiring", "Отличная практика, но устанете",
           (Out("You get outplayed and learn a lot.", "Вас переигрывают, но вы многому учитесь.",
                {"skill": {"aim": 0.3, "tapping": 0.3, "reading": 0.3}, "fatigue": 5, "followers": 10}),)),
       Opt("advice", "Ask for advice", "Попросить совет", "Mental edge", "Психологический опыт",
           (Out("Three sentences of advice are worth a week of practice.", "Три фразы совета стоят недели тренировок.",
                {"skill": {"clutch": 0.5, "nerve_resistance": 0.5}, "motivation": 5}),)),
       Opt("thanks", "Thank politely", "Вежливо поблагодарить", "Nothing happens", "Ничего не изменится",
           (Out("A pleasant, short chat.", "Приятный и короткий разговор.", {"morale": 1}),))),
      "thanks", when=lambda c: c.rank is not None and 200 < c.rank < 20000, weight=0.8, cooldown=120),

    T("referee_offer", "community", ("Referee a tournament", "Судить турнир"),
      ("Organisers need a referee for a community tournament and think of you.",
       "Организаторам нужен судья на комьюнити-турнире, и они вспомнили о вас."),
      (Opt("accept", "Referee", "Согласиться", "Money and followers, time spent", "Деньги и подписчики, но время",
           (Out("A long weekend, a good paycheck and new connections.", "Длинные выходные, неплохая плата и новые знакомства.",
                {"money": 60, "followers": 25, "reputation": 2, "mod": _mod(7, "Refereeing", "Судейство", free_hours=-2)}),)),
       Opt("decline", "Decline", "Отказаться", "Nothing", "Ничего",
           (Out("Another referee is found.", "Находят другого судью.", {}),))),
      "decline", when=lambda c: c.rank is not None and c.rank < 2000 and c.year >= 2012, weight=0.8, cooldown=120),

    T("local_meetup", "community", ("An osu! meetup nearby", "Встреча игроков неподалёку"),
      ("Local players are gathering to play, eat and talk. It is a rare chance to meet the faces behind the names.",
       "Местные игроки собираются поиграть, поесть и поговорить. Редкий шанс увидеть тех, кто стоит за никами."),
      (Opt("go", "Go", "Пойти", "Mood and followers, costs a bit", "Настроение и подписчики, немного денег",
           (Out("A fun day. You come back inspired.", "Весёлый день. Вы возвращаетесь вдохновлённым.",
                {"money": -20, "motivation": 8, "morale": 6, "followers": 10, "fatigue": 4}),)),
       Opt("skip", "Skip", "Пропустить", "Nothing", "Ничего",
           (Out("Maybe next time.", "Может быть, в следующий раз.", {}),))),
      "skip", when=lambda c: (c.age is None or c.age >= 14), weight=0.8, cooldown=180, ttl=10),

    T("wrist_ache", "health", ("An ache in your wrist", "Ноет запястье"),
      ("A dull ache after long sessions. It's the kind that people ignore until it's too late.",
       "Тупая боль после долгих сессий. Из тех, что игнорируют, пока не станет поздно."),
      (Opt("rest", "Rest it for two days", "Дать отдохнуть два дня", "Safe", "Безопасно",
           (Out("Two quiet days and the ache fades.", "Два тихих дня, и боль проходит.",
                {"fatigue": -20, "mod": _mod(2, "Resting the wrist", "Отдых запястья", free_hours=-14)}),)),
       Opt("stretch", "Stretch and warm up", "Размяться и растянуться", "Builds resilience", "Укрепляет",
           (Out("You learn some proper stretches.", "Вы осваиваете правильную растяжку.",
                {"skill": {"rsi_resistance": 0.6}, "fatigue": -8}),)),
       Opt("push", "Push through", "Терпеть", "Risk of strain", "Риск травмы",
           (Out("You pull a strained tendon.", "Вы растягиваете сухожилие.",
                {"injury": "minor_strain", "fatigue": 6}, 30),
            Out("It fades. This time.", "Прошло. На этот раз.", {"form": 0.1, "fatigue": 6}, 70)))),
      "push", when=lambda c: c.fatigue > 55 and c.injury == "healthy", weight=3.0, cooldown=21),

    T("epiphany", "school", ("Something clicks", "Вдруг щёлкнуло"),
      ("Watching a replay, you suddenly see how it should feel: {stuck}.",
       "Смотря реплей, вы вдруг понимаете, как это должно ощущаться: {stuck}."),
      _ok("It will take practice, but now you know the way.", "Придётся потренироваться, но теперь вы знаете путь.",
          {"skill": {"$stuck": 1.0}, "motivation": 6}),
      "ok", when=lambda c: c.stuck is not None, weight=0.8, cooldown=30, ttl=3),

    T("birthday_gift", "family", ("Happy birthday", "С днём рождения"),
      ("Family and friends remember your birthday, with some money in an envelope.",
       "Семья и друзья помнят о дне рождения и дарят конверт с деньгами."),
      _ok("Money for your next upgrade, and a good mood.", "Деньги на следующий апгрейд и отличное настроение.",
          {"money": 60, "motivation": 4, "morale": 3}),
      "ok", when=lambda c: c.birthday and (c.age is None or c.age < 40), weight=20.0, cooldown=300, ttl=5, guaranteed=True),

    T("new_pack", "community", ("A fresh map pack is out", "Вышел свежий набор карт"),
      ("The community is buzzing about a brand new farm pack.",
       "Комьюнити обсуждает свежий фарм-пак."),
      (Opt("grind", "Download and grind", "Скачать и пройти", "Extra practice", "Дополнительная практика",
           (Out("You blaze through the pack.", "Вы пролетаете пак.",
                {"skill": {"snap_aim": 0.3, "high_ar_reaction": 0.3}, "fatigue": 5,
                 "mod": _mod(2, "Pack grind", "Гринд пака", free_hours=-1)}),)),
       Opt("skip", "Skip it", "Пропустить", "Nothing", "Ничего",
           (Out("You'll catch it later.", "Нагоните позже.", {}),))),
      "skip", when=lambda c: c.era in ("farm", "modern"), weight=0.8, cooldown=60),

    T("viral_clip", "fame", ("Your clip goes viral", "Ваш клип завирусился"),
      ("A clip of your play is spreading fast on social media.",
       "Клип вашего плея стремительно расходится по соцсетям."),
      _ok("Notifications everywhere, a few hundred new followers.", "Уведомления везде и несколько сотен новых подписчиков.",
          {"followers": 80, "morale": 5, "post": "news"}),
      "ok", when=lambda c: c.followers >= 50 and c.year >= 2013, weight=0.4, cooldown=150, ttl=3),

    T("desk_upgrade", "gear", ("Your back hurts", "Болит спина"),
      ("Hours at the desk have caught up with you. A better setup would help.",
       "Долгие часы за столом дают о себе знать. Лучшая организация рабочего места помогла бы."),
      (Opt("fix", "Fix the setup", "Привести стол в порядок", "Costs a little, helps the wrists", "Недорого, но полезно запястьям",
           (Out("Chair height, desk, breaks: the little things count.", "Высота стула, стол, перерывы: мелочи имеют значение.",
                {"money": -30, "skill": {"rsi_resistance": 0.8}}),)),
       Opt("ignore", "Ignore it", "Не обращать внимания", "Nothing changes", "Ничего не меняется",
           (Out("You slouch on.", "Вы продолжаете сутулиться.", {"fatigue": 3}),))),
      "ignore", when=lambda c: c.fatigue > 30 and c.money >= 40, weight=0.7, cooldown=150),
)

BY_KEY: dict[str, Template] = {t.key: t for t in CATALOG}
assert len(BY_KEY) == len(CATALOG)

DAILY_CHANCE = 0.09
MAX_PENDING = 3


def eligible(ctx: Ctx, last_fired: dict[str, str], today, fired_once: set[str]) -> list[Template]:
    from datetime import date

    out = []
    for t in CATALOG:
        if t.once and t.key in fired_once:
            continue
        last = last_fired.get(t.key)
        if last and (today - date.fromisoformat(last)).days < t.cooldown:
            continue
        if t.when(ctx):
            out.append(t)
    return out


def render(template: Template, data: dict, lang: str) -> dict:
    """Title, body and option labels in one language with the placeholders filled."""
    i = 1 if lang == "ru" else 0

    def fill(s: str) -> str:
        try:
            return s.format(**data)
        except (KeyError, IndexError):
            return s

    return {
        "title": fill(template.title[i]),
        "body": fill(template.body[i]),
        "options": [{"key": o.key, "label": o.ru if i else o.en, "hint": o.hint_ru if i else o.hint_en}
                    for o in template.options],
    }


STAT_RU = {
    "snap_aim": "снэп-аим (рывки)", "flow_aim": "флоу-аим", "precision": "точность и малый CS",
    "distance": "дальние прыжки", "low_mid_bpm": "контроль низкого/среднего BPM", "burst": "бёрсты на высоком BPM",
    "deathstream": "выносливость в дэтстримах", "finger_independence": "независимость пальцев",
    "low_ar_reading": "ридинг низкого AR и плотных карт", "high_ar_reaction": "реакция на высоком AR",
    "rhythm_reading": "ридинг сложного ритма", "hidden": "игра с Hidden", "slider_velocity": "сложные слайдеры и SV",
    "awkward_angles": "неудобные углы", "strict_od": "HardRock и строгий OD", "nerve_resistance": "стрессоустойчивость",
    "clutch": "игра в решающие моменты", "tilt_resilience": "устойчивость к тильту", "hand_stamina": "выносливость рук",
    "rsi_resistance": "устойчивость к травмам (RSI)", "visual_endurance": "выносливость зрения",
}
DEVICE_NAMES = {"mouse": ("mouse", "мышь"), "tablet": ("tablet", "планшет")}
