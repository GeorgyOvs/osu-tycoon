"""Background download of popular maps of the in-game era, so the world has maps its players can score on.

NPC world scores only use maps whose .osu file is already cached. Without this, a fresh install has a
handful of cached maps and the forum stays quiet; with it the pool of playable maps grows by itself.
"""

import logging
import threading
import time

from app.config import OSU_CACHE_DIR
from app.services import osu_files

log = logging.getLogger(__name__)

DELAY_SECONDS = 1.0  # be polite to osu.ppy.sh
MAX_QUEUE = 40


class Prefetcher:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: list[int] = []
        self._missing: set[int] = set()
        self._running = False

    def request(self, beatmap_ids: list[int]) -> int:
        with self._lock:
            fresh = [i for i in beatmap_ids if i not in self._missing and i not in self._queue
                     and not (OSU_CACHE_DIR / f"{i}.osu").exists()]
            self._queue.extend(fresh[: max(0, MAX_QUEUE - len(self._queue))])
            if self._queue and not self._running:
                self._running = True
                threading.Thread(target=self._run, name="map-prefetch", daemon=True).start()
            return len(fresh)

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._running = False
                    return
                beatmap_id = self._queue.pop(0)
            try:
                osu_files.get_osu_file(beatmap_id)
            except osu_files.BeatmapNotFound:
                with self._lock:
                    self._missing.add(beatmap_id)
            except Exception:  # noqa: BLE001 - a background helper must never die loudly
                log.exception("map prefetch failed for %s", beatmap_id)
            time.sleep(DELAY_SECONDS)


prefetcher = Prefetcher()
