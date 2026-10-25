"""Calendar actions: every action advances the in-game date."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.engine import simulation
from dataclasses import replace

from sqlalchemy import select

from app.engine import attributes as A
from app.engine.training import DRILLS, ERA_ORDER, Drill
from app.models import Player
from app.routers.players import get_player_or_404
from app.schemas import ActionResultOut, DrillOut, EventOut, RestRequest, TrainRequest
from app.models import Npc, Score
from app.schemas import ScoreOut
from app.services import (
    autoplay,
    beatmap_index,
    condition,
    profile_stats,
    life,
    media,
    profile,
    sessions,
    tournaments,
    world_service,
)

router = APIRouter(prefix="/api/players/{player_id}", tags=["career"])


def _drill_out(drill: Drill, player: Player) -> DrillOut:
    return DrillOut(
        key=drill.key,
        label=drill.label,
        description=drill.description,
        targets=drill.targets,
        strain=drill.strain,
        efficiency=drill.efficiency(player.in_game_date),
        available=drill.available(player.in_game_date),
        available_from=drill.available_from.value,
        sets_scores=drill.ranked_preset is not None,
    )


def days_until_match(db: Session, player: Player, days: int) -> int:
    """Cap a multi-day action so it stops on the day of the user's next tournament match."""
    world_service.ensure_world(db, player)
    tournaments.forfeit_if_unable(db, player)
    deadline = tournaments.next_deadline(db, player)
    if deadline is None:
        return days
    if deadline <= player.in_game_date:
        raise HTTPException(409, "you have a tournament match today; play it first")
    return min(days, (deadline - player.in_game_date).days)


def world_events(news: list[tournaments.News]) -> list[EventOut]:
    return [EventOut(date=n.date, type=f"WORLD_{n.type}", message=n.message, data=n.data) for n in news]


def _train_with_plays(
    db: Session, player: Player, plan: simulation.DayPlan, days: int
) -> tuple[simulation.ActionResult, list[Score]]:
    """Map-playing drills: each day a few ranked maps are really played (and can set scores)."""
    assert plan.drill is not None and plan.drill.ranked_preset
    start, before = player.in_game_date, simulation.effective_values(player)
    events: list[simulation.Event] = []
    scores: list[Score] = []
    simulated = 0
    for i in range(days):
        if i and player.injury == simulation.SEVERE_RSI:
            events.append(simulation.Event(player.in_game_date, "TRAINING_INTERRUPTED",
                                           "Training stopped: forced hiatus.", {"days_lost": days - i}))
            break
        if player.injury != simulation.SEVERE_RSI:
            try:
                requests = autoplay.training_plays(db, player, plan.drill.ranked_preset)
                played = sessions.play_maps(db, player, requests, tag="training")
                scores += [p.recorded.score for p in played.plays if p.recorded]
            except sessions.SessionError:
                pass  # no suitable maps indexed yet: the day is pure practice
        day = simulation.run_days(player, plan, 1)
        events += day.events
        simulated += day.days
    after = simulation.effective_values(player)
    deltas = {k: after[k] - before[k] for k in after if abs(after[k] - before[k]) >= 0.005}
    return simulation.ActionResult(start, player.in_game_date, simulated, events, deltas), scores


def _run(db: Session, player: Player, plan: simulation.DayPlan, days: int) -> ActionResultOut:
    days = days_until_match(db, player, days)
    try:
        life.check_hours(player, plan.hours, days)
    except life.LifeError as e:
        raise HTTPException(e.status_code, str(e)) from e
    rank_before = player.global_rank
    scores: list[Score] = []
    try:
        if plan.drill and plan.drill.ranked_preset:
            result, scores = _train_with_plays(db, player, plan, days)
        else:
            result = simulation.run_days(player, plan, days)
    except simulation.TrainingBlocked as e:
        raise HTTPException(409, str(e)) from e
    result.events += life.apply_days(player, result.start_date, result.end_date, plan.hours if plan.is_training else 0)
    if plan.is_training:
        condition.progress_adaptation(player, plan.hours * result.days)
        if not (plan.drill and plan.drill.ranked_preset):  # map-playing drills count their own attempts
            profile_stats.add_play(player, plan.hours * result.days * 3600 * 0.8)
    news = world_service.advance(db, player)
    media.after_action(db, player, rank_before, result.events, news)
    db.commit()
    beatmap_index.syncer.request(player.in_game_date)
    return ActionResultOut(
        start_date=result.start_date,
        end_date=result.end_date,
        days=result.days,
        events=[EventOut(date=e.date, type=e.type, message=e.message, data=e.data) for e in result.events]
        + world_events(news),
        deltas=result.deltas,
        player=profile.to_player_out(player),
        scores=[ScoreOut.model_validate(s) for s in scores],
    )


def _replay_drill(db: Session, player: Player, drill: Drill) -> Drill:
    """Replays teach most when the players you watch are far above you."""
    world_service.ensure_world(db, player)
    top = [n.overall for n in db.scalars(
        select(Npc).where(Npc.player_id == player.id, Npc.rank.is_not(None)).order_by(Npc.pp.desc()).limit(10))]
    gap = (sum(top) / len(top) if top else 80) - A.overall(simulation.effective_values(player))
    factor = max(0.3, min(1.4, 0.4 + gap / 50))
    return replace(drill, era_efficiency={era: factor for era in ERA_ORDER})


def _lobby_drill(player: Player, drill: Drill) -> Drill:
    """Public lobbies are played across regions: a high ping makes them less useful."""
    from app.engine import network
    from app.services import setup

    ms = network.lobby_ping(network.region(player.country), player.in_game_date.year, setup.isp_level(player))
    factor = max(0.7, 1 - 1.5 * (network.pressure_factor(ms) - 1))
    return replace(drill, era_efficiency={era: drill.efficiency(player.in_game_date) * factor for era in ERA_ORDER})


@router.get("/drills", response_model=list[DrillOut])
def list_drills(player_id: int, db: Session = Depends(get_db)) -> list[DrillOut]:
    player = get_player_or_404(db, player_id)
    return [_drill_out(d, player) for d in DRILLS.values()]


@router.post("/train", response_model=ActionResultOut)
def train(player_id: int, body: TrainRequest, db: Session = Depends(get_db)) -> ActionResultOut:
    player = get_player_or_404(db, player_id)
    drill = DRILLS.get(body.drill)
    if drill is None:
        raise HTTPException(422, f"unknown drill '{body.drill}'")
    if drill.key == "watch_replays":
        drill = _replay_drill(db, player, drill)
    if drill.key == "multiplayer_lobbies":
        drill = _lobby_drill(player, drill)
    learning, caps = condition.learning_extras(db, player)
    plan = simulation.DayPlan(drill=drill, hours=body.hours_per_day, learning=learning, caps=caps)
    return _run(db, player, plan, body.days)


@router.post("/rest", response_model=ActionResultOut)
def rest(player_id: int, body: RestRequest, db: Session = Depends(get_db)) -> ActionResultOut:
    player = get_player_or_404(db, player_id)
    if body.physio:
        try:
            condition.pay_physio(player, days_until_match(db, player, body.days))
        except condition.ShopError as e:
            raise HTTPException(e.status_code, str(e)) from e
    return _run(db, player, simulation.DayPlan(physio=body.physio), body.days)
