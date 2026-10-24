"""1v1 duels: friendly or rival showmatches against any player in your world.

Same engine as tournament matches: a pool sized for the format (BO1 to BO13), bans and
alternating picks (yours or the AI's), a tiebreaker at match point, and every map simulated
note by note for both players. Skill decides most of it; form, map knowledge, nerves and
plain luck decide the rest.
"""

import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import match, simulation, world
from app.models import Duel, Npc, Player
from app.services import condition, media, osu_files, rivals, sessions, tournaments

FORMATS = (1, 3, 5, 7, 9, 11, 13)
DIFFICULTY = {"comfortable": 0.78, "even": 0.9, "hard": 1.0}  # pool stars vs. the players' average level
MAX_DUELS_PER_DAY = 3
FRIENDLY_RANK_GAP = 20  # without a rivalry, players this many times above you rarely accept
NOTABLE_RANK = 1000


class DuelError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def pool_layout(best_of: int) -> list[str]:
    if best_of == 1:
        return ["NM1", "NM2", "HD1", "HR1", "DT1"]
    if best_of <= 3:
        return ["NM1", "NM2", "NM3", "HD1", "HR1", "DT1", "DT2", "TB"]
    return match.SMALL_POOL if best_of <= 7 else match.BIG_POOL


def handled_stars(overall: float) -> float:
    return 2 * (0.6 + 0.04 * overall)


def _user_overall(db: Session, player: Player) -> float:
    return A.overall(condition.play_skills(db, player))


def _expire_old(db: Session, player: Player) -> None:
    for d in db.scalars(select(Duel).where(Duel.player_id == player.id, Duel.status == "pending",
                                           Duel.date < player.in_game_date)):
        d.status = "expired"


def challenge(db: Session, player: Player, npc_id: int, best_of: int, kind: str, difficulty: str,
              bans_per_side: int) -> Duel:
    """Ask an NPC for a 1v1. On acceptance the pool is drawn and shown before playing."""
    _expire_old(db, player)
    if best_of not in FORMATS:
        raise DuelError(422, f"format must be one of BO{', BO'.join(map(str, FORMATS))}")
    if kind not in ("friendly", "rival") or difficulty not in DIFFICULTY or not 0 <= bans_per_side <= 2:
        raise DuelError(422, "kind: friendly|rival, difficulty: comfortable|even|hard, bans per side: 0-2")
    if player.injury == simulation.SEVERE_RSI:
        raise DuelError(409, "you're on a forced hiatus")
    played_today = db.scalar(select(func.count()).select_from(Duel).where(
        Duel.player_id == player.id, Duel.date == player.in_game_date, Duel.status != "expired")) or 0
    if played_today >= MAX_DUELS_PER_DAY:
        raise DuelError(409, f"that's {MAX_DUELS_PER_DAY} 1v1s today already; your hands need a break")

    npc = db.get(Npc, npc_id)
    if npc is None or npc.player_id != player.id:
        raise DuelError(404, "no such player in this world")
    if npc.status != "active":
        raise DuelError(409, f"{npc.name} isn't available ({npc.status})")

    rival = rivals.rival_for(db, player, npc.id)
    if kind == "rival" and rival is None:
        raise DuelError(409, f"{npc.name} isn't your rival (yet)")
    mine = player.global_rank or 2_000_000
    gap = max(npc.rank or mine, mine) / max(1, min(npc.rank or mine, mine))
    rng = random.Random(f"{player.seed}:duel:{player.in_game_date.isoformat()}:{npc.id}")
    if rival is None and gap > FRIENDLY_RANK_GAP and rng.random() > FRIENDLY_RANK_GAP / gap:
        rivals.dm(db, player, npc, "decline", player.in_game_date)
        raise DuelError(409, f"{npc.name} declined: they don't usually play 1v1s with someone {gap:.0f}x lower ranked")

    level = (handled_stars(_user_overall(db, player)) + handled_stars(npc.overall)) / 2
    stars = round(level * DIFFICULTY[difficulty] * 1.05, 2)  # mirror stars run ~5% above stable
    slots = [match.Slot(name, stars + (0.25 if name == "TB" else 0.0)) for name in pool_layout(best_of)]
    try:
        tournaments.fill_slots(db, slots, player.in_game_date, rng)
    except tournaments.TournamentError as e:
        raise DuelError(409, str(e)) from e

    duel = Duel(player_id=player.id, npc_id=npc.id, date=player.in_game_date, kind=kind, best_of=best_of,
                bans_per_side=bans_per_side, difficulty=difficulty, status="pending",
                pool=[vars(s) for s in slots], maps=[], score_user=0, score_npc=0, won=None)
    db.add(duel)
    db.flush()
    return duel


def _npc_competitor(npc: Npc) -> tournaments._Competitor:
    from app.engine import play

    comps = world.composites(npc.overall, npc.style)
    return tournaments._Competitor(npc.name, npc.kind, world.substats(comps, npc.seed), npc.form,
                                   play.DayModifiers(form=npc.form), npc.seed, npc.id)


def _user_competitor(db: Session, player: Player) -> tournaments._Competitor:
    day = sessions.day_modifiers(player)
    day.morale = player.morale
    return tournaments._Competitor(player.name, "user", condition.play_skills(db, player), player.form, day,
                                   player.seed, None)


def play_duel(db: Session, player: Player, duel: Duel, strategy: dict[str, list[str]] | None = None) -> Duel:
    _expire_old(db, player)
    if duel.status != "pending":
        raise DuelError(409, f"this 1v1 is {duel.status}")
    if player.injury == simulation.SEVERE_RSI:
        raise DuelError(409, "you're on a forced hiatus")
    npc = db.get(Npc, duel.npc_id)
    pool = [match.Slot(**s) for s in duel.pool]
    # Pool maps can vanish between drawing and playing; redraw those slots.
    for s in pool:
        try:
            osu_files.get_osu_file(s.beatmap_id)
        except osu_files.BeatmapNotFound:
            s.beatmap_id, s.title = None, ""
    if any(not s.beatmap_id for s in pool):
        tournaments.fill_slots(db, pool, player.in_game_date, random.Random(f"{player.seed}:duel-redraw:{duel.id}"))

    advantage, play_map = tournaments.map_simulator(db, player, [_user_competitor(db, player)],
                                                    [_npc_competitor(npc)], seed_key=f"duel:{duel.id}")
    rng = random.Random(f"{player.seed}:duel-match:{duel.id}")
    first_to = (duel.best_of + 1) // 2
    outcome = match.run_match(pool, first_to, advantage, play_map, rng, bans_per_side=duel.bans_per_side,
                              prefs={"a": strategy} if strategy else None)

    won = outcome.winner == "a"
    duel.status, duel.won = "played", won
    duel.score_user, duel.score_npc = outcome.score_a, outcome.score_b
    duel.pool = [vars(s) for s in pool]
    duel.maps = [{"slot": r.slot, "picked_by": r.picked_by, "score_a": r.score_a, "score_b": r.score_b, **r.detail}
                 for r in outcome.maps] + [{"bans": outcome.bans}]

    # Consequences: tired hands, morale, the rivalry, a DM, and the story for SillyTavern.
    stakes = 2.0 if duel.kind == "rival" else 1.0
    player.fatigue = A.clamp(player.fatigue + 1 + 0.5 * len(outcome.maps), 0, 100)
    player.morale = A.clamp(player.morale + (3 if won else -2) * stakes, 0, 100)
    player.motivation = A.clamp(player.motivation + (1.5 if won else -0.5), 0, 100)
    rivals.on_match(db, player, [npc.id], won)
    if rivals.rival_for(db, player, npc.id) is None:
        rivals.dm(db, player, npc, "match_won" if won else "match_lost", player.in_game_date)
    media.duel_result(db, player, npc, duel, notable=npc.kind == "legend" or (
        npc.rank is not None and npc.rank <= NOTABLE_RANK and (player.global_rank or 10**9) <= NOTABLE_RANK))
    db.flush()
    return duel


def history(db: Session, player: Player, limit: int = 20) -> list[Duel]:
    return list(db.scalars(select(Duel).where(Duel.player_id == player.id, Duel.status == "played")
                           .order_by(Duel.id.desc()).limit(limit)))

