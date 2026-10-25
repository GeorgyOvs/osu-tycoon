"""World score stories backed by saved, reproducible plays on ranked maps."""
import random
from datetime import date

from sqlalchemy import func, select
from app.config import OSU_CACHE_DIR
from app.engine import leaderboard as lb, pp_history, world
from app.models import Beatmap, BeatmapSet, MapScore, Npc, Score, WorldState
from app.services import familiarity, leaderboards, map_prefetch, media, osu_files, pp


PREFETCH_BELOW = 60  # keep at least this many era-appropriate maps playable for the world
PREFETCH_BATCH = 6


def _grow_pool(db, on: date, cached_ids: set[int], rng: random.Random) -> None:
    popular = db.execute(select(Beatmap.id).join(BeatmapSet).where(
        BeatmapSet.ranked_date <= on, BeatmapSet.status.in_(("ranked", "approved")), Beatmap.stars.between(3.0, 7.5),
    ).order_by(BeatmapSet.play_count.desc()).limit(500)).scalars().all()
    missing = [i for i in popular if i not in cached_ids]
    if missing:
        map_prefetch.prefetcher.request(rng.sample(missing, min(PREFETCH_BATCH, len(missing))))


def consider(db, player, score, on: date, npc=None):
    """Called only after a score is stored. Real NPCs never receive fictional records."""
    if npc is not None and npc.kind != "procedural":
        return None
    if score.id is None:
        return None
    state = db.get(WorldState, player.id)
    beatmap = db.get(Beatmap, score.beatmap_id)
    if (state is None or beatmap is None or beatmap.beatmapset.ranked_date > on
            or beatmap.beatmapset.status not in ("ranked", "approved")
            or pp_history.era_for(on).ranking != "pp"):
        return None
    value = leaderboards.era_pp(score.beatmap_id, score.mods, score.accuracy,
                                score.misses, score.max_combo, on)
    if npc is not None and value > media.era_top_play_pp(on) * 1.2:
        return None
    score.pp = value
    previous = state.fictional_score_record
    if value <= previous:
        return None
    state.fictional_score_record = value
    first_1000 = previous < 1000 <= value
    if not first_1000 and (value < media.era_top_play_pp(on) * 0.45 or value < previous * 1.01):
        return None
    if npc is not None:
        score.record = True
    db.flush()
    name = npc.name if npc else player.name
    title = f"{beatmap.beatmapset.artist} - {beatmap.beatmapset.title} [{beatmap.version}]"
    suffix = " — first 1000pp score in this fictional world!" if first_1000 else " — fictional-world score record!"
    message = (f"{name} | {title} +{score.mods or 'NM'} ({score.accuracy:.2f}%) "
               f"{score.max_combo}x {score.misses}xMiss | {value:.2f}pp{suffix}")
    return world.WorldNews("FIRST_1000PP" if first_1000 else "NPC_SCORE_RECORD", message, 3, {
        "npc_id": npc.id if npc else None, "score_id": score.id,
        "score_kind": "npc" if npc else "user", "beatmap_id": beatmap.id,
        "beatmapset_id": beatmap.beatmapset_id, "map_title": title,
        "mods": score.mods, "accuracy": score.accuracy, "max_combo": score.max_combo,
        "misses": score.misses, "score_pp": value, "set_on": on.isoformat(),
        "pp_system": pp_history.era_for(on).key,
    })


def weekly(db, player, npcs, on: date, cached_ids: set[int]):
    """Bounded work: two cached, era-available maps and six fictional competitors per week."""
    candidates = list(db.scalars(select(Beatmap).join(BeatmapSet).where(
        Beatmap.id.in_(sorted(cached_ids)), BeatmapSet.ranked_date <= on,
        BeatmapSet.status.in_(("ranked", "approved")), Beatmap.stars >= 3,
    ).order_by(Beatmap.stars.desc(), Beatmap.id).limit(200))) if cached_ids else []
    active = sorted((n for n in npcs if n.kind == "procedural" and n.status == "active"),
                    key=lambda n: (-n.overall, n.id))[:40]
    if len(candidates) < PREFETCH_BELOW:
        _grow_pool(db, on, cached_ids, random.Random(f"prefetch:{player.seed}:{on}"))
    if not candidates or not active:
        return []
    rng = random.Random(f"world-scores:{player.seed}:{on}")
    news = []
    posted = 0
    pp_era = pp_history.era_for(on).ranking == "pp"
    user_best = db.scalar(select(func.max(Score.pp)).where(Score.player_id == player.id)) or 0.0
    for beatmap in rng.sample(candidates, min(3 if len(candidates) >= 20 else 2, len(candidates))):
        try:
            facts = leaderboards.map_facts(beatmap.id)
        except (osu_files.BeatmapNotFound, pp.InvalidBeatmap, ValueError):
            continue
        for npc in rng.sample(active, min(6, len(active))):
            known = db.scalars(select(MapScore).where(
                MapScore.player_id == player.id, MapScore.npc_id == npc.id,
                MapScore.beatmap_id == beatmap.id).order_by(MapScore.score.desc())).first()
            bonus = 0.10 * familiarity.mastery_from(known.attempts, (on - known.set_on).days) if known else 0.0
            est = lb.estimate_best(lb.boost(world.composites(npc.overall, npc.style), bonus), facts, on, 5, rng)
            if known is not None:
                known.attempts += 5  # a replay of a map they already passed
            if est is None:
                continue
            value = leaderboards.era_pp(beatmap.id, est.mods, est.accuracy, est.misses, est.max_combo, on)
            # Reject unrealistic analytic attempts; never fabricate a lower pp value for the same play.
            if value > media.era_top_play_pp(on) * 1.2:
                continue
            current = known
            if current and current.score >= est.score:
                continue
            score = MapScore(player_id=player.id, beatmap_id=beatmap.id, kind="npc", npc_id=npc.id,
                             name=npc.name, country=npc.country, mods=est.mods, score=est.score,
                             accuracy=est.accuracy, max_combo=est.max_combo, misses=est.misses,
                             pp=value, set_on=on, record=False, attempts=(known.attempts if known else 0) + 5)
            db.add(score)
            db.flush()
            event = consider(db, player, score, on, npc)
            if event:
                news.append(event)
            elif pp_era and posted < media.NPC_POSTS_PER_WEEK and media.npc_scorepost(
                    db, player, npc, score, beatmap, value, rng, user_best):
                posted += 1
    return news


def cached_map_ids() -> set[int]:
    return {int(p.stem) for p in OSU_CACHE_DIR.glob("*.osu") if p.stem.isdecimal()}


def repair_legacy_records(db) -> int:
    """Retract old unbacked announcements, preserving the discussion as a correction."""
    from app.models import WorldEvent, ForumThread, StEvent, ChatMessage
    count = 0
    for event in db.scalars(select(WorldEvent).where(WorldEvent.type == "FIRST_1000PP")):
        if event.data.get("score_id") or event.data.get("retracted"):
            continue
        original = event.message
        correction = "Record withdrawn: the old 1000pp announcement had no verified beatmap score."
        event.message = correction
        event.importance = 1
        event.data = {**event.data, "retracted": True, "original_message": original}
        for thread in db.scalars(select(ForumThread).where(
                ForumThread.player_id == event.player_id, ForumThread.title == original[:300])):
            thread.title = "[Retracted] Unverified 1000pp announcement"
            thread.body = f"{correction}\n\nOriginal announcement: {original}"
            thread.flair, thread.llm_status = "Correction", "done"
        for message in db.scalars(select(ChatMessage).where(
                ChatMessage.player_id == event.player_id, ChatMessage.content.contains(original))):
            message.content = correction
        count += 1
        state = db.get(WorldState, event.player_id)
        if state:
            state.fictional_score_record = max((e.data.get("score_pp", 0) for e in db.scalars(
                select(WorldEvent).where(WorldEvent.player_id == event.player_id,
                                         WorldEvent.type.in_(("FIRST_1000PP", "NPC_SCORE_RECORD"))))
                if e.data.get("score_id") and not e.data.get("retracted")), default=0.0)
    for event in db.scalars(select(StEvent).where(StEvent.type == "WORLD_NEWS")):
        data = event.payload.get("data", {})
        if data.get("news_type") == "FIRST_1000PP" and not data.get("score_id") and not data.get("retracted"):
            event.payload = {**event.payload, "data": {**data, "retracted": True,
                             "headline": "Unverified 1000pp record withdrawn", "npc_reactions_needed": []}}
            event.handled = True
    return count
