from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32))
    character_build: Mapped[dict] = mapped_column(JSON, default=dict)
    country: Mapped[str] = mapped_column(String(2), default="XX")
    in_game_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Drives all randomness: the same seed and actions always give the same career.
    seed: Mapped[int] = mapped_column(Integer)
    # Default ceiling for every attribute (1-115).
    potential: Mapped[float] = mapped_column(Float)
    # Hidden learning speed multiplier (~0.6-1.6).
    talent: Mapped[float] = mapped_column(Float, default=1.0)
    # Autocorrelated day-to-day form, roughly -2..2; good and bad streaks last days.
    form: Mapped[float] = mapped_column(Float, default=0.0)
    # 0 = cheap unergonomic setup, 1 = ideal. Will come from the gear inventory.
    ergonomics: Mapped[float] = mapped_column(Float, default=0.3)

    # Conditions, 0-100 scale.
    fatigue: Mapped[float] = mapped_column(Float, default=0.0)
    motivation: Mapped[float] = mapped_column(Float, default=80.0)
    morale: Mapped[float] = mapped_column(Float, default=50.0)
    consecutive_training_days: Mapped[int] = mapped_column(Integer, default=0)

    # Injury state machine: healthy -> minor_strain -> severe_rsi.
    injury: Mapped[str] = mapped_column(String(16), default="healthy")
    injury_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    strain_recovery_days: Mapped[int] = mapped_column(Integer, default=0)
    physio_days: Mapped[int] = mapped_column(Integer, default=0)

    # Role-play only: shapes how the community and SillyTavern talk about you, never the mechanics.
    gender: Mapped[str] = mapped_column(String(16), default="unspecified")
    # Life outside osu!.
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    occupation: Mapped[str] = mapped_column(String(16), default="school")  # school | university | work | pro
    money: Mapped[float] = mapped_column(Float, default=100.0)
    # Playstyle; switching starts a long adaptation (0 = just switched, 1 = fully used to it).
    input_device: Mapped[str] = mapped_column(String(8), default="mouse")  # mouse | tablet
    tap_style: Mapped[str] = mapped_column(String(12), default="alternate")  # alternate | singletap
    style_adaptation: Mapped[float] = mapped_column(Float, default=1.0)
    # Streaming.
    followers: Mapped[int] = mapped_column(Integer, default=0)
    # Tournament badges: [{"name", "tournament_id", "date"}]; count towards BWS seeding.
    badges: Mapped[list] = mapped_column(JSON, default=list)

    # Derived from scores; recomputed on every submission.
    total_pp: Mapped[float] = mapped_column(Float, default=0.0)
    accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    global_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    scores: Mapped[list["Score"]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )
    attributes: Mapped[list["PlayerAttribute"]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )


class PlayerAttribute(Base):
    """One granular sub-stat. Effective value = min(base - rust, cap) x injury modifier."""

    __tablename__ = "player_attributes"
    __table_args__ = (UniqueConstraint("player_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    key: Mapped[str] = mapped_column(String(32))
    base: Mapped[float] = mapped_column(Float)
    cap: Mapped[float] = mapped_column(Float)
    rust: Mapped[float] = mapped_column(Float, default=0.0)
    # Hidden per-skill aptitude: natural aimers learn aim faster than streams.
    affinity: Mapped[float] = mapped_column(Float, default=1.0)
    # Training volume since the last breakthrough; high plateau = diminishing returns.
    plateau: Mapped[float] = mapped_column(Float, default=0.0)
    last_trained_on: Mapped[date] = mapped_column(Date)

    player: Mapped[Player] = relationship(back_populates="attributes")


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    beatmap_id: Mapped[int] = mapped_column(Integer, index=True)
    beatmapset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artist: Mapped[str] = mapped_column(String(256), default="")
    title: Mapped[str] = mapped_column(String(256), default="")
    difficulty_name: Mapped[str] = mapped_column(String(256), default="")

    mods: Mapped[str] = mapped_column(String(32), default="")
    accuracy: Mapped[float] = mapped_column(Float)
    max_combo: Mapped[int] = mapped_column(Integer)
    misses: Mapped[int] = mapped_column(Integer, default=0)
    stars: Mapped[float] = mapped_column(Float)
    pp: Mapped[float] = mapped_column(Float)
    score_value: Mapped[int] = mapped_column(Integer, default=0)  # ScoreV1, for map leaderboards
    # pp components (as computed today) so historical pp reworks can be applied per era.
    pp_aim: Mapped[float] = mapped_column(Float, default=0.0)
    pp_speed: Mapped[float] = mapped_column(Float, default=0.0)
    pp_acc: Mapped[float] = mapped_column(Float, default=0.0)
    pp_modern: Mapped[float] = mapped_column(Float, default=0.0)  # today's formula; `pp` is the era's
    map_max_combo: Mapped[int] = mapped_column(Integer, default=0)

    played_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    player: Mapped[Player] = relationship(back_populates="scores")


class BeatmapSet(Base):
    """Local index of ranked/approved mapsets, synced from the mirror in ranked_date order."""

    __tablename__ = "beatmapsets"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist: Mapped[str] = mapped_column(String(256))
    title: Mapped[str] = mapped_column(String(256))
    creator: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(256), default="")
    tags: Mapped[str] = mapped_column(String(2048), default="")
    status: Mapped[str] = mapped_column(String(16))
    ranked_date: Mapped[date] = mapped_column(Date, index=True)
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    favourite_count: Mapped[int] = mapped_column(Integer, default=0)
    bpm: Mapped[float] = mapped_column(Float, default=0.0)

    beatmaps: Mapped[list["Beatmap"]] = relationship(
        back_populates="beatmapset", cascade="all, delete-orphan"
    )


class Beatmap(Base):
    __tablename__ = "beatmaps"

    id: Mapped[int] = mapped_column(primary_key=True)
    beatmapset_id: Mapped[int] = mapped_column(ForeignKey("beatmapsets.id"), index=True)
    version: Mapped[str] = mapped_column(String(256))
    stars: Mapped[float] = mapped_column(Float, index=True)  # mirror's (current) star rating
    ar: Mapped[float] = mapped_column(Float)
    cs: Mapped[float] = mapped_column(Float)
    od: Mapped[float] = mapped_column(Float)
    hp: Mapped[float] = mapped_column(Float)
    bpm: Mapped[float] = mapped_column(Float)
    total_length: Mapped[int] = mapped_column(Integer)
    hit_length: Mapped[int] = mapped_column(Integer)
    max_combo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    count_circles: Mapped[int] = mapped_column(Integer, default=0)
    count_sliders: Mapped[int] = mapped_column(Integer, default=0)
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    pass_count: Mapped[int] = mapped_column(Integer, default=0)

    beatmapset: Mapped[BeatmapSet] = relationship(back_populates="beatmaps")


class SyncState(Base):
    """Progress of the mirror crawl, one row per ranked status."""

    __tablename__ = "sync_state"

    status: Mapped[int] = mapped_column(primary_key=True)  # mirror status code: 1 ranked, 2 approved
    offset: Mapped[int] = mapped_column(Integer, default=0)
    last_ranked_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exhausted: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# --- Living world (one per career) ---------------------------------------------------


class WorldState(Base):
    __tablename__ = "world_state"

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    last_tick: Mapped[date] = mapped_column(Date)  # the world has been simulated up to this date
    generated_through: Mapped[int] = mapped_column(Integer)  # tournaments exist up to this year
    number_one_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    population_version: Mapped[int] = mapped_column(Integer, default=1)
    # Fictional-world records. Real/legend rows never write these values.
    fictional_pp_record: Mapped[float] = mapped_column(Float, default=0.0)
    fictional_score_record: Mapped[float] = mapped_column(Float, default=0.0)


class Npc(Base):
    """A legend or procedural player. Only composites are simulated, weekly."""

    __tablename__ = "npcs"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # legend | procedural
    name: Mapped[str] = mapped_column(String(32))
    country: Mapped[str] = mapped_column(String(2))
    style: Mapped[dict] = mapped_column(JSON)
    # Persistent simulation state kept as JSON so old careers can be upgraded safely.
    development: Mapped[dict] = mapped_column(JSON, default=dict)
    story: Mapped[dict] = mapped_column(JSON, default=dict)
    seed: Mapped[int] = mapped_column(Integer)

    # Procedural career shape (legends use their curve from world_data instead).
    join_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    peak: Mapped[float] = mapped_column(Float, default=0.0)
    ramp_years: Mapped[float] = mapped_column(Float, default=0.0)
    prime_years: Mapped[float] = mapped_column(Float, default=0.0)
    decline_per_year: Mapped[float] = mapped_column(Float, default=0.0)

    # Dynamic state.
    status: Mapped[str] = mapped_column(String(12), default="not_started")
    overall: Mapped[float] = mapped_column(Float, default=0.0)
    deviation: Mapped[float] = mapped_column(Float, default=0.0)  # random walk around the career curve
    form: Mapped[float] = mapped_column(Float, default=0.0)
    motivation: Mapped[float] = mapped_column(Float, default=70.0)
    away_until: Mapped[date | None] = mapped_column(Date, nullable=True)  # injury or hiatus end
    curve_shift_weeks: Mapped[int] = mapped_column(Integer, default=0)  # delayed decline (rivalries)
    pp: Mapped[float] = mapped_column(Float, default=0.0)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    titles: Mapped[int] = mapped_column(Integer, default=0)


class WorldEvent(Base):
    __tablename__ = "world_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    type: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(String(512))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    importance: Mapped[int] = mapped_column(Integer, default=1)  # 1 minor .. 3 headline


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    template: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    tier: Mapped[str] = mapped_column(String(16))
    rank_min: Mapped[int] = mapped_column(Integer)
    rank_max: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer)
    team_size: Mapped[int] = mapped_column(Integer, default=1)
    registration_opens: Mapped[date] = mapped_column(Date)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    base_stars: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="upcoming")  # upcoming | ongoing | finished
    user_registered: Mapped[bool] = mapped_column(default=False)
    pools: Mapped[dict] = mapped_column(JSON, default=dict)  # week -> list of slots
    winner_entry_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    entries: Mapped[list["TournamentEntry"]] = relationship(cascade="all, delete-orphan")
    matches: Mapped[list["Match"]] = relationship(cascade="all, delete-orphan", order_by="Match.order")


class TournamentEntry(Base):
    """A bracket participant: the user, an NPC, a one-off filler, or a country team."""

    __tablename__ = "tournament_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # user | npc | filler | team
    npc_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(48))
    country: Mapped[str] = mapped_column(String(2))
    seed: Mapped[int] = mapped_column(Integer)
    # Composite snapshot at the start, plus team members [{name, kind, npc_id, composites}].
    composites: Mapped[dict] = mapped_column(JSON)
    members: Mapped[list] = mapped_column(JSON, default=list)
    includes_user: Mapped[bool] = mapped_column(default=False)
    placement: Mapped[str | None] = mapped_column(String(24), nullable=True)


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(8))  # W1-0, L3-1, GF
    order: Mapped[int] = mapped_column(Integer)
    week: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(24))
    first_to: Mapped[int] = mapped_column(Integer)
    source_a: Mapped[str] = mapped_column(String(16))  # seed:3 | winner:W1-0 | loser:W1-0
    source_b: Mapped[str] = mapped_column(String(16))
    entry_a: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_b: Mapped[int | None] = mapped_column(Integer, nullable=True)
    winner: Mapped[int | None] = mapped_column(Integer, nullable=True)
    loser: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_a: Mapped[int] = mapped_column(Integer, default=0)
    score_b: Mapped[int] = mapped_column(Integer, default=0)
    maps: Mapped[list] = mapped_column(JSON, default=list)  # map-by-map results for user matches
    played_on: Mapped[date | None] = mapped_column(Date, nullable=True)


# --- Social layer: forum, IRC and the SillyTavern outbox ------------------------------------


class StEvent(Base):
    """An engine event for SillyTavern, in the plan's {event_type, data} shape."""

    __tablename__ = "st_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    thread_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channel: Mapped[str] = mapped_column(String(32), default="#osu")
    handled: Mapped[bool] = mapped_column(default=False)  # acknowledged by the SillyTavern extension
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ForumThread(Base):
    __tablename__ = "forum_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    board: Mapped[str] = mapped_column(String(48))
    kind: Mapped[str] = mapped_column(String(16))  # scorepost | tournament | news | drama | milestone
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(String(4000), default="")
    author: Mapped[str] = mapped_column(String(48))
    flair: Mapped[str] = mapped_column(String(32), default="")
    upvotes: Mapped[int] = mapped_column(Integer, default=1)
    llm_status: Mapped[str] = mapped_column(String(12), default="none")  # none | pending | done

    comments: Mapped[list["ForumComment"]] = relationship(cascade="all, delete-orphan", order_by="ForumComment.id")


class ForumComment(Base):
    __tablename__ = "forum_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("forum_threads.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author: Mapped[str] = mapped_column(String(48))
    content: Mapped[str] = mapped_column(String(4000))
    upvotes: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(12), default="procedural")  # procedural | llm
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ChatMessage(Base):
    """IRC / Twitch / DM lines."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    channel: Mapped[str] = mapped_column(String(32), index=True)
    author: Mapped[str] = mapped_column(String(48))
    content: Mapped[str] = mapped_column(String(1000))
    source: Mapped[str] = mapped_column(String(12), default="procedural")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# --- Per-map leaderboards ----------------------------------------------------------------------


class MapScore(Base):
    """Best score of one NPC (or a curated real anchor score) on a beatmap. The user's come from `scores`."""

    __tablename__ = "map_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    record: Mapped[bool] = mapped_column(default=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    beatmap_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(12))  # npc | anchor
    npc_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(48))
    country: Mapped[str] = mapped_column(String(2))
    mods: Mapped[str] = mapped_column(String(32), default="")
    score: Mapped[int] = mapped_column(Integer)
    accuracy: Mapped[float] = mapped_column(Float)
    max_combo: Mapped[int] = mapped_column(Integer)
    misses: Mapped[int] = mapped_column(Integer)
    pp: Mapped[float] = mapped_column(Float, default=0.0)
    set_on: Mapped[date] = mapped_column(Date)


class MapBoard(Base):
    """How far a beatmap's leaderboard has been simulated, per world."""

    __tablename__ = "map_boards"

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    beatmap_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generated_through: Mapped[date] = mapped_column(Date)
    user_first: Mapped[bool] = mapped_column(default=False)  # the user holds #1: watch for snipes


# --- Careers in depth: familiarity, gear, rivals ----------------------------------------------


class Duel(Base):
    """A 1v1 showmatch: drawn (pending) with its pool, then played."""

    __tablename__ = "duels"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    npc_id: Mapped[int] = mapped_column(Integer)
    date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(12))  # friendly | rival
    best_of: Mapped[int] = mapped_column(Integer)
    bans_per_side: Mapped[int] = mapped_column(Integer, default=1)
    difficulty: Mapped[str] = mapped_column(String(12), default="even")
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | played | expired
    pool: Mapped[list] = mapped_column(JSON, default=list)
    maps: Mapped[list] = mapped_column(JSON, default=list)
    score_user: Mapped[int] = mapped_column(Integer, default=0)
    score_npc: Mapped[int] = mapped_column(Integer, default=0)
    won: Mapped[bool | None] = mapped_column(nullable=True)


class MapFamiliarity(Base):
    """How well the player knows a map: replaying it builds muscle memory, time away fades it."""

    __tablename__ = "map_familiarity"

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    beatmap_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_played: Mapped[date] = mapped_column(Date)


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    item_key: Mapped[str] = mapped_column(String(32))
    bought_on: Mapped[date] = mapped_column(Date)
    equipped: Mapped[bool] = mapped_column(default=False)


class Rival(Base):
    __tablename__ = "rivals"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    npc_id: Mapped[int] = mapped_column(Integer)
    since: Mapped[date] = mapped_column(Date)
    heat: Mapped[float] = mapped_column(Float, default=20.0)  # 0..100: how personal it is
    active: Mapped[bool] = mapped_column(default=True)
    record: Mapped[dict] = mapped_column(JSON, default=dict)  # snipes_for/against, matches_won/lost
