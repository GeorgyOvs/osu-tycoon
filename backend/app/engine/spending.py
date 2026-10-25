"""The catalogue of things to spend money on: coaching, health, setup extras, community and career, small treats.

Every item is data. Prices are USD, inflate with the era and follow your means (a student pays student prices).
Effects use the lasting-modifier store of services/story.py:

  learning, learn_<group>   training speed (all / one skill group)
  recovery                  fatigue recovery multiplier
  injury                    RSI risk multiplier         hiatus   length of a severe hiatus
  income                    stream money and sponsor pay   followers_mult   follower growth from streaming
  pack                      training efficiency of ranked-map drills
  skill_<sub_stat>          a multiplier on that skill while playing
  play, free_hours          as for life events

Kinds: one_off (instant effects, maybe a timed buff), timed (a buff for `days`), sub (a monthly subscription whose perks last
while it is paid), owned (bought once, perks forever).
"""

from dataclasses import dataclass, field
from datetime import date

GROUPS = ("aim", "tapping", "reading", "technical", "mentality", "physical")
GROUP_NAMES = {
    "aim": ("Aim", "Аим"), "tapping": ("Tapping", "Тэппинг"), "reading": ("Reading", "Ридинг"),
    "technical": ("Technical", "Техника"), "mentality": ("Mentality", "Психология"), "physical": ("Physical", "Физика"),
}
FOREVER = "2100-01-01"

CATEGORIES = {
    "coaching": ("Coaching & training", "Тренеры и обучение", "🎓"),
    "health": ("Health & lifestyle", "Здоровье и быт", "💪"),
    "setup": ("Setup extras", "Дополнения к сетапу", "🖱"),
    "career": ("Community & career", "Сообщество и карьера", "🌐"),
    "treats": ("Small things", "Мелочи", "☕"),
}

# What you can afford: students pay student prices, professionals pay professional ones.
TIER = {"school": 0.5, "university": 0.8, "work": 1.5, "pro": 2.0}
REGION_TRAVEL = {"EU": 1.0, "NA": 1.3, "AS": 1.4, "SA": 1.5, "OC": 1.7}


def era_factor(on: date) -> float:
    """Prices drift up over the years: 1.0 in 2008, ~1.6 in 2024."""
    return round(1.0 + 0.6 * max(0.0, min(1.0, (on.year + (on.month - 1) / 12 - 2008) / 16)), 3)


@dataclass(frozen=True)
class Item:
    key: str
    category: str
    icon: str
    kind: str  # one_off | timed | sub | owned
    name: tuple[str, str]
    desc: tuple[str, str]
    price: float  # base price, before era and tier
    from_year: float = 2008.0
    tiered: bool = True  # scale with the player's means
    days: int = 0  # length of the buff
    cooldown: int = 0
    mods: dict = field(default_factory=dict)  # modifier keys while active
    effects: dict = field(default_factory=dict)  # instant effects (services.events.apply_effects)
    choice: str | None = None  # 'group': the buyer picks a skill group
    needs: tuple[str, ...] = ()  # team | tournament | tablet | mouse | streaming
    min_followers: int = 0
    max_rank: int | None = None
    min_age: float = 12.0
    handler: str | None = None  # special-case behaviour in services/spending.py
    perk: tuple[str, str] = ("", "")  # one line about the effect, shown on the card


def _i(**kw) -> Item:
    return Item(**kw)


CATALOG: tuple[Item, ...] = (
    # --- coaching -------------------------------------------------------------------------------
    _i(key="coach_session", category="coaching", icon="🎯", kind="timed", price=30, from_year=2010, days=7, cooldown=7,
       choice="group", min_age=13,
       name=("Private coach session", "Занятие с тренером"),
       desc=("An hour with a coach who knows your chosen skill group. You learn it much faster for a week.",
             "Час с тренером по выбранной группе навыков. Неделю вы учитесь ей заметно быстрее."),
       mods={"learn_group": 1.4}, perk=("+40% learning in one group for 7 days", "+40% к обучению группы на 7 дней")),
    _i(key="coach_retainer", category="coaching", icon="📋", kind="sub", price=22, from_year=2011, min_age=14,
       name=("Coaching retainer", "Абонемент у тренера"),
       desc=("A coach checks in every week and keeps your training honest.",
             "Тренер раз в неделю разбирает ваши тренировки и держит режим."),
       mods={"learning": 1.08}, perk=("+8% learning while subscribed", "+8% к обучению, пока абонемент оплачен")),
    _i(key="psychologist", category="coaching", icon="🧠", kind="timed", price=45, from_year=2011, days=14, cooldown=14,
       min_age=14,
       name=("Sports psychologist", "Спортивный психолог"),
       desc=("Breathing, routines and what to do after a bad map. Calmer nerves for two weeks.",
             "Дыхание, ритуалы и что делать после плохой карты. Две недели спокойнее нервы."),
       mods={"skill_nerve_resistance": 1.06, "skill_clutch": 1.06, "skill_tilt_resilience": 1.06, "recovery": 1.08},
       perk=("+6% nerves, clutch and tilt resilience, faster recovery (14 days)",
             "+6% к нервам, клатчу и тильту, быстрее восстановление (14 дней)")),
    _i(key="replay_analysis", category="coaching", icon="🎬", kind="one_off", price=14, from_year=2009, cooldown=10,
       choice="group", min_age=12,
       name=("Replay analysis", "Разбор реплеев"),
       desc=("A stronger player goes through your replays and points at the exact habits holding you back.",
             "Игрок посильнее разбирает ваши реплеи и показывает конкретные привычки, которые тормозят."),
       effects={"skill": 0.35}, perk=("+0.35 to every skill in one group", "+0.35 ко всем навыкам группы")),
    _i(key="bootcamp", category="coaching", icon="🏕", kind="one_off", price=70, from_year=2011, cooldown=60,
       needs=("team",), min_age=14, handler="bootcamp",
       name=("Team bootcamp weekend", "Командный буткемп"),
       desc=("A weekend of scrims, VOD reviews and pizza with your team. Needs at least two active teammates.",
             "Выходные со сборами, разборами и пиццей с командой. Нужны минимум двое активных товарищей."),
       perk=("+8 team chemistry, a tiring weekend", "+8 химии команды, выходные выматывают")),
    # --- health -----------------------------------------------------------------------------------
    _i(key="gym", category="health", icon="🏋", kind="sub", price=14, from_year=2008, min_age=14,
       name=("Gym & hand exercises", "Спортзал и упражнения для рук"),
       desc=("Regular strength work and wrist care. The hands hold up better and recover faster.",
             "Регулярные упражнения и уход за запястьями. Руки выдерживают больше и быстрее отходят."),
       mods={"injury": 0.85, "recovery": 1.12},
       perk=("-15% RSI risk, +12% recovery", "-15% риска травмы, +12% к восстановлению")),
    _i(key="massage", category="health", icon="💆", kind="one_off", price=22, from_year=2008, cooldown=5, min_age=14,
       handler="massage",
       name=("Massage & physio package", "Массаж и физиотерапия"),
       desc=("A proper session on forearms and wrists. Takes the edge off fatigue and soothes a minor strain.",
             "Серьёзная работа с предплечьями и запястьями. Снимает усталость и успокаивает лёгкую травму."),
       effects={"fatigue": -25, "morale": 2}, perk=("-25 fatigue, heals a minor strain", "-25 усталости, лечит лёгкую травму")),
    _i(key="eye_care", category="health", icon="👓", kind="owned", price=40, from_year=2010, min_age=12,
       name=("Eye care & blue-light glasses", "Уход за глазами и очки"),
       desc=("An eye exam and glasses for long sessions. Your eyes tire later.",
             "Проверка зрения и очки для долгих сессий. Глаза устают позже."),
       mods={"skill_visual_endurance": 1.08}, perk=("+8% visual endurance", "+8% к выносливости зрения")),
    _i(key="meal_plan", category="health", icon="🥗", kind="sub", price=24, from_year=2008, min_age=14,
       name=("Healthy meal plan", "Нормальное питание"),
       desc=("Real food instead of chips at 3 a.m. A small, steady edge.",
             "Нормальная еда вместо чипсов в 3 ночи. Небольшое, но стабильное преимущество."),
       mods={"recovery": 1.08, "learning": 1.03}, perk=("+8% recovery, +3% learning", "+8% к восстановлению, +3% к обучению")),
    _i(key="vacation", category="health", icon="🏝", kind="one_off", price=110, from_year=2008, cooldown=90, min_age=14,
       handler="vacation",
       name=("A real vacation", "Настоящий отпуск"),
       desc=("Five days away from the screen. Costly, but you come back a different person.",
             "Пять дней без экрана. Дорого, но вы возвращаетесь другим человеком."),
       effects={"motivation": 20, "morale": 15, "fatigue": -35},
       perk=("+20 motivation, -35 fatigue; 5 days off the computer", "+20 мотивации, -35 усталости; 5 дней без компьютера")),
    _i(key="medical_insurance", category="health", icon="🩺", kind="sub", price=9, from_year=2008, min_age=16,
       name=("Medical insurance", "Медицинская страховка"),
       desc=("Physio costs a fraction and a severe hiatus is shorter, because you get treated early.",
             "Физиотерапия стоит копейки, а тяжёлый перерыв короче: лечиться начинаете рано."),
       mods={"hiatus": 0.75}, perk=("physio 60% cheaper, hiatuses 25% shorter", "физио дешевле на 60%, перерывы короче на 25%")),
    # --- setup ---------------------------------------------------------------------------------------
    _i(key="mousepad", category="setup", icon="🟦", kind="owned", price=28, from_year=2008, needs=("mouse",), min_age=10,
       handler="comfort",
       name=("Quality mousepad", "Хороший коврик"),
       desc=("A consistent surface makes your settings feel familiar sooner.", "Одинаковая поверхность — и настройки быстрее становятся привычными."),
       perk=("+0.12 settings comfort", "+0.12 к привычке к настройкам")),
    _i(key="tablet_overlay", category="setup", icon="📝", kind="owned", price=18, from_year=2008, needs=("tablet",), min_age=10,
       handler="comfort",
       name=("Tablet surface & nibs", "Покрытие и перья для планшета"),
       desc=("A better surface and a set of nibs: smoother, quieter, more predictable.", "Лучшее покрытие и набор перьев: плавнее, тише, предсказуемее."),
       perk=("+0.12 settings comfort", "+0.12 к привычке к настройкам")),
    _i(key="skates", category="setup", icon="🛼", kind="one_off", price=8, from_year=2008, cooldown=14, tiered=False,
       handler="skates", min_age=10,
       name=("Mouse skates / pen nibs", "Глайды для мыши / перья"),
       desc=("Fresh glides (or nibs) for the device you use. Cheap and noticeable.", "Свежие глайды (или перья) на ваше устройство. Дёшево и заметно."),
       perk=("-0.25 wear on your device", "-0.25 износа устройства")),
    _i(key="switches", category="setup", icon="⌨", kind="one_off", price=22, from_year=2008, cooldown=30, tiered=False,
       handler="switches", min_age=10,
       name=("Keyboard switches", "Свитчи для клавиатуры"),
       desc=("New switches and a clean-out. The keyboard feels new again.", "Новые свитчи и чистка. Клавиатура снова как новая."),
       perk=("-0.5 keyboard wear", "-0.5 износа клавиатуры")),
    _i(key="headphones", category="setup", icon="🎧", kind="owned", price=55, from_year=2008, min_age=10,
       name=("Noise-cancelling headphones", "Наушники с шумоподавлением"),
       desc=("You hear the rhythm, not the room.", "Вы слышите ритм, а не комнату."),
       mods={"skill_rhythm_reading": 1.02, "skill_low_mid_bpm": 1.01}, perk=("+2% rhythm reading", "+2% к ритмическому чтению")),
    _i(key="ups", category="setup", icon="🔋", kind="owned", price=38, from_year=2008, min_age=12,
       name=("Uninterruptible power supply", "Источник бесперебойного питания"),
       desc=("No more lost runs to a power flicker.", "Больше никаких потерянных попыток из-за моргнувшего света."),
       mods={"play": 1.01}, perk=("+1% to everything you play", "+1% ко всем вашим играм")),
    _i(key="wrist_rest", category="setup", icon="🧤", kind="owned", price=18, from_year=2008, min_age=10,
       name=("Wrist rest & desk setup", "Подставка под запястье и организация стола"),
       desc=("The wrist sits right, the shoulder relaxes.", "Запястье лежит правильно, плечо расслаблено."),
       mods={"injury": 0.92}, perk=("-8% RSI risk", "-8% риска травмы")),
    _i(key="internet_plan", category="setup", icon="📶", kind="one_off", price=0, from_year=2009, handler="isp", tiered=False,
       min_age=14,
       name=("Better internet plan", "Тариф интернета получше"),
       desc=("Lower ping in lobbies, duels and matches against far-away players.", "Меньший пинг в лобби, дуэлях и матчах с далёкими соперниками."),
       perk=("-30% latency per level (max 2)", "-30% задержки за уровень (максимум 2)")),
    _i(key="stream_kit", category="setup", icon="🎙", kind="owned", price=110, from_year=2011.5, needs=("streaming",), min_age=13,
       name=("Streaming kit", "Набор для стрима"),
       desc=("Webcam and a proper microphone. Streams look and sound like a show.", "Веб-камера и нормальный микрофон. Стрим выглядит и звучит как шоу."),
       mods={"income": 1.2, "followers_mult": 1.15}, perk=("+20% stream income, +15% followers from streams",
                                                          "+20% дохода со стрима, +15% подписчиков со стримов")),
    # --- community & career ------------------------------------------------------------------------------
    _i(key="supporter", category="career", icon="💖", kind="sub", price=4, from_year=2008, tiered=False, min_age=10,
       name=("osu!supporter", "osu!supporter"),
       desc=("Support the game and get osu!direct: maps and packs a click away.", "Поддержать игру и получить osu!direct: карты и паки в один клик."),
       mods={"pack": 1.08, "followers_mult": 1.03}, perk=("+8% training with ranked maps, +3% followers",
                                                          "+8% к тренировкам на ранкед-картах, +3% подписчиков")),
    _i(key="map_contest", category="career", icon="🗺", kind="one_off", price=40, from_year=2010, cooldown=60, min_age=14,
       handler="contest",
       name=("Sponsor a mapping contest", "Спонсировать конкурс маппинга"),
       desc=("Prize money for a community mapping contest. People remember who paid.", "Призовые для комьюнити-конкурса маппинга. Люди помнят, кто заплатил."),
       effects={"followers": 10, "morale": 3}, perk=("+reputation, +10 followers", "+репутация, +10 подписчиков")),
    _i(key="host_tournament", category="career", icon="🏆", kind="one_off", price=240, from_year=2010, cooldown=120,
       min_followers=20, min_age=15, handler="host",
       name=("Host a community tournament", "Организовать комьюнити-турнир"),
       desc=("Pay for the pool, the referees and the prizes. Big reputation, loud thread on the forum.",
             "Оплатить пул, судей и призы. Большая репутация и шумная тема на форуме."),
       effects={"followers": 60, "morale": 6}, perk=("+4 reputation, +60 followers, a forum thread",
                                                      "+4 репутации, +60 подписчиков, тема на форуме")),
    _i(key="lan_trip", category="career", icon="✈", kind="timed", price=210, from_year=2011, days=14, cooldown=45,
       needs=("tournament",), min_age=15, handler="lan",
       name=("Travel to the LAN finals", "Поездка на оффлайн-финал"),
       desc=("Fly out to play your registered tournament offline. Hotel and flights depend on how far you live.",
             "Лететь играть зарегистрированный турнир оффлайн. Отель и перелёт зависят от того, как далеко вы живёте."),
       mods={"skill_nerve_resistance": 1.05, "skill_clutch": 1.06}, effects={"followers": 30, "morale": 8},
       perk=("+5-6% nerves and clutch for 14 days, +30 followers, reputation",
             "+5-6% к нервам и клатчу на 14 дней, +30 подписчиков, репутация")),
    _i(key="agent", category="career", icon="💼", kind="sub", price=30, from_year=2011.5, max_rank=3000, min_age=16,
       name=("Agent / manager", "Агент / менеджер"),
       desc=("Someone who negotiates your sponsorships for a cut.", "Тот, кто выбивает вам спонсорские контракты за долю."),
       mods={"income": 1.2}, perk=("+20% sponsor and stream pay", "+20% к оплате спонсоров и стримов")),
    _i(key="clip_editor", category="career", icon="✂", kind="sub", price=14, from_year=2011.5, needs=("streaming",),
       min_followers=100, min_age=14,
       name=("Clip editor", "Монтажёр клипов"),
       desc=("Your best moments cut into clips that travel on their own.", "Лучшие моменты нарезаются в клипы, которые разлетаются сами."),
       mods={"followers_mult": 1.25}, perk=("+25% followers from streams", "+25% подписчиков со стримов")),
    # --- small things ----------------------------------------------------------------------------------------
    _i(key="coffee", category="treats", icon="☕", kind="one_off", price=3, from_year=2008, cooldown=2, tiered=False,
       handler="coffee", min_age=12,
       name=("Coffee / energy drink", "Кофе / энергетик"),
       desc=("A boost now and a crash tomorrow. Cheap, and not free.", "Бодрость сейчас и откат завтра. Дёшево, но не бесплатно."),
       effects={"fatigue": -8, "motivation": 2}, perk=("-8 fatigue today, a small crash tomorrow", "-8 усталости сегодня, лёгкий откат завтра")),
    _i(key="treat", category="treats", icon="🍰", kind="one_off", price=10, from_year=2008, cooldown=3, tiered=False,
       min_age=10,
       name=("Treat yourself", "Побаловать себя"),
       desc=("Something nice, just because the grind is long.", "Что-нибудь приятное просто потому, что грайнд долгий."),
       effects={"morale": 5, "motivation": 3}, perk=("+5 morale, +3 motivation", "+5 настроения, +3 мотивации")),
)

BY_KEY: dict[str, Item] = {i.key: i for i in CATALOG}
assert len(BY_KEY) == len(CATALOG)


def text(item: Item, lang: str) -> tuple[str, str, str]:
    i = 1 if lang == "ru" else 0
    return item.name[i], item.desc[i], item.perk[i]


def price_on(item: Item, on: date, occupation: str, region: str = "EU") -> int:
    """USD price now: era inflation, then your means, then travel for the LAN."""
    base = item.price * era_factor(on)
    if item.tiered:
        base *= TIER.get(occupation, 1.0)
    if item.handler == "lan":
        base *= REGION_TRAVEL.get(region, 1.0)
    return max(1, round(base))
