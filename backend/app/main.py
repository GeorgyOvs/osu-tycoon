from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import func, select

from app.config import CORS_ORIGINS
from app.db import SessionLocal, init_db
from app.models import Player
from app.routers import beatmaps, career, duels, life, play, players, pp, social, week, world
from app.services import beatmap_index, world_service, score_records


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        world_service.prune_removed_legends(db)
        score_records.repair_legacy_records(db)
        db.commit()
        # Resume indexing beatmaps up to the furthest career date.
        latest = db.scalar(select(func.max(Player.in_game_date)))
    if latest is not None:
        beatmap_index.syncer.request(latest)
    yield
    beatmap_index.syncer.stop()


app = FastAPI(title="osu! Tycoon Engine", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(pp.router)
app.include_router(players.router)
app.include_router(career.router)
app.include_router(beatmaps.router)
app.include_router(play.router)
app.include_router(world.router)
app.include_router(social.router)
app.include_router(social.bridge)
app.include_router(life.router)
app.include_router(week.router)
app.include_router(duels.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
