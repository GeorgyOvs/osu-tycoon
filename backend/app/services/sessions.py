"""Play sessions: a day spent playing ranked maps, attempt by attempt."""

import math
import random
from dataclasses import dataclass, field
from functools import lru_cache

from sqlalchemy.orm import Session

from app.engine import psychology
from app.engine import play, pp_history, scoring, simulation
from app.engine.map_analysis import MapProfile, analyze
from app.engine.training import ERA_ORDER, Drill
from app.models import MapBoard, Player
from app.models import Beatmap
from app.services import (
    mindlock,
    profile_stats,
    beatmap_index,
    condition,
    familiarity,
    life,
    media,
    osu_files,
    pp,
    profile,
    rivals,
    streaming,
)

MAX_SESSION_HOURS = 14.0
PLAY_STRAIN = 1.6  # competitive play wears you out more than the same hours of casual practice
ATTEMPT_OVERHEAD_S = 25.0  # song select, retry, a breather
WARMUP = (0.94, 0.97)  # capability on the first and second attempt of the day


class SessionError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class PlayRequest:
    beatmap_id: int
    mods: str = ""
    attempts: int = 1


@dataclass
class AttemptResult:
    attempt: play.Attempt
    pp: float | None  # under the current era's rules
    perf: pp.PpResult | None = None  # today's formula, with components
    replay: dict = field(default_factory=dict)


@dataclass
class PlayResult:
    meta: osu_files.BeatmapMeta
    mods: str
    stars: float
    attempts: list[AttemptResult]
    best_index: int | None
    recorded: profile.Recorded | None


@dataclass
class SessionResult:
    hours: float
    plays: list[PlayResult]
    action: simulation.ActionResult
    training: dict[str, float] = field(default_factory=dict)


@lru_cache(maxsize=128)
def map_profile(beatmap_id: int, mods: str) -> MapProfile:
    return analyze(osu_files.get_osu_file(beatmap_id), mods)


def _prepare(db: Session, player: Player, req: PlayRequest) -> tuple[osu_files.BeatmapMeta, str, MapProfile]:
    try:
        beatmap_index.check_playable(db, player.in_game_date, req.beatmap_id)
        mods = pp.normalize_mods(req.mods)
        content = osu_files.get_osu_file(req.beatmap_id)
        prof = map_profile(req.beatmap_id, mods)
    except beatmap_index.NotPlayable as e:
        raise SessionError(e.status_code, str(e)) from e
    except pp.InvalidMods as e:
        raise SessionError(422, str(e)) from e
    except osu_files.BeatmapNotFound as e:
        raise SessionError(404, str(e)) from e
    if not prof.objects:
        raise SessionError(422, f"beatmap {req.beatmap_id} has no hit objects")
    return osu_files.parse_meta(req.beatmap_id, content), mods, prof


def day_modifiers(player: Player) -> play.DayModifiers:
    return play.DayModifiers(form=player.form, fatigue=player.fatigue, motivation=player.motivation)


def _challenge(attempt: play.Attempt) -> float:
    """Learning is fastest at the edge of ability, slow on trivial or hopeless maps."""
    peak = max(attempt.peak_ratios.get(k, 0.0) for k in ("aim", "tapping", "reading"))
    return 0.35 + 0.85 * math.exp(-(((peak - 1.05) / 0.25) ** 2))


@dataclass
class Played:
    plays: list[PlayResult]
    skipped: list[str]  # maps that couldn't be loaded (missing from the mirror, unplayable...)
    elapsed: float  # seconds including the breaks between attempts
    play_seconds: float
    targets: dict[str, float]  # sub-stat -> weighted seconds of demand
    challenge_time: float
    strain_time: float

    def as_drill(self) -> Drill:
        """What these plays trained, shaped by what the maps demanded."""
        seconds = max(1.0, self.play_seconds)
        top = max(self.targets.values(), default=1.0)
        return Drill(
            key="ranked_play",
            label="Playing ranked maps",
            description="A session of ranked maps.",
            targets={k: v / top for k, v in self.targets.items()} or {"low_mid_bpm": 1.0},
            strain=PLAY_STRAIN * (self.strain_time / seconds if self.strain_time else 1.0),
            era_efficiency={era: (self.challenge_time / seconds if self.challenge_time else 1.0) for era in ERA_ORDER},
        )


def check_can_play(player: Player) -> None:
    if player.injury == simulation.SEVERE_RSI:
        raise SessionError(409, f"recovering from severe RSI until {player.injury_until}")
    from app.services import integrity

    try:
        integrity.check_unrestricted(player)
    except integrity.IntegrityError as e:
        raise SessionError(e.status_code, str(e)) from e


def _prepare_all(db: Session, player: Player, requests: list[PlayRequest]) -> tuple[list, list[str]]:
    """Prepare what can be played; maps that fail to load are dropped (and purged from the index)."""
    ok, skipped, first_error = [], [], None
    for req in requests:
        try:
            ok.append((req, *_prepare(db, player, req)))
        except SessionError as e:
            first_error = first_error or e
            if e.status_code == 404:
                bm = db.get(Beatmap, req.beatmap_id)
                if bm is not None:
                    db.delete(bm)
            skipped.append(f"{req.beatmap_id}: {e}")
    if not ok:
        raise SessionError(first_error.status_code if first_error else 404, "none of the chosen maps could be played: " + "; ".join(skipped[:3]))
    return ok, skipped


def play_maps(db: Session, player: Player, requests: list[PlayRequest], tag: str = "session",
              pressure: float = 1.0, prepared: tuple[list, list[str]] | None = None) -> Played:
    """Simulate every attempt and record the best pass per map. Doesn't advance the calendar."""
    prepared, skipped = prepared or _prepare_all(db, player, requests)
    skills = condition.play_skills(db, player)
    day = day_modifiers(player)
    day.pressure = pressure
    out = Played([], skipped, 0.0, 0.0, {}, 0.0, 0.0)
    tilt = 0.0
    played_count = 0
    placements = [0 if tag == "training" else PLACEMENT_BUDGET]

    for idx, (req, meta, mods, prof) in enumerate(prepared):
        attempts: list[AttemptResult] = []
        fam = psychology.family(prof, mods)
        map_skills = psychology.scale_skills(skills, psychology.confidence(player, fam, player.in_game_date))
        for k in range(req.attempts):
            day.warmup = WARMUP[played_count] if played_count < len(WARMUP) else 1.0
            day.session_hours = out.elapsed / 3600
            day.tilt = tilt
            day.familiarity = familiarity.level(db, player, req.beatmap_id)
            day.mastery = familiarity.mastery(db, player, req.beatmap_id)
            block = mindlock.current(db, player, req.beatmap_id, day.mastery)
            day.block_bucket, day.block_severity = block if block else (None, 0.0)
            rng = random.Random(f"{player.seed}:{player.in_game_date.isoformat()}:{tag}:{idx}:{k}")
            a = play.simulate(prof, map_skills, mods, day, rng)
            note = mindlock.record(db, player, req.beatmap_id, a, len(prof.objects), prof.drain_seconds,
                                   map_skills["nerve_resistance"], map_skills["tilt_resilience"])
            if note:
                a.key_moments.append(note)
            psychology.record_attempt(player, fam, a.passed, a.choked, a.misses, player.in_game_date)
            familiarity.record_attempt(db, player, req.beatmap_id, 1.0 if a.passed else a.fail_progress or 0.0)

            seconds = a.fail_time if a.fail_time is not None else prof.drain_seconds
            out.elapsed += seconds + ATTEMPT_OVERHEAD_S
            out.play_seconds += seconds
            profile_stats.add_play(player, seconds, a.n300 + a.n100 + a.n50, a.max_combo)
            played_count += 1
            if not a.passed:
                tilt += 1.0
            elif a.choked:
                tilt += 0.7
            elif a.misses == 0:
                tilt = max(0.0, tilt - 1.0)

            played = len(prof.objects) if a.passed else round((a.fail_progress or 0) * len(prof.objects))
            for key, share in play.training_targets(prof, mods, max(1, played)).items():
                out.targets[key] = out.targets.get(key, 0.0) + share * seconds
            out.challenge_time += _challenge(a) * seconds
            fast_streams = sum(1 for o in prof.objects if (o.stream_bpm or 0) > 200) / len(prof.objects)
            out.strain_time += (1 + 0.8 * fast_streams) * seconds

            score_pp, perf = None, None
            if a.passed:
                perf = pp.calculate(
                    osu_files.get_osu_file(req.beatmap_id), mods, misses=a.misses,
                    combo=a.max_combo, n100=a.n100, n50=a.n50,
                )
                score_pp = pp_history.adjust(perf.pp, perf.pp_aim, perf.pp_speed, perf.pp_accuracy, a.max_combo,
                                             prof.max_combo, pp_history.era_for(player.in_game_date))
            attempts.append(AttemptResult(a, score_pp, perf, a.replay(prof)))

        passes = [i for i, ar in enumerate(attempts) if ar.pp is not None]
        best = max(passes, key=lambda i: attempts[i].pp or 0.0) if passes else None
        recorded = (_record_best(db, player, req, meta, mods, prof, attempts[best], placements)
                    if best is not None else None)
        out.plays.append(PlayResult(meta, mods, prof.stars, attempts, best, recorded))
    return out


PLACEMENT_BUDGET = 2  # boards that must be simulated from scratch cost ~1-2s each; the rest show up on demand


def _record_best(db: Session, player: Player, req: PlayRequest, meta, mods: str, prof: MapProfile,
                 best: AttemptResult, placements: list[int] | None = None) -> profile.Recorded:
    from app.services import leaderboards  # leaderboards needs map_profile from this module

    a = best.attempt
    difficulty = leaderboards.map_facts(req.beatmap_id).difficulty[""]
    perf = best.perf
    recorded = profile.record_score(
        db, player, meta, mods, accuracy=a.accuracy, max_combo=a.max_combo,
        misses=a.misses, stars=prof.stars, pp=perf.pp if perf else 0.0,
        score_value=scoring.score_v1(a.n300, a.n100, a.n50, a.misses, a.max_combo, prof.max_combo, difficulty, mods),
        pp_aim=perf.pp_aim if perf else 0.0, pp_speed=perf.pp_speed if perf else 0.0,
        pp_acc=perf.pp_accuracy if perf else 0.0, map_max_combo=prof.max_combo,
    )
    board = db.get(MapBoard, (player.id, req.beatmap_id))
    fresh = board is not None and board.generated_through >= player.in_game_date
    if fresh or (placements and placements[0] > 0):
        if not fresh and placements:
            placements[0] -= 1
        placed = leaderboards.placement(db, player, req.beatmap_id, recorded.score.score_value)
    else:
        placed = None
    if placed:
        recorded.board_rank, recorded.board_size = placed
    snipe = leaderboards.on_user_score(db, player, recorded.score)
    if snipe:
        media.snipe_first_place(db, player, f"{meta.artist} - {meta.title} [{meta.version}]", snipe.sniped,
                                snipe.user_entry, leaderboards.map_play_count(db, req.beatmap_id))
        rivals.on_snipe(db, player, snipe.sniped.npc_id, user_sniped=True)
    if recorded.top_play_position:
        fc_pp = pp.calculate(osu_files.get_osu_file(req.beatmap_id), mods, accuracy=a.accuracy).pp
        media.score_submission(db, player, recorded.score, prof.max_combo, fc_pp, recorded.top_play_position)
    return recorded


def run_session(db: Session, player: Player, requests: list[PlayRequest], stream: bool = False) -> SessionResult:
    """A day spent playing these maps: attempts, scores, then the day's training and fatigue."""
    check_can_play(player)
    planned = 0.0
    ready = _prepare_all(db, player, requests)
    for req, _meta, _mods, prof in ready[0]:
        planned += req.attempts * (prof.drain_seconds + ATTEMPT_OVERHEAD_S)
    if planned / 3600 > MAX_SESSION_HOURS:
        raise SessionError(422, f"that's {planned / 3600:.1f}h of playing; the limit is {MAX_SESSION_HOURS:g}h a day")
    try:
        life.check_hours(player, planned / 3600)
    except life.LifeError as e:
        raise SessionError(e.status_code, str(e)) from e

    if stream:
        try:
            streaming.check(player)
        except streaming.StreamError as e:
            raise SessionError(e.status_code, str(e)) from e
    start = player.in_game_date
    played = play_maps(db, player, requests, pressure=streaming.LIVE_PRESSURE if stream else 1.0, prepared=ready)
    stream_events = streaming.apply(db, player, played.plays, played.elapsed / 3600) if stream else []
    drill = played.as_drill()
    hours = played.elapsed / 3600
    learning, caps = condition.learning_extras(db, player)
    action = simulation.run_days(player, simulation.DayPlan(drill=drill, hours=hours, learning=learning, caps=caps), 1)
    action.events += stream_events + life.apply_days(player, start, player.in_game_date, hours)
    condition.progress_adaptation(player, hours)
    return SessionResult(hours=hours, plays=played.plays, action=action, training=drill.targets)
