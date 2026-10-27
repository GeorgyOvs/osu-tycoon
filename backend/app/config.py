import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("TYCOON_DATA_DIR", BASE_DIR / "data"))
OSU_CACHE_DIR = DATA_DIR / "osu_files"
DATABASE_URL = os.getenv("TYCOON_DATABASE_URL", f"sqlite:///{DATA_DIR / 'tycoon.db'}")

OSU_FILE_URL = "https://osu.ppy.sh/osu/{beatmap_id}"
# Where the tycoon client reaches this backend (used in links it follows by itself, like avatars).
PUBLIC_URL = os.getenv("TYCOON_PUBLIC_URL", "http://127.0.0.1:8642")
MIRROR_BEATMAP_URL = "https://catboy.best/api/v2/b/{beatmap_id}"
# Search mirror: supports sorting by ranked_date and deep pagination.
MIRROR_API_URL = "https://osu.direct/api"
# Where the tycoon client downloads beatmap sets (lazer asks the API; the backend redirects here).
MIRROR_DOWNLOAD_URL = "https://catboy.best/d/{beatmapset_id}"
USER_AGENT = "osu-tycoon/0.1 (local game engine)"

# Stable-era scoring: the game simulates 2007-2024 osu!stable, not lazer.
PP_LAZER = False

TOP_PLAYS_LIMIT = 100
PP_WEIGHT_DECAY = 0.95

# Browser origins allowed to call the API: the Vite dev server and SillyTavern (default port 8000).
CORS_ORIGINS = os.getenv(
    "TYCOON_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
).split(",")
