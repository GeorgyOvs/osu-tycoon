from datetime import date

from pydantic import BaseModel, ConfigDict, Field

# osu! went public in September 2007; the timeline spec covers up to 2024.
EARLIEST_START = date(2007, 9, 16)
LATEST_START = date(2024, 12, 31)


class BeatmapInfo(BaseModel):
    beatmap_id: int
    beatmapset_id: int | None
    artist: str
    title: str
    version: str
    creator: str
    preview_url: str | None


class PpRequest(BaseModel):
    beatmap_id: int = Field(gt=0)
    mods: str = ""
    accuracy: float | None = Field(default=None, ge=0, le=100)
    misses: int = Field(default=0, ge=0)
    combo: int | None = Field(default=None, ge=0)
    n100: int | None = Field(default=None, ge=0)
    n50: int | None = Field(default=None, ge=0)


class PpResponse(BaseModel):
    beatmap: BeatmapInfo
    mods: str
    pp: float
    pp_aim: float
    pp_speed: float
    pp_accuracy: float
    stars: float
    aim_difficulty: float
    speed_difficulty: float
    max_combo: int
    ar: float
    od: float
    cs: float
    hp: float
    bpm: float


class PlayerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    country: str = Field(default="XX", pattern=r"^[A-Za-z]{2}$")
    start_date: date = Field(ge=EARLIEST_START, le=LATEST_START)
    seed: int | None = None
    age: float = Field(default=15, ge=7, le=40)
    gender: str = Field(default="unspecified", pattern="^(male|female|nonbinary|unspecified)$")
    occupation: str | None = None  # defaults by age: school / university / work
    preset: str = "random"
    perks: list[str] | None = Field(default=None, max_length=20)
    unbalanced: bool = False
    scenario: str = "newcomer"  # starting level, see engine/scenarios.py
    hardcore: bool = False
    realistic_economy: bool = False


class SubStatOut(BaseModel):
    key: str
    label: str
    value: float  # effective: rust, cap and injury applied
    base: float
    cap: float
    rust: float
    plateau: float


class AttributeGroupOut(BaseModel):
    key: str
    label: str
    value: float
    subs: list[SubStatOut]


class PlayerConditions(BaseModel):
    fatigue: float
    motivation: float
    morale: float
    consecutive_training_days: int


class InjuryOut(BaseModel):
    state: str
    until: date | None
    strain_recovery_days: int
    physio_days: int


class LifeOut(BaseModel):
    gender: str
    pronouns: str
    age: float | None
    occupation: str
    money: float
    free_hours_today: float
    followers: int
    input_device: str
    tap_style: str
    style_adaptation: float


class PlayerOut(BaseModel):
    id: int
    character_build: dict = {}
    name: str
    country: str
    in_game_date: date
    era: str
    era_label: str
    overall: float
    pp_potential: float
    tournament_strength: float
    potential: float
    form: float
    traits: list[str]
    ergonomics: float
    attributes: list[AttributeGroupOut]
    conditions: PlayerConditions
    injury: InjuryOut
    total_pp: float
    accuracy: float
    play_count: int
    global_rank: int | None
    previous_rank: int | None
    life: LifeOut | None = None
    pp_system: dict | None = None
    badges: list[dict] = []


class ScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    beatmap_id: int
    beatmapset_id: int | None
    artist: str
    title: str
    difficulty_name: str
    mods: str
    accuracy: float
    max_combo: int
    misses: int
    stars: float
    pp: float
    played_on: date
    grade: str = ""


class TopPlay(ScoreOut):
    weight: float
    weighted_pp: float


class PlayerProfile(PlayerOut):
    top_plays: list[TopPlay]
    recent_scores: list[ScoreOut]


class ScoreSubmit(BaseModel):
    beatmap_id: int = Field(gt=0)
    mods: str = ""
    accuracy: float = Field(ge=0, le=100)
    misses: int = Field(default=0, ge=0)
    combo: int | None = Field(default=None, ge=0)


class ScoreSubmitResult(BaseModel):
    score: ScoreOut
    is_new_top_play: bool
    top_play_position: int | None
    pp_gained: float
    player: PlayerOut


class DrillOut(BaseModel):
    key: str
    label: str
    description: str
    targets: dict[str, float]
    strain: float
    efficiency: float
    available: bool
    available_from: str
    sets_scores: bool  # plays ranked maps, so it can set scores and pp


class TrainRequest(BaseModel):
    drill: str
    hours_per_day: float = Field(gt=0, le=16)
    days: int = Field(ge=1, le=30)


class RestRequest(BaseModel):
    days: int = Field(ge=1, le=120)
    physio: bool = False


class EventOut(BaseModel):
    date: date
    type: str
    message: str
    data: dict


class ActionResultOut(BaseModel):
    start_date: date
    end_date: date
    days: int
    events: list[EventOut]
    deltas: dict[str, float]
    player: PlayerOut
    scores: list[ScoreOut] = []  # ranked plays set along the way (map-playing drills)


class BeatmapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: str
    stars: float
    ar: float
    cs: float
    od: float
    hp: float
    bpm: float
    total_length: int
    hit_length: int
    max_combo: int | None
    count_circles: int
    count_sliders: int
    play_count: int
    pass_count: int


class BeatmapSetOut(BaseModel):
    id: int
    artist: str
    title: str
    creator: str
    source: str
    status: str
    ranked_date: date
    play_count: int
    favourite_count: int
    bpm: float
    preview_url: str
    cover_url: str
    beatmaps: list[BeatmapOut]


class IndexStatusOut(BaseModel):
    synced_until: date | None
    target: date | None
    running: bool
    error: str | None
    indexed_sets: int


class BeatmapSearchOut(BaseModel):
    before: date
    total: int
    complete: bool  # False while the index hasn't reached `before` yet
    index: IndexStatusOut
    results: list[BeatmapSetOut]


class PlayRequestIn(BaseModel):
    beatmap_id: int = Field(gt=0)
    mods: str = ""
    attempts: int = Field(default=1, ge=1, le=10)


class SessionRequest(BaseModel):
    plays: list[PlayRequestIn] = Field(min_length=1, max_length=20)
    stream: bool = False


class TimelineBucketOut(BaseModel):
    misses: int
    hp_min: float
    reached: bool


class AttemptOut(BaseModel):
    passed: bool
    fail_progress: float | None
    fail_time: float | None
    n300: int
    n100: int
    n50: int
    misses: int
    max_combo: int
    accuracy: float
    grade: str
    pp: float | None
    choked: bool
    miss_causes: dict[str, int]
    key_moments: list[str]
    timeline: list[TimelineBucketOut]
    replay: dict = Field(default_factory=dict)
    commentary: list[dict] = Field(default_factory=list)


class PlayOut(BaseModel):
    beatmap: BeatmapInfo
    mods: str
    stars: float
    attempts: list[AttemptOut]
    best_index: int | None
    score: ScoreOut | None
    is_new_top_play: bool
    top_play_position: int | None
    pp_gained: float
    previous_best_pp: float | None = None
    board_rank: int | None = None
    board_size: int | None = None


class SessionOut(BaseModel):
    date: date
    hours: float
    plays: list[PlayOut]
    training: dict[str, float]
    events: list[EventOut]
    deltas: dict[str, float]
    player: PlayerOut


class MapDemandOut(BaseModel):
    stars: float
    aim: float
    speed: float
    ar: float
    od: float
    cs: float
    hp: float
    bpm: float
    drain_seconds: float
    max_combo: int
    fastest_stream_bpm: float
    longest_stream: int


class AssessmentOut(BaseModel):
    beatmap: BeatmapInfo
    mods: str
    map: MapDemandOut
    pass_rate: float
    fc_rate: float
    median_accuracy: float | None
    median_misses: float | None
    peak_ratios: dict[str, float]
    weakest: str
    familiarity: float = 0.0
    mastery: float = 0.0
    block: dict | None = None  # mindlock: {at_seconds, severity}
    family: str | None = None  # kind of map, for confidence
    confidence: float = 0.0  # -1..1 from recent passes and fails on this kind of map


class NewsOut(BaseModel):
    id: int
    date: date
    type: str
    message: str
    importance: int
    data: dict


class LeaderboardRowOut(BaseModel):
    rank: int | None
    name: str
    country: str
    pp: float
    overall: float | None
    kind: str
    npc_id: int | None
    status: str


class LeaderboardOut(BaseModel):
    date: date
    rows: list[LeaderboardRowOut]
    you: LeaderboardRowOut | None


class NpcOut(BaseModel):
    id: int
    name: str
    country: str
    kind: str
    status: str
    overall: float
    composites: dict[str, float]
    form: float
    pp: float
    rank: int | None
    best_rank: int | None
    titles: int
    away_until: date | None
    note: str
    aliases: list[str] = []
    archetype: str = ""
    pp_potential: float = 0.0
    tournament_strength: float = 0.0
    best_score_types: list[str] = []
    peaks: list[str] = []
    weaknesses: list[str] = []
    match_stats: dict = {}
    development: dict = {}
    storyline: dict = {}
    rival: dict | None = None


class TournamentSummaryOut(BaseModel):
    id: int
    name: str
    tier: str
    rank_min: int
    rank_max: int
    size: int
    team_size: int
    registration_opens: date
    start_date: date
    base_stars: float
    status: str
    user_registered: bool
    can_register: bool
    eligible: bool
    winner: str | None
    user_placement: str | None


class EntryOut(BaseModel):
    id: int
    kind: str
    name: str
    country: str
    seed: int
    npc_id: int | None
    includes_user: bool
    placement: str | None
    members: list[str]


class MatchOut(BaseModel):
    id: int
    key: str
    week: int
    stage: str
    first_to: int
    due: date
    entry_a: int | None
    entry_b: int | None
    winner: int | None
    score_a: int
    score_b: int
    played_on: date | None
    is_user_match: bool
    maps: list[dict]
    commentary: dict | None = None


class TournamentDetailOut(TournamentSummaryOut):
    entries: list[EntryOut]
    matches: list[MatchOut]
    pools: dict[str, list[dict]]


class TournamentsOut(BaseModel):
    date: date
    pending_match: MatchOut | None
    pending_tournament_id: int | None
    tournaments: list[TournamentSummaryOut]


class ThreadSummaryOut(BaseModel):
    id: int
    date: date
    board: str
    kind: str
    title: str
    author: str
    flair: str
    upvotes: int
    comment_count: int
    llm_status: str


class CommentOut(BaseModel):
    id: int
    parent_id: int | None
    author: str
    content: str
    upvotes: int
    source: str


class ThreadOut(ThreadSummaryOut):
    body: str
    comments: list[CommentOut]


class ChatOut(BaseModel):
    id: int
    date: date
    channel: str
    author: str
    content: str
    source: str


class StCareerOut(BaseModel):
    id: int
    name: str
    country: str
    in_game_date: date


class StEventOut(BaseModel):
    id: int
    date: date
    type: str
    handled: bool
    channel: str
    payload: dict
    thread: dict | None
    prompts: dict[str, str]
    schemas: dict[str, dict]


class LlmComment(BaseModel):
    author: str = Field(min_length=1, max_length=48)
    content: str = Field(min_length=1, max_length=4000)
    upvotes: int | None = None
    reply_to: int | None = None  # index of an earlier comment in this batch


class LlmCommentsIn(BaseModel):
    comments: list[LlmComment] = Field(max_length=30)


class LlmThreadComment(BaseModel):
    author: str = Field(min_length=1, max_length=48)
    content: str = Field(min_length=1, max_length=2000)
    upvotes: int | None = None


class LlmThread(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(default="", max_length=4000)
    author: str = Field(min_length=1, max_length=48)
    flair: str | None = None
    upvotes: int | None = None
    comments: list[LlmThreadComment] = Field(default_factory=list, max_length=15)


class LlmThreadsIn(BaseModel):
    threads: list[LlmThread] = Field(max_length=5)


class LlmLine(BaseModel):
    author: str = Field(min_length=1, max_length=48)
    content: str = Field(min_length=1, max_length=1000)


class LlmLinesIn(BaseModel):
    channel: str = Field(min_length=1, max_length=32)
    lines: list[LlmLine] = Field(max_length=30)


class StContextOut(BaseModel):
    text: str


class MapLeaderboardEntryOut(BaseModel):
    rank: int
    kind: str
    name: str
    country: str
    mods: str
    score: int
    accuracy: float
    max_combo: int
    misses: int
    pp: float
    set_on: date
    npc_id: int | None
    source: str | None


class FirstPlaceChangeOut(BaseModel):
    date: date
    sniper: str
    sniped: str
    score: int
    mods: str
    accuracy: float


class MapLeaderboardOut(BaseModel):
    beatmap_id: int
    date: date
    entries: list[MapLeaderboardEntryOut]
    user_rank: int | None
    record_history: list[MapLeaderboardEntryOut] = []
    first_place_history: list[FirstPlaceChangeOut] = []


class PresetOut(BaseModel):
    key: str
    label: str
    description: str
    mods: str
    available: bool


class AutoSessionRequest(BaseModel):
    preset: str
    hours: float = Field(gt=0, le=12)
    stream: bool = False


class ShopItemOut(BaseModel):
    key: str
    name: str
    category: str
    year: int
    month: int
    until: int | None  # last year on sale (None: still sold)
    price: float  # today's price
    launch_price: float
    is_new: bool
    aim: float
    tapping: float
    ar_cap: float | None
    ergonomics: float | None
    notes: str
    available: bool
    owned: bool
    equipped: bool


class ShopOut(BaseModel):
    money: float
    input_device: str
    ergonomics: float
    effects: dict
    items: list[ShopItemOut]


class OccupationIn(BaseModel):
    occupation: str


class PlaystyleIn(BaseModel):
    input_device: str | None = None
    tap_style: str | None = None


class RivalOut(BaseModel):
    npc_id: int
    name: str
    country: str
    kind: str
    rank: int | None
    overall: float
    heat: float
    since: date
    record: dict


class MatchStrategyIn(BaseModel):
    bans: list[str] = Field(default_factory=list, max_length=4)  # slot names in priority order, e.g. ["DT2"]
    picks: list[str] = Field(default_factory=list, max_length=16)


class PoolPracticeRequest(BaseModel):
    tournament_id: int
    week: int = Field(ge=1, le=8)
    hours: float = Field(gt=0, le=12)
    stream: bool = False


class DmIn(BaseModel):
    to: str = Field(min_length=1, max_length=48)
    text: str = Field(min_length=1, max_length=500)


class DuelChallengeIn(BaseModel):
    npc_id: int
    best_of: int = 5
    kind: str = "friendly"
    difficulty: str = "even"
    bans_per_side: int = Field(default=1, ge=0, le=2)


class DuelOut(BaseModel):
    id: int
    date: date
    opponent: str
    opponent_country: str
    opponent_rank: int | None
    kind: str
    best_of: int
    bans_per_side: int
    difficulty: str
    status: str
    pool: list[dict]
    maps: list[dict]
    score_user: int
    score_npc: int
    won: bool | None
    commentary: dict | None = None


class DraftActIn(BaseModel):
    slot: str = Field(min_length=2, max_length=4)


class DraftOut(BaseModel):
    match_id: int
    tournament_id: int
    stage: str
    first_to: int
    finished: bool
    user_side: str
    names: dict[str, str]
    seeds: dict[str, int]
    score: dict[str, int]
    turn: dict
    legal: list[str]
    slots: list[dict]
    bans: dict[str, list[str]]
    first_ban: str
    first_pick: str
    bans_per_side: int
    log: list[dict]
    maps: list[dict]
    warmup: dict
