"""Local SQLite index of ranked beatmaps, crawled from the mirror oldest-first.

The crawl only needs to reach the latest in-game date of any career, so a 2010 career
indexes a few thousand sets instead of the whole ranked history.
"""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import SessionLocal
from app.models import Beatmap, BeatmapSet, SyncState
from app.services import mirror

log = logging.getLogger(__name__)

SYNC_STATUSES = (mirror.STATUS_RANKED, mirror.STATUS_APPROVED)
PAGE_DELAY_SECONDS = 0.3  # be polite to the mirror


def upsert_set(db: Session, data: mirror.BeatmapSetData) -> BeatmapSet | None:
    """Store a set and its osu!standard difficulties. Skips sets that can't be played for PP."""
    if data.ranked_date is None or not data.beatmaps or data.status not in mirror.PP_STATUSES:
        return None

    bset = db.get(BeatmapSet, data.id)
    if bset is None:
        bset = BeatmapSet(id=data.id)
        db.add(bset)
    bset.artist = data.artist
    bset.title = data.title
    bset.creator = data.creator
    bset.source = data.source
    bset.tags = data.tags[:2048]
    bset.status = data.status
    bset.ranked_date = data.ranked_date
    bset.play_count = data.play_count
    bset.favourite_count = data.favourite_count
    bset.bpm = data.bpm

    existing = {b.id: b for b in bset.beatmaps}
    for bd in data.beatmaps:
        b = existing.get(bd.id) or db.get(Beatmap, bd.id)
        if b is None:
            b = Beatmap(id=bd.id)
            bset.beatmaps.append(b)
        b.version = bd.version
        b.stars = bd.stars
        b.ar, b.cs, b.od, b.hp = bd.ar, bd.cs, bd.od, bd.hp
        b.bpm = bd.bpm
        b.total_length = bd.total_length
        b.hit_length = bd.hit_length
        b.max_combo = bd.max_combo
        b.count_circles = bd.count_circles
        b.count_sliders = bd.count_sliders
        b.play_count = bd.play_count
        b.pass_count = bd.pass_count
    return bset


def _state(db: Session, status: int) -> SyncState:
    state = db.get(SyncState, status)
    if state is None:
        state = SyncState(status=status, offset=0, last_ranked_date=None, exhausted=False)
        db.add(state)
        db.flush()
    return state


def synced_until(db: Session) -> date | None:
    """Every ranked/approved set up to this date is in the index."""
    dates = []
    for status in SYNC_STATUSES:
        state = db.get(SyncState, status)
        if state is None or state.last_ranked_date is None:
            if state is not None and state.exhausted:
                continue
            return None
        dates.append(date.max if state.exhausted else state.last_ranked_date)
    return min(dates) if dates else None


def sync_step(db: Session, client: mirror.MirrorClient, status: int) -> int:
    """Fetch and store the next page for one status. Returns the number of sets fetched."""
    state = _state(db, status)
    page = client.search_page(status, state.offset)
    for data in page:
        upsert_set(db, data)
        if data.ranked_date and (state.last_ranked_date is None or data.ranked_date > state.last_ranked_date):
            state.last_ranked_date = data.ranked_date
    state.offset += len(page)
    state.exhausted = len(page) < mirror.PAGE_SIZE
    state.updated_at = datetime.now(timezone.utc)
    db.commit()
    return len(page)


def _next_status(db: Session, until: date) -> int | None:
    """The status whose crawl lags furthest behind `until`, or None if all are done."""
    lagging = []
    for status in SYNC_STATUSES:
        state = db.get(SyncState, status)
        if state is None or state.last_ranked_date is None:
            if state is None or not state.exhausted:
                return status
            continue
        if not state.exhausted and state.last_ranked_date < until:
            lagging.append((state.last_ranked_date, status))
    return min(lagging)[1] if lagging else None


def sync_until(
    db: Session,
    client: mirror.MirrorClient,
    until: date,
    max_pages: int | None = None,
    delay: float = 0.0,
    should_stop=lambda: False,
) -> int:
    """Crawl until the index covers `until`. Returns pages fetched."""
    pages = 0
    while (max_pages is None or pages < max_pages) and not should_stop():
        status = _next_status(db, until)
        if status is None:
            break
        sync_step(db, client, status)
        pages += 1
        if delay:
            time.sleep(delay)
    return pages


@dataclass
class SyncStatus:
    synced_until: date | None
    target: date | None
    running: bool
    error: str | None
    indexed_sets: int


class BackgroundSyncer:
    """Runs the crawl in a daemon thread; requests only ever raise the target date."""

    def __init__(self, client_factory=mirror.MirrorClient, session_factory=SessionLocal):
        self._client_factory = client_factory
        self._session_factory = session_factory
        self._lock = threading.Lock()
        self._running = False  # guarded by _lock; cleared by the worker before it exits
        self._target: date | None = None
        self._error: str | None = None
        self._stop = threading.Event()

    def request(self, until: date) -> None:
        with self._lock:
            if self._target is None or until > self._target:
                self._target = until
            if not self._running:
                self._running = True
                self._error = None
                self._stop.clear()
                threading.Thread(target=self._run, name="beatmap-sync", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            client = self._client_factory()
            with self._session_factory() as db:
                while not self._stop.is_set():
                    with self._lock:
                        target = self._target
                    assert target is not None
                    if sync_until(db, client, target, max_pages=1, should_stop=self._stop.is_set) == 0:
                        with self._lock:
                            if self._target == target:  # no newer request arrived meanwhile
                                self._running = False
                                return
                        continue
                    time.sleep(PAGE_DELAY_SECONDS)
        except Exception as e:  # keep the error visible to the UI instead of dying silently
            log.exception("beatmap sync failed")
            with self._lock:
                self._error = str(e)
        with self._lock:
            self._running = False

    def status(self, db: Session) -> SyncStatus:
        with self._lock:
            running, target, error = self._running, self._target, self._error
        return SyncStatus(
            synced_until=synced_until(db),
            target=target,
            running=running,
            error=error,
            indexed_sets=db.scalar(select(func.count()).select_from(BeatmapSet)) or 0,
        )


syncer = BackgroundSyncer()

_client: mirror.MirrorClient | None = None


def default_client() -> mirror.MirrorClient:
    global _client
    if _client is None:
        _client = mirror.MirrorClient()
    return _client


def lookup_set_for_beatmap(
    db: Session, client: mirror.MirrorClient, beatmap_id: int
) -> tuple[BeatmapSet | None, str | None]:
    """Find the set of a beatmap, asking the mirror if it's not indexed yet.

    Returns (indexed set or None, mirror status). The set is None for maps that aren't
    ranked/approved (graveyard, loved...) and don't give PP.
    """
    beatmap = db.get(Beatmap, beatmap_id)
    if beatmap is not None:
        return beatmap.beatmapset, beatmap.beatmapset.status

    data = client.get_set_for_beatmap(beatmap_id)
    if data is None:
        return None, None
    bset = upsert_set(db, data)
    if bset is not None:
        db.commit()
    return bset, data.status


class NotPlayable(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def check_playable(db: Session, in_game_date: date, beatmap_id: int) -> BeatmapSet:
    """Only ranked/approved maps that already exist on the in-game date count."""
    try:
        bset, status = lookup_set_for_beatmap(db, default_client(), beatmap_id)
    except mirror.MirrorError as e:
        raise NotPlayable(502, f"couldn't check beatmap status: {e}") from e
    if bset is None:
        if status is None:
            raise NotPlayable(404, f"beatmap {beatmap_id} not found")
        raise NotPlayable(422, f"beatmap is {status}: only ranked and approved maps give pp")
    if bset.ranked_date > in_game_date:
        raise NotPlayable(409, f"{bset.artist} - {bset.title} gets ranked on {bset.ranked_date}; it's only {in_game_date}")
    return bset


SORTS = {
    "ranked_desc": BeatmapSet.ranked_date.desc(),
    "ranked_asc": BeatmapSet.ranked_date.asc(),
    "plays": BeatmapSet.play_count.desc(),
    "favourites": BeatmapSet.favourite_count.desc(),
}


def search(
    db: Session,
    before: date,
    query: str = "",
    min_stars: float | None = None,
    max_stars: float | None = None,
    sort: str = "ranked_desc",
    limit: int = 30,
    offset: int = 0,
) -> tuple[int, list[tuple[BeatmapSet, list[Beatmap]]]]:
    """Sets ranked on or before `before`, with only the difficulties matching the star range."""
    diff_filters = [Beatmap.beatmapset_id == BeatmapSet.id]
    if min_stars is not None:
        diff_filters.append(Beatmap.stars >= min_stars)
    if max_stars is not None:
        diff_filters.append(Beatmap.stars <= max_stars)

    set_filters = [BeatmapSet.ranked_date <= before]
    for token in query.split():
        like = f"%{token}%"
        set_filters.append(
            or_(
                BeatmapSet.artist.ilike(like),
                BeatmapSet.title.ilike(like),
                BeatmapSet.creator.ilike(like),
                BeatmapSet.source.ilike(like),
                BeatmapSet.tags.ilike(like),
                select(Beatmap.id).where(Beatmap.beatmapset_id == BeatmapSet.id, Beatmap.version.ilike(like)).exists(),
            )
        )
    set_filters.append(select(Beatmap.id).where(*diff_filters).exists())

    total = db.scalar(select(func.count()).select_from(BeatmapSet).where(*set_filters)) or 0
    order = SORTS.get(sort)
    stmt = select(BeatmapSet).where(*set_filters).options(selectinload(BeatmapSet.beatmaps))
    if order is not None:
        stmt = stmt.order_by(order, BeatmapSet.id)
    else:  # stars_desc / stars_asc: by the hardest matching difficulty
        hardest = select(func.max(Beatmap.stars)).where(*diff_filters).scalar_subquery()
        stmt = stmt.order_by(hardest.asc() if sort == "stars_asc" else hardest.desc(), BeatmapSet.id)

    results = []
    for bset in db.scalars(stmt.limit(limit).offset(offset)):
        diffs = [
            b
            for b in bset.beatmaps
            if (min_stars is None or b.stars >= min_stars) and (max_stars is None or b.stars <= max_stars)
        ]
        results.append((bset, sorted(diffs, key=lambda b: b.stars)))
    return total, results
