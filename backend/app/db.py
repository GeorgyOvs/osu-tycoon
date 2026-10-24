from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATA_DIR, DATABASE_URL

if DATABASE_URL.startswith("sqlite:///"):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record) -> None:
    # WAL lets API reads proceed while the beatmap crawler writes in the background.
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Bump on every schema change. UPGRADES maps an old version to the SQL that brings it one step
# forward (new tables are created by create_all afterwards); versions missing here need a fresh DB.
SCHEMA_VERSION = 14
UPGRADES: dict[int, list[str]] = {
    13: [
        "ALTER TABLE map_scores ADD COLUMN record BOOLEAN NOT NULL DEFAULT 0",
        "UPDATE world_state SET fictional_score_record = 0",
    ],
    12: [
        "ALTER TABLE players ADD COLUMN character_build JSON NOT NULL DEFAULT '{}'",
        "ALTER TABLE world_state ADD COLUMN population_version INTEGER NOT NULL DEFAULT 0",
    ],
    3: [],
    4: [],
    5: [],
    6: ["ALTER TABLE scores ADD COLUMN score_value INTEGER NOT NULL DEFAULT 0"],
    7: [
        "ALTER TABLE players ADD COLUMN birth_date DATE",
        "ALTER TABLE players ADD COLUMN occupation VARCHAR(16) NOT NULL DEFAULT 'school'",
        "ALTER TABLE players ADD COLUMN money FLOAT NOT NULL DEFAULT 100.0",
        "ALTER TABLE players ADD COLUMN input_device VARCHAR(8) NOT NULL DEFAULT 'mouse'",
        "ALTER TABLE players ADD COLUMN tap_style VARCHAR(12) NOT NULL DEFAULT 'alternate'",
        "ALTER TABLE players ADD COLUMN style_adaptation FLOAT NOT NULL DEFAULT 1.0",
        "ALTER TABLE players ADD COLUMN followers INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE scores ADD COLUMN pp_aim FLOAT NOT NULL DEFAULT 0.0",
        "ALTER TABLE scores ADD COLUMN pp_speed FLOAT NOT NULL DEFAULT 0.0",
        "ALTER TABLE scores ADD COLUMN pp_acc FLOAT NOT NULL DEFAULT 0.0",
        "ALTER TABLE scores ADD COLUMN pp_modern FLOAT NOT NULL DEFAULT 0.0",
        "ALTER TABLE scores ADD COLUMN map_max_combo INTEGER NOT NULL DEFAULT 0",
    ],
    8: ["ALTER TABLE players ADD COLUMN badges JSON NOT NULL DEFAULT '[]'"],
    9: ["ALTER TABLE players ADD COLUMN gender VARCHAR(16) NOT NULL DEFAULT 'unspecified'"],
    10: [],  # duels table (created by create_all)
    11: [
        "ALTER TABLE npcs ADD COLUMN development JSON NOT NULL DEFAULT '{}'",
        "ALTER TABLE npcs ADD COLUMN story JSON NOT NULL DEFAULT '{}'",
        "ALTER TABLE world_state ADD COLUMN fictional_pp_record FLOAT NOT NULL DEFAULT 0.0",
        "ALTER TABLE world_state ADD COLUMN fictional_score_record FLOAT NOT NULL DEFAULT 0.0",
    ],
}


def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    with engine.begin() as conn:
        version = conn.exec_driver_sql("PRAGMA user_version").scalar()
        has_tables = bool(inspect(conn).get_table_names())
        if has_tables and version != SCHEMA_VERSION:
            if any(v not in UPGRADES for v in range(version, SCHEMA_VERSION)):
                raise RuntimeError(
                    f"Database schema is v{version}, the engine needs v{SCHEMA_VERSION}. "
                    f"Delete {DATABASE_URL.removeprefix('sqlite:///')} to start fresh."
                )
            for v in range(version, SCHEMA_VERSION):
                for statement in UPGRADES[v]:
                    conn.exec_driver_sql(statement)
        Base.metadata.create_all(conn)
        conn.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")
