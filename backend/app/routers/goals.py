from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Goal
from app.routers.players import get_player_or_404
from app.services import goals, story

router = APIRouter(prefix="/api/players/{player_id}/goals", tags=["goals"])


class GoalOut(BaseModel):
    id: int
    key: str
    title: str
    description: str
    status: str
    progress: float
    created_on: str
    deadline: str | None
    days_left: int | None
    finished_on: str | None
    reward: dict
    inspired: bool


class ChapterOut(BaseModel):
    date: str
    text: str


class ArcOut(BaseModel):
    id: int
    key: str
    title: str
    status: str
    started_on: str
    ended_on: str | None
    chapters: list[ChapterOut]


class GoalsOut(BaseModel):
    active: list[GoalOut]
    finished: list[GoalOut]
    arcs: list[ArcOut]


@router.get("", response_model=GoalsOut)
def get_goals(player_id: int, lang: str = Query(default="en", pattern="^(en|ru)$"),
              db: Session = Depends(get_db)) -> GoalsOut:
    player = get_player_or_404(db, player_id)
    if not db.scalar(select(func.count()).select_from(Goal).where(Goal.player_id == player.id)):
        goals.tick(db, player, [])  # a new career gets its first goals on first look
        db.commit()
    return GoalsOut(**goals.overview(db, player, lang))


@router.post("/{goal_id}/drop", response_model=GoalsOut)
def drop_goal(player_id: int, goal_id: int, lang: str = Query(default="en", pattern="^(en|ru)$"),
              db: Session = Depends(get_db)) -> GoalsOut:
    player = get_player_or_404(db, player_id)
    goal = db.scalar(select(Goal).where(Goal.id == goal_id, Goal.player_id == player.id))
    if goal is None:
        raise HTTPException(404, f"goal {goal_id} not found")
    if goal.status != "active":
        raise HTTPException(409, "this goal is already finished")
    goal.status, goal.finished_on = "dropped", player.in_game_date
    story.put(player, "goals_checked_on", "")  # let the next tick propose a replacement
    goals.tick(db, player, [])
    db.commit()
    return GoalsOut(**goals.overview(db, player, lang))
