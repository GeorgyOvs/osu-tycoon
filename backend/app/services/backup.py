"""Move careers between devices: export the database (everything, or one career) and import it back.

An export is a zip with a consistent snapshot of the SQLite database (taken with SQLite's backup API, so it is
safe while the server and the beatmap crawler are running) and a manifest saying what is inside. Importing
replaces the whole database with the file's: careers reference each other's rows by id in many places (NPCs,
tournaments, scores inside JSON), so merging two databases can't be done safely. The database being replaced
is kept first, under data/backups, and the imported one is checked and upgraded to the current schema in a
scratch copy before the live database is touched.

Beatmap files (data/osu_files) are a download cache and are not exported; the client keeps its own data
(downloaded maps, local scores and replays) in %APPDATA%\\osu-tycoon.
"""
import io
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import sqlalchemy.exc
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app import db as app_db
from app.models import Player

FORMAT = "osu-tycoon-export"
FORMAT_VERSION = 1
DB_NAME = "tycoon.db"
MANIFEST = "manifest.json"
MAX_UPLOAD = 2 * 1024**3


class BackupError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def live_path() -> Path:
    database = app_db.engine.url.database
    if app_db.engine.url.get_backend_name() != "sqlite" or not database:
        raise BackupError(501, "export and import only work with the SQLite database")
    return Path(database)


def backups_dir() -> Path:
    path = live_path().parent / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _snapshot(source: Path, target: Path) -> None:
    src = sqlite3.connect(source, timeout=30)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _careers(engine) -> list[dict]:
    with Session(engine) as db:
        return [{"id": p.id, "name": p.name, "country": p.country, "date": p.in_game_date.isoformat(),
                 "pp": round(p.total_pp or 0, 1)} for p in db.scalars(select(Player).order_by(Player.id))]


def _engine(path: Path):
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 30})

    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def export(player_id: int | None = None) -> tuple[bytes, str]:
    """(zip bytes, file name). With `player_id`, only that career is kept (plus the shared beatmap index)."""
    live = live_path()
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / DB_NAME
        _snapshot(live, copy)
        engine = _engine(copy)
        try:
            if player_id is not None:
                with Session(engine) as db:
                    if db.get(Player, player_id) is None:
                        raise BackupError(404, "career not found")
                    for other in db.scalars(select(Player).where(Player.id != player_id)):
                        db.delete(other)  # the same cascade as deleting a career in the app
                    db.commit()
            careers = _careers(engine)
            with engine.connect() as conn:
                schema = conn.exec_driver_sql("PRAGMA user_version").scalar()
        finally:
            engine.dispose()
        conn = sqlite3.connect(copy)
        conn.execute("VACUUM")
        conn.close()

        manifest = {"format": FORMAT, "version": FORMAT_VERSION, "schema_version": schema,
                    "exported_at": datetime.now().isoformat(timespec="seconds"), "careers": careers}
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1))
            z.write(copy, DB_NAME)

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    who = careers[0]["name"] if player_id is not None and careers else "all"
    safe = "".join(c for c in who if c.isalnum() or c in "-_") or "career"
    return out.getvalue(), f"osu-tycoon-{safe}-{stamp}.zip"


def inspect_file(data: bytes) -> dict:
    """The manifest of an export, checked; raises BackupError when it isn't one."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            manifest = json.loads(z.read(MANIFEST))
            if DB_NAME not in z.namelist():
                raise KeyError(DB_NAME)
    except (zipfile.BadZipFile, KeyError, ValueError) as e:
        raise BackupError(422, f"not an osu! Tycoon export: {e}") from e
    if manifest.get("format") != FORMAT:
        raise BackupError(422, "not an osu! Tycoon export")
    if manifest.get("version", 0) > FORMAT_VERSION or manifest.get("schema_version", 0) > app_db.SCHEMA_VERSION:
        raise BackupError(422, "this export comes from a newer version of osu! Tycoon; update this one first")
    return manifest


def import_(data: bytes) -> dict:
    """Replace the database with the export's. Returns what was imported and where the old database was kept."""
    if len(data) > MAX_UPLOAD:
        raise BackupError(413, "file too large")
    manifest = inspect_file(data)
    live = live_path()

    with tempfile.TemporaryDirectory() as tmp:
        incoming = Path(tmp) / DB_NAME
        with zipfile.ZipFile(io.BytesIO(data)) as z, z.open(DB_NAME) as src, open(incoming, "wb") as dst:
            shutil.copyfileobj(src, dst)

        # Check and upgrade it on the side first: a broken or too old file must not cost the current data.
        engine = _engine(incoming)
        try:
            with engine.connect() as conn:
                if conn.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok":
                    raise BackupError(422, "the database in this export is damaged")
                if "players" not in inspect(conn).get_table_names():
                    raise BackupError(422, "the database in this export has no careers")
            try:
                app_db.init_db(engine)
            except RuntimeError as e:
                raise BackupError(422, str(e)) from e
            careers = _careers(engine)
        except (sqlite3.DatabaseError, sqlalchemy.exc.DatabaseError) as e:
            raise BackupError(422, f"the database in this export can't be read: {e}") from e
        finally:
            engine.dispose()

        kept = backups_dir() / f"tycoon-before-import-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
        _snapshot(live, kept)

        # Write the imported database into the live one in place: open connections keep working.
        app_db.engine.dispose()
        src = sqlite3.connect(incoming)
        dst = sqlite3.connect(live, timeout=60)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        app_db.engine.dispose()

    app_db.init_db()
    return {"careers": careers, "exported_at": manifest.get("exported_at"), "backup": kept.name}

