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
SCHEMA_VERSION = 22
UPGRADES: dict[int, list[str]] = {
    21: [
        "ALTER TABLE beatmaps ADD COLUMN checksum VARCHAR(32)",
        "CREATE INDEX IF NOT EXISTS ix_beatmaps_checksum ON beatmaps (checksum)",
    ],
    20: [
        "ALTER TABLE real_plays ADD COLUMN career_score_id INTEGER",
        "ALTER TABLE real_plays ADD COLUMN career_note VARCHAR(256) NOT NULL DEFAULT ''",
    ],  # + hand_days table (created by create_all)
    19: [],  # assist_settings table (created by create_all)
    18: ["ALTER TABLE real_plays ADD COLUMN assist JSON NOT NULL DEFAULT '{}'"],
    17: [
        "ALTER TABLE real_plays ADD COLUMN source VARCHAR(8) NOT NULL DEFAULT 'stable'",
        "ALTER TABLE real_plays ADD COLUMN status VARCHAR(8) NOT NULL DEFAULT 'passed'",
        "ALTER TABLE real_plays ADD COLUMN progress FLOAT NOT NULL DEFAULT 1.0",
    ],  # + client_link table (created by create_all)
    16: [],  # real_plays table (created by create_all)
    15: ["ALTER TABLE map_scores ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"],
    14: ["ALTER TABLE players ADD COLUMN story_state JSON NOT NULL DEFAULT '{}'"],
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


def init_db(target=None) -> None:
    """Create or upgrade the schema of the app's database, or of `target` (an engine) when given."""
    from app import models  # noqa: F401  (register tables)

    with (target or engine).begin() as conn:
        version = conn.exec_driver_sql("PRAGMA user_version").scalar()
        has_tables = bool(inspect(conn).get_table_names())
        if has_tables and version != SCHEMA_VERSION:
            if any(v not in UPGRADES for v in range(version, SCHEMA_VERSION)):
                raise RuntimeError(
                    f"Database schema is v{version}, the engine needs v{SCHEMA_VERSION}. "
                    f"Delete {DATABASE_URL.removeprefix('sqlite:///')} to start fresh."
                )
            tables = set(inspect(conn).get_table_names())
            for v in range(version, SCHEMA_VERSION):
                for statement in UPGRADES[v]:
                    # A table added in a later version doesn't exist yet: create_all builds it complete.
                    if statement.startswith("ALTER TABLE ") and statement.split()[2] not in tables:
                        continue
                    conn.exec_driver_sql(statement)
        Base.metadata.create_all(conn)
        conn.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")
