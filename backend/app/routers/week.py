"""Live a planned week in one go: each day is a drill, a play session, pool practice or rest."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.engine import simulation
from app.routers import career, play
from app.routers.players import get_player_or_404
from app.schemas import AutoSessionRequest, EventOut, PlayerOut, PoolPracticeRequest, RestRequest, ScoreOut, TrainRequest
from app.services import profile, tournaments

router = APIRouter(prefix="/api/players/{player_id}", tags=["week"])


class DayPlanIn(BaseModel):
    type: Literal["train", "session", "pool", "rest"]
    hours: float = Field(default=0, ge=0, le=16)
    drill: str | None = None
    preset: str | None = None
    stream: bool = False
    physio: bool = False
    tournament_id: int | None = None
    week: int | None = None


class WeekIn(BaseModel):
    days: list[DayPlanIn] = Field(min_length=1, max_length=14)


class DayOut(BaseModel):
    date: str
    type: str
    ok: bool
    summary: str
    events: list[EventOut] = []


class WeekOut(BaseModel):
    start_date: str
    end_date: str
    days: list[DayOut]
    stopped_early: str | None
    deltas: dict[str, float]
    scores: list[ScoreOut]
    money_change: float
    followers_change: int
    player: PlayerOut


def _run_day(db: Session, player_id: int, day: DayPlanIn):
    """Returns (summary, events, scores) using the same code paths as the single-day endpoints."""
    if day.type == "train":
        if not day.drill:
            raise HTTPException(422, "a training day needs a drill")
        out = career.train(player_id, TrainRequest(drill=day.drill, hours_per_day=day.hours, days=1), db)
        return f"{day.drill.replace('_', ' ')} {day.hours:g}h", out.events, out.scores
    if day.type == "rest":
        out = career.rest(player_id, RestRequest(days=1, physio=day.physio), db)
        return "rest" + (" + physio" if day.physio else ""), out.events, []
    if day.type == "pool":
        if day.tournament_id is None or day.week is None:
            raise HTTPException(422, "a pool day needs tournament_id and week")
        out = play.practice_pool(player_id, PoolPracticeRequest(tournament_id=day.tournament_id, week=day.week,
                                                                hours=day.hours, stream=day.stream), db)
    else:
        out = play.auto_session(player_id, AutoSessionRequest(preset=day.preset or "farm", hours=day.hours,
                                                              stream=day.stream), db)
    scores = [p.score for p in out.plays if p.score]
    passed = sum(1 for p in out.plays for a in p.attempts if a.passed)
    tries = sum(len(p.attempts) for p in out.plays)
    label = "pool practice" if day.type == "pool" else (day.preset or "farm")
    return f"{label} {out.hours:.1f}h, {passed}/{tries} passed", out.events, scores


@router.post("/week", response_model=WeekOut)
def live_week(player_id: int, body: WeekIn, db: Session = Depends(get_db)) -> WeekOut:
    player = get_player_or_404(db, player_id)
    start = player.in_game_date
    before = simulation.effective_values(player)
    money, followers = player.money, player.followers
    days: list[DayOut] = []
    scores: list[ScoreOut] = []
    stopped = None

    for day in body.days:
        db.refresh(player)
        deadline = tournaments.next_deadline(db, player)
        if deadline is not None and deadline <= player.in_game_date:
            stopped = f"tournament match on {deadline}: play it first"
            break
        today = player.in_game_date.isoformat()
        plan = day
        if player.injury == simulation.SEVERE_RSI and day.type != "rest":
            plan = DayPlanIn(type="rest", physio=day.physio)  # forced hiatus: the day becomes rest
        try:
            summary, events, day_scores = _run_day(db, player_id, plan)
        except HTTPException as e:
            days.append(DayOut(date=today, type=day.type, ok=False, summary=str(e.detail)))
            if e.status_code == 409 and "match" in str(e.detail):
                stopped = str(e.detail)
                break
            # Refused (free time, no maps, money for physio...): rest instead so the week still moves.
            try:
                summary, events, day_scores = _run_day(db, player_id, DayPlanIn(type="rest"))
                days[-1].summary += " → rested instead"
                days[-1].events = events
            except HTTPException as e2:
                stopped = str(e2.detail)
                break
            continue
        if plan is not day:
            summary = "forced rest (injury hiatus)"
        days.append(DayOut(date=today, type=plan.type, ok=True, summary=summary, events=events))
        scores += day_scores

    db.refresh(player)
    after = simulation.effective_values(player)
    return WeekOut(
        start_date=start.isoformat(), end_date=player.in_game_date.isoformat(), days=days, stopped_early=stopped,
        deltas={k: round(after[k] - before[k], 3) for k in after if abs(after[k] - before[k]) >= 0.005},
        scores=scores, money_change=round(player.money - money, 2), followers_change=player.followers - followers,
        player=profile.to_player_out(player),
    )

