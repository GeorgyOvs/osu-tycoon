"""Chat that answers what you actually said.

The player's message is classified (map advice, who to snipe, a provocation, a 1v1 challenge, gear,
skill advice, rank talk...) and the answer is built from real game data: maps that fit your level,
the NPCs holding #1 on boards you could take, your weakest skill and the drills that train it, the
named player's rank and mood. Provocations heat up rivalries and 1v1 invitations create real duels.
The same facts are handed to SillyTavern so the LLM replies grounded in them.
"""

import random
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import gear, simulation
from app.engine.training import available_drills
from app.models import Beatmap, BeatmapSet, MapBoard, MapScore, Npc, Player
from app.services import autoplay, duels, media, rivals

CYRILLIC = re.compile("[а-яё]", re.I)

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("duel", re.compile(r"\b(1v1|1 v 1|duel|bo[357]|fight me|challenge)\b|дуэл|вызыва|сыграем|1 на 1|один на один", re.I)),
    ("snipe", re.compile(r"snip|take (his|her|their|someone'?s) #?1|steal (a )?#?1|снайп|перебить скор|забрать топ", re.I)),
    ("recommend", re.compile(r"(what|which|any|some).{0,20}(play|farm|map|song|grind)|recommend|suggest|"
                             r"что (сыграть|поиграть|фармить|играть)|посоветуй|подскажи карт|какие карты|что фармить", re.I)),
    ("provoke", re.compile(r"\b(noob|trash|garbage|washed|overrated|bot|cheater|ez|cope|skill issue|mad|clown|"
                           r"i'?m better|better than (you|u|all)|you suck|you all suck|nobody can beat|bow down|"
                           r"i'?ll (beat|destroy|crush|take)|weak|dogwater)\b|"
                           r"лох|нуб|слабак|мусор|изи|я лучше|вы слабы|читер|бот\b|хуже меня|всех порву|клоун", re.I)),
    ("skill_help", re.compile(r"(how|tips?|advice|help).{0,30}(improve|get better|aim|stream|jump|read|acc|stamina|speed|consisten)|"
                              r"как (улучшить|прокачать|тренировать|стать лучше)|совет.{0,20}(аим|стрим|скорост|чтени)", re.I)),
    ("gear", re.compile(r"mouse|tablet|keyboard|monitor|pen\b|wacom|мышь|мышк|планшет|клавиатур|монитор", re.I)),
    ("rank", re.compile(r"\brank\b|\bpp\b|how (good|strong) am i|my level|мой ранг|мои pp|мой уровень|какой у меня", re.I)),
    ("greeting", re.compile(r"^\s*(hi|hello|hey|yo|o/|sup|привет|здарова|хай|здорово)\b", re.I)),
]

# Intent -> lines (en, ru). Placeholders are filled from the facts.
LINES = {
    "recommend_maps": (["try {map1}", "{map1} is nice for your level", "i'd go with {map1}, then {map2}", "{map2} is fun too",
                        "can't go wrong with {map1}"],
                       ["попробуй {map1}", "{map1} норм для твоего уровня", "я бы начал с {map1}, потом {map2}", "{map2} тоже приятная"]),
    "recommend_none": (["honestly just play what you enjoy, the pool is small right now", "farm whatever is newly ranked"],
                       ["играй что нравится, выбор пока небольшой", "фарми то, что недавно ранкнули"]),
    "snipe_target": (["{npc} has #1 on {map}, doesn't look that hard", "go for {map}, {npc} sits on top with {score}",
                      "{npc}'s score on {map} is beatable i think"],
                     ["у {npc} топ-1 на {map}, вроде не сложно", "бери {map}, {npc} сидит там с {score}"]),
    "snipe_names": (["try sniping {npc}, rank {rank} so not untouchable", "{npc} farms a lot of maps, check their scores"],
                    ["попробуй снайпнуть {npc}, ранг {rank}, не недосягаем", "{npc} много фармит, глянь его скоры"]),
    "provoke_rival": (["lol ok, talk is cheap {user}", "bold words for rank {rank}", "say that again in a 1v1", "sure buddy"],
                      ["ну-ну, слова ничего не стоят", "смелые слова для ранга {rank}", "повтори это в 1v1", "конечно, дружок"]),
    "provoke_named": (["{user}, you really want that smoke?", "keep talking, i'll remember this", "lol, see you on the leaderboard",
                       "that's cute coming from #{rank}"],
                      ["{user}, ты серьёзно?", "продолжай, я запомню", "ну увидимся на лидерборде", "забавно слышать это от #{rank}"]),
    "provoke_calm": (["relax, it's just a game lol", "don't tilt {user}", "nobody asked", "ok champ"],
                     ["расслабься, это просто игра", "не тильтуй, {user}", "тебя никто не спрашивал", "окей, чемпион"]),
    "provoke_gracious": (["haha, good energy, show it on the leaderboard", "confidence is good, results are better",
                          "i'd rather see the replay"],
                         ["хаха, отличный настрой, покажи на лидерборде", "уверенность это хорошо, результат лучше", "лучше покажи реплей"]),
    "duel_accept": (["sure {user}, check your duels, i sent the pool", "bo{bo}? you're on", "alright, pool's drawn, good luck"],
                    ["давай, {user}, загляни в дуэли, пул готов", "bo{bo}? принято", "ладно, пул выбран, удачи"]),
    "duel_decline": (["not now, maybe when you're closer in rank", "{why}", "busy grinding, ask me later"],
                     ["не сейчас, давай когда подтянешь ранг", "{why}", "занят грайндом, спроси позже"]),
    "duel_none": (["i'd play you but no one has good maps indexed yet lol", "ask me when the pool is ready"],
                  ["сыграл бы, но подходящих карт пока нет", "спроси, когда пул будет готов"]),
    "skill": (["your {skill} looks weakest, maybe try {drill}", "i'd work on {skill}: {drill} helps a lot",
               "{drill} fixed my {skill}"],
              ["у тебя слабее всего {skill}, попробуй {drill}", "я бы качал {skill}: {drill} сильно помогает"]),
    "gear": (["{item} is solid right now", "a lot of people use the {item} these days", "you can't go wrong with the {item}"],
             ["{item} сейчас хороший вариант", "многие сидят на {item}"]),
    "rank_self": (["you're #{rank} with {pp}pp, not bad", "{pp}pp is a decent base, keep grinding", "rank {rank} already? nice"],
                  ["у тебя #{rank} и {pp}pp, неплохо", "{pp}pp отличная база, продолжай", "уже ранг {rank}? круто"]),
    "rank_none": (["you're not ranked yet, set a few scores first", "play some maps and you'll get a rank"],
                  ["у тебя пока нет ранга, набей пару скоров", "сыграй пару карт и появится ранг"]),
    "greeting": (["o/", "hey {user}", "hi!", "yo {user}", "welcome", "sup"], ["привет!", "здарова, {user}", "о/", "хай"]),
}
GENERIC_Q = (["depends tbh", "no idea, sorry", "good question lol", "i think so? not sure", "it varies a lot"],
             ["зависит от ситуации", "без понятия, честно", "хороший вопрос", "кажется да, но не уверен"])
GENERIC_ACK = (["lol", "true", "same", "haha", "agreed", "yeah that's fair", "o.o", "fr"],
               ["лол", "точно", "ха-ха", "согласен", "ну да", "о.о"])


@dataclass
class Reply:
    intent: str
    lines: list[tuple[str, str]] = field(default_factory=list)  # (author, text)
    facts: dict = field(default_factory=dict)


def classify(text: str) -> str:
    for name, pattern in PATTERNS:
        if pattern.search(text):
            return name
    return "question" if "?" in text else "other"


def _find_named(db: Session, player: Player, text: str) -> Npc | None:
    lowered = text.lower()
    rows = db.execute(select(Npc.id, Npc.name).where(Npc.player_id == player.id)).all()
    best = None
    for npc_id, name in rows:
        n = name.lower()
        if len(n) >= 3 and re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", lowered):
            if best is None or len(name) > len(best[1]):
                best = (npc_id, name)
    return db.get(Npc, best[0]) if best else None


def _pick(rng: random.Random, pool: tuple[list[str], list[str]], ru: bool, k: int = 1) -> list[str]:
    options = pool[1] if ru else pool[0]
    return rng.sample(options, min(k, len(options)))


def _recommend(db: Session, player: Player, text: str, rng: random.Random) -> list[dict]:
    lowered = text.lower()
    key = "farm"
    for words, preset in ((("stream", "стрим", "bpm"), "streams"), (("jump", "прыж", "джамп"), "jumps"), (("low ar", "ридинг"), "lowar"),
                          (("hddt", "hd dt"), "hddt"), (("hdhr",), "hdhr"), ((" dt", "doubletime", "дт"), "doubletime"),
                          ((" hr", "hardrock", "хр"), "hardrock"), ((" hd", "hidden", "хд"), "hidden"),
                          (("new", "новые", "свеж"), "new_ranked"), (("push", "harder", "сложн"), "push")):
        if any(w in lowered for w in words):
            key = preset
            break
    preset = autoplay.PRESETS[key]
    if not autoplay.available(preset, player):
        preset = autoplay.PRESETS["farm"]
    try:
        maps = autoplay.select_maps(db, player, preset, 3, rng)
    except Exception:  # noqa: BLE001 - advice must never break the chat
        maps = []
    return [{"title": f"{b.beatmapset.artist} - {b.beatmapset.title} [{b.version}]", "stars": round(b.stars, 2),
             "mods": preset.mods or "NM", "beatmap_id": b.id} for b in maps]


def _snipe_targets(db: Session, player: Player, rng: random.Random) -> list[dict]:
    handled = autoplay.handled_stars(player, autoplay.PRESETS["push"])
    boards = list(db.scalars(select(MapBoard.beatmap_id).where(MapBoard.player_id == player.id).limit(80)))
    out = []
    for bid in boards:
        top = db.scalars(select(MapScore).where(MapScore.player_id == player.id, MapScore.beatmap_id == bid)
                         .order_by(MapScore.score.desc()).limit(1)).first()
        b = db.get(Beatmap, bid)
        if top is None or b is None or b.stars * autoplay.MIRROR_TO_STABLE > handled * 1.1:
            continue
        out.append({"npc": top.name, "map": f"{b.beatmapset.artist} - {b.beatmapset.title} [{b.version}]",
                    "score": f"{top.score:,}", "stars": round(b.stars, 2)})
    rng.shuffle(out)
    return out[:3]


def _near_npcs(db: Session, player: Player, rng: random.Random) -> list[dict]:
    rank = player.global_rank or 500_000
    rows = list(db.scalars(select(Npc).where(Npc.player_id == player.id, Npc.status == "active", Npc.rank.is_not(None),
                                             Npc.rank.between(max(1, rank // 3), rank * 3)).limit(40)))
    rng.shuffle(rows)
    return [{"npc": n.name, "rank": n.rank} for n in rows[:3]]


def _weakest_skill(player: Player) -> tuple[str, list[str]]:
    values = simulation.effective_values(player)
    weakest = min((k for k in values if k not in ("rsi_resistance", "hand_stamina", "visual_endurance")), key=values.get)
    drills = [d.label for d in available_drills(player.in_game_date) if weakest in d.targets][:2]
    return weakest, drills


def _gear_pick(player: Player, text: str) -> dict | None:
    lowered = text.lower()
    category = next((c for words, c in ((("tablet", "wacom", "pen", "планшет"), "tablet"), (("keyboard", "клавиатур"), "keyboard"),
                                        (("monitor", "монитор"), "monitor"), (("mouse", "мышь", "мышк"), "mouse")) if any(w in lowered for w in words)), "mouse")
    items = [i for i in gear.CATALOG.values() if i.category == category and i.available(player.in_game_date)
             and not i.discontinued(player.in_game_date)]
    if not items:
        return None
    best = max(items, key=lambda i: (i.aim - 1) + (i.tapping - 1) + 0.2 * (i.ergonomics or 0))
    return {"item": best.name, "category": category, "price": best.price_on(player.in_game_date)}


def build(db: Session, player: Player, channel: str, text: str, rng: random.Random, names: list[str],
          dm_with: str | None = None) -> Reply:
    """The grounded answer to `text`. Authors are channel regulars, or the named/addressed player."""
    ru = bool(CYRILLIC.search(text)) or channel == "#russian"
    intent = classify(text)
    named = _find_named(db, player, text) if not dm_with else db.scalar(select(Npc).where(Npc.player_id == player.id, Npc.name == dm_with))
    user = player.name
    reply = Reply(intent)
    if named:
        reply.facts["addressed"] = {"name": named.name, "rank": named.rank, "country": named.country, "status": named.status,
                                    "attitude": media._attitude(named)}
    regular = lambda: rng.choice(names or ["anon"])  # noqa: E731

    def say(author: str, pool, **kw) -> None:
        for line in _pick(rng, pool, ru):
            reply.lines.append((author, line.format(user=user, **kw)))

    if intent == "recommend":
        maps = _recommend(db, player, text, rng)
        reply.facts["maps"] = maps
        if maps:
            m = [x["title"] + (f" +{x['mods']}" if x["mods"] != "NM" else "") + f" ({x['stars']}★)" for x in maps]
            reply.lines.append((regular(), rng.choice(LINES["recommend_maps"][1 if ru else 0]).format(
                map1=m[0], map2=m[1] if len(m) > 1 else m[0])))
            if len(m) > 2 and rng.random() < 0.6:
                reply.lines.append((regular(), (f"а ещё {m[2]}" if ru else f"also {m[2]}")))
        else:
            say(regular(), LINES["recommend_none"])
    elif intent == "snipe":
        targets = _snipe_targets(db, player, rng)
        reply.facts["snipe_targets"] = targets
        if targets:
            t = targets[0]
            reply.lines.append((regular(), rng.choice(LINES["snipe_target"][1 if ru else 0]).format(**t)))
        else:
            near = _near_npcs(db, player, rng)
            reply.facts["near_players"] = near
            if near:
                reply.lines.append((regular(), rng.choice(LINES["snipe_names"][1 if ru else 0]).format(npc=near[0]["npc"], rank=near[0]["rank"])))
            else:
                say(regular(), LINES["recommend_none"])
    elif intent == "provoke":
        rival = None
        if named:
            rival = rivals.rival_for(db, player, named.id)
        else:
            active = rivals.active(db, player)
            rival = max(active, key=lambda r: r.heat) if active else None
            named = db.get(Npc, rival.npc_id) if rival else None
        rank = (named.rank if named else None) or player.global_rank or "?"
        if named:
            comps = media._attitude(named)
            pool = LINES["provoke_gracious"] if comps.startswith("Gracious") else (LINES["provoke_named"] if rival else LINES["provoke_calm"])
            say(named.name, pool, rank=rank)
            if rival:
                rivals.bump(rival, 5.0)
                reply.facts["rival_heat_up"] = named.name
        else:
            say(regular(), LINES["provoke_calm"], rank=rank)
        if rng.random() < 0.5:
            say(regular(), LINES["provoke_calm"], rank=rank)
    elif intent == "duel":
        target = named
        if target is None:
            active = rivals.active(db, player)
            target = db.get(Npc, active[0].npc_id) if active else None
        if target is None:
            say(regular(), GENERIC_Q)
        else:
            bo = 5 if 5 in duels.FORMATS else duels.FORMATS[0]
            try:
                duel = duels.challenge(db, player, target.id, bo, "friendly", "even", 1)
                reply.facts["duel_created"] = {"opponent": target.name, "id": duel.id, "best_of": bo}
                say(target.name, LINES["duel_accept"], bo=bo)
            except duels.DuelError as e:
                reply.facts["duel_declined"] = {"opponent": target.name, "why": str(e)}
                why = str(e).split(": ", 1)[-1] if e.status_code == 409 else ""
                pool = LINES["duel_none"] if "maps" in str(e).lower() else LINES["duel_decline"]
                say(target.name, pool, why=why if not ru else "не сейчас")
    elif intent == "skill_help":
        skill, drills = _weakest_skill(player)
        label = A.SUBSTATS[skill].label
        reply.facts["weakest_skill"] = {"skill": label, "drills": drills}
        say(regular(), LINES["skill"], skill=label.lower(), drill=drills[0] if drills else "playing ranked maps")
    elif intent == "gear":
        pick = _gear_pick(player, text)
        reply.facts["gear"] = pick
        if pick:
            say(regular(), LINES["gear"], item=pick["item"])
        else:
            say(regular(), GENERIC_Q)
    elif intent == "rank":
        reply.facts["player_rank"] = {"rank": player.global_rank, "pp": round(player.total_pp)}
        if player.global_rank:
            say(regular(), LINES["rank_self"], rank=f"{player.global_rank:,}", pp=f"{player.total_pp:,.0f}")
        else:
            say(regular(), LINES["rank_none"])
    elif intent == "greeting":
        say(named.name if named else regular(), LINES["greeting"])
    elif intent == "question":
        say(named.name if named else regular(), GENERIC_Q)
    else:
        say(named.name if named else regular(), GENERIC_ACK)
    return reply
