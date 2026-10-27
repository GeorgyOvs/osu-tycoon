from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import func, select, text

from app.config import CORS_ORIGINS
from app.db import SessionLocal, init_db
from app.models import Player
from app.routers import spending, hints, profile_page, search, integrity as integrity_router
from app.routers import beatmaps, career, duels, events, goals, life, play, players, pp, social, teams, week, world
from app.routers import legacy as legacy_router
from app.routers import backup as backup_router
from app.routers import client, osu_api, real
from app.routers import notifications as notifications_router
from app.services import beatmap_index, tournaments, world_service, score_records


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        world_service.prune_removed_legends(db)
        tournaments.dedupe(db)
        db.flush()
        db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_tournament_slot ON tournaments(player_id, template, start_date)"))
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
app.include_router(backup_router.router)
app.include_router(spending.router)
app.include_router(hints.router)
app.include_router(profile_page.router)
app.include_router(notifications_router.router)
app.include_router(search.router)
app.include_router(career.router)
app.include_router(beatmaps.router)
app.include_router(play.router)
app.include_router(world.router)
app.include_router(social.router)
app.include_router(social.bridge)
app.include_router(life.router)
app.include_router(week.router)
app.include_router(duels.router)
app.include_router(integrity_router.router)
from app.routers import mentors as mentors_router  # noqa: E402

app.include_router(mentors_router.router)
app.include_router(events.router)
app.include_router(goals.router)
app.include_router(teams.router)
app.include_router(legacy_router.router)
app.include_router(legacy_router.hall)
app.include_router(real.router)
app.include_router(client.router)
app.include_router(client.players_router)
app.include_router(osu_api.early)
app.include_router(osu_api.router)


@app.middleware("http")
async def strip_api_v2_trailing_slash(request, call_next):
    # lazer asks for "me/" and "users/{id}/" when no ruleset is chosen yet; a redirect would drop its Authorization
    # header (HTTP clients don't forward it), so route those paths directly instead.
    path = request.scope["path"]
    if path.startswith("/api/v2/") and path.endswith("/"):
        request.scope["path"] = path.rstrip("/")
    return await call_next(request)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
