from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.players import get_player_or_404
from app.services import integrity, setup

router = APIRouter(prefix="/api/players/{player_id}", tags=["integrity"])
Lang = Query(default="en", pattern="^(en|ru)$")


class OptionOut(BaseModel):
    key: str
    label: str
    hint: str


class CaseOut(BaseModel):
    id: int
    kind: str
    title: str
    body: str
    status: str
    opened: str
    expires: str
    resolved: str | None
    days_left: int | None
    response: str | None
    outcome: str
    auto: bool
    rep_delta: float
    restricted_days: int | None
    options: list[OptionOut]


class FactorOut(BaseModel):
    kind: str
    level: float


class SuspicionOut(BaseModel):
    level: float
    factors: list[FactorOut]


class LogOut(BaseModel):
    date: str
    delta: float
    reason: str


class IntegrityOut(BaseModel):
    reputation: float
    label: str
    restricted_until: str | None
    effects: dict[str, float]
    suspicion: SuspicionOut
    open: list[CaseOut]
    history: list[CaseOut]
    log: list[LogOut]


class RespondIn(BaseModel):
    choice: str


@router.get("/integrity", response_model=IntegrityOut)
def get_integrity(player_id: int, lang: str = Lang, db: Session = Depends(get_db)) -> IntegrityOut:
    return IntegrityOut(**integrity.overview(db, get_player_or_404(db, player_id), lang))


@router.post("/integrity/cases/{case_id}/respond", response_model=IntegrityOut)
def respond(player_id: int, case_id: int, body: RespondIn, lang: str = Lang,
            db: Session = Depends(get_db)) -> IntegrityOut:
    player = get_player_or_404(db, player_id)
    try:
        integrity.respond(db, player, case_id, body.choice)
    except integrity.IntegrityError as e:
        db.rollback()
        raise HTTPException(e.status_code, str(e)) from e
    db.commit()
    return IntegrityOut(**integrity.overview(db, player, lang))


# --- setup condition: gear wear, settings comfort, connection ---------------------------------


class WearOut(BaseModel):
    category: str
    item: str | None
    active: bool
    wear: float
    condition: str
    penalty: float
    service_cost: float
    replace_cost: int | None


class NetworkOut(BaseModel):
    region: str
    region_name: str
    local_ping: int
    lobby_ping: int
    tier: str
    isp_level: int
    isp_max: int
    isp_price: float | None
    pressure_penalty: float
    regional_servers: bool


class SetupOut(BaseModel):
    wear: list[WearOut]
    comfort: float
    comfort_penalty: float
    network: NetworkOut
    money: float


class CategoryIn(BaseModel):
    category: str


@router.get("/setup", response_model=SetupOut)
def get_setup(player_id: int, db: Session = Depends(get_db)) -> SetupOut:
    return SetupOut(**setup.overview(db, get_player_or_404(db, player_id)))


def _act(player_id: int, db: Session, fn) -> SetupOut:
    player = get_player_or_404(db, player_id)
    try:
        fn(player)
    except setup.SetupError as e:
        db.rollback()
        raise HTTPException(e.status_code, str(e)) from e
    db.commit()
    return SetupOut(**setup.overview(db, player))


@router.post("/setup/maintain", response_model=SetupOut)
def maintain(player_id: int, body: CategoryIn, db: Session = Depends(get_db)) -> SetupOut:
    return _act(player_id, db, lambda p: setup.maintain(db, p, body.category))


@router.post("/setup/replace", response_model=SetupOut)
def replace(player_id: int, body: CategoryIn, db: Session = Depends(get_db)) -> SetupOut:
    return _act(player_id, db, lambda p: setup.replace(db, p, body.category))


@router.post("/setup/isp", response_model=SetupOut)
def upgrade_isp(player_id: int, db: Session = Depends(get_db)) -> SetupOut:
    return _act(player_id, db, lambda p: setup.upgrade_isp(p))
