"""Player profile state: aggregates, serialization and score submission."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import PP_WEIGHT_DECAY
from app.engine import attributes as A
from app.engine import pp_history, simulation, world
from app.engine.training import ERA_LABELS, era_for
from app.models import Player, Score
from app.schemas import (
    AttributeGroupOut,
    InjuryOut,
    LifeOut,
    PlayerConditions,
    PlayerOut,
    PlayerProfile,
    ScoreOut,
    SubStatOut,
    TopPlay,
)
from app.services import life, ranking
from app.services.osu_files import BeatmapMeta


NEW_TOP_PLAY_MOTIVATION = 3.0


@dataclass
class Recorded:
    score: Score
    top_play_position: int | None
    pp_gained: float


def record_score(
    db: Session,
    player: Player,
    meta: BeatmapMeta,
    mods: str,
    accuracy: float,
    max_combo: int,
    misses: int,
    stars: float,
    pp: float,
    score_value: int = 0,
    pp_aim: float = 0.0,
    pp_speed: float = 0.0,
    pp_acc: float = 0.0,
    map_max_combo: int = 0,
) -> Recorded:
    """Store a passed play and refresh the profile aggregates. Caller commits."""
    old_total = player.total_pp
    score = Score(
        player_id=player.id,
        beatmap_id=meta.beatmap_id,
        beatmapset_id=meta.beatmapset_id,
        artist=meta.artist,
        title=meta.title,
        difficulty_name=meta.version,
        mods=mods,
        accuracy=accuracy,
        max_combo=max_combo,
        misses=misses,
        stars=stars,
        pp=pp_history.adjust(pp, pp_aim, pp_speed, pp_acc, max_combo, map_max_combo,
                             pp_history.era_for(player.in_game_date)),
        pp_modern=pp,
        pp_aim=pp_aim,
        pp_speed=pp_speed,
        pp_acc=pp_acc,
        map_max_combo=map_max_combo,
        score_value=score_value,
        played_on=player.in_game_date,
    )
    db.add(score)
    db.flush()
    top = recompute_aggregates(db, player)
    from app.services import score_records, tournaments, media
    event = score_records.consider(db, player, score, player.in_game_date)
    if event:
        news = []
        tournaments._news(db, player, player.in_game_date, event.type, event.message,
                          event.importance, event.data, news)
        media.world_headline(db, player, news[0])
    position = next((i + 1 for i, s in enumerate(top) if s.id == score.id), None)
    if position is not None and position <= 10:
        # Only a real step up is a thrill: scaled by how good the play is for the era, and diminishing.
        significance = min(1.0, pp / (ranking.top_pp(player.in_game_date) / 18))
        player.motivation = min(100.0, player.motivation + NEW_TOP_PLAY_MOTIVATION * significance
                                * (1 - player.motivation / 100))
    return Recorded(score, position, player.total_pp - old_total)


def reprice_scores(db: Session, player: Player) -> None:
    """Re-evaluate every score under the pp rules of the player's current date."""
    era = pp_history.era_for(player.in_game_date)
    for s in player_scores(db, player):
        if not s.pp_modern:
            s.pp_modern = s.pp  # scores saved before eras were tracked
        s.pp = pp_history.adjust(s.pp_modern, s.pp_aim, s.pp_speed, s.pp_acc, s.max_combo, s.map_max_combo,
                                 era, (player.in_game_date - s.played_on).days)


def player_scores(db: Session, player: Player) -> list[Score]:
    return list(db.scalars(select(Score).where(Score.player_id == player.id)))


def recompute_aggregates(db: Session, player: Player) -> list[Score]:
    """Refresh total PP, accuracy and rank from stored scores. Returns current top plays."""
    scores = player_scores(db, player)
    top = ranking.top_plays(scores)

    player.total_pp = ranking.weighted_pp([s.pp for s in top])
    player.accuracy = ranking.weighted_accuracy(top)
    player.play_count = len(scores)

    new_rank = ranking.estimate_global_rank(player.total_pp, player.in_game_date)
    if new_rank != player.global_rank:
        player.previous_rank = player.global_rank
        player.global_rank = new_rank
    return top


def attribute_groups(player: Player) -> list[AttributeGroupOut]:
    attrs = {a.key: a for a in player.attributes}
    values = simulation.effective_values(player)
    return [
        AttributeGroupOut(
            key=group.key,
            label=group.label,
            value=A.composite(values, group),
            subs=[
                SubStatOut(
                    key=sub.key,
                    label=sub.label,
                    value=values[sub.key],
                    base=attrs[sub.key].base,
                    cap=attrs[sub.key].cap,
                    rust=attrs[sub.key].rust,
                    plateau=attrs[sub.key].plateau,
                )
                for sub in group.subs
            ],
        )
        for group in A.GROUPS
    ]


def _pp_system(player: Player) -> dict:
    era = pp_history.era_for(player.in_game_date)
    return {"key": era.key, "name": era.name, "summary": era.summary, "ranking": era.ranking,
            "since": era.start.isoformat()}


def to_player_out(player: Player) -> PlayerOut:
    era = era_for(player.in_game_date)
    comps = A.composites(simulation.effective_values(player))
    return PlayerOut(
        id=player.id,
        character_build=player.character_build or {},
        name=player.name,
        country=player.country,
        in_game_date=player.in_game_date,
        era=era.value,
        era_label=ERA_LABELS[era],
        overall=A.overall(simulation.effective_values(player)),
        pp_potential=world.pp_overall(comps, player.in_game_date),
        tournament_strength=world.tournament_overall(comps),
        potential=player.potential,
        form=player.form,
        traits=simulation.traits(player),
        ergonomics=player.ergonomics,
        attributes=attribute_groups(player),
        conditions=PlayerConditions(
            fatigue=player.fatigue,
            motivation=player.motivation,
            morale=player.morale,
            consecutive_training_days=player.consecutive_training_days,
        ),
        injury=InjuryOut(
            state=player.injury,
            until=player.injury_until,
            strain_recovery_days=player.strain_recovery_days,
            physio_days=player.physio_days,
        ),
        total_pp=player.total_pp,
        accuracy=player.accuracy,
        play_count=player.play_count,
        global_rank=player.global_rank,
        previous_rank=player.previous_rank,
        pp_system=_pp_system(player),
        badges=list(player.badges or []),
        life=LifeOut(
            gender=player.gender,
            pronouns=life.pronouns(player),
            age=round(life.age(player), 1) if player.birth_date else None,
            occupation=player.occupation,
            money=round(player.money, 2),
            free_hours_today=life.free_hours(player, player.in_game_date),
            followers=player.followers,
            input_device=player.input_device,
            tap_style=player.tap_style,
            style_adaptation=round(player.style_adaptation, 3),
        ),
    )


def to_profile(db: Session, player: Player, recent_limit: int = 10) -> PlayerProfile:
    scores = player_scores(db, player)
    top = ranking.top_plays(scores)
    recent = sorted(scores, key=lambda s: (s.played_on, s.id), reverse=True)[:recent_limit]

    top_out = []
    for i, s in enumerate(top):
        weight = PP_WEIGHT_DECAY**i
        top_out.append(
            TopPlay(
                **ScoreOut.model_validate(s).model_dump(), weight=weight, weighted_pp=s.pp * weight
            )
        )

    return PlayerProfile(
        **to_player_out(player).model_dump(),
        top_plays=top_out,
        recent_scores=[ScoreOut.model_validate(s) for s in recent],
    )
