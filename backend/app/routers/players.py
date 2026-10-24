import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.engine import simulation, character
from app.models import Player
from app.routers.pp import load_and_calculate
from app.schemas import PlayerCreate, PlayerOut, PlayerProfile, ScoreOut, ScoreSubmit, ScoreSubmitResult
from app.engine import scoring
from app.services import (
    beatmap_index,
    condition,
    leaderboards,
    life,
    media,
    osu_files,
    pp,
    profile,
    rivals,
    world_service,
)

router = APIRouter(prefix="/api/players", tags=["players"])


def get_player_or_404(db: Session, player_id: int) -> Player:
    player = db.get(Player, player_id)
    if player is None:
        raise HTTPException(404, f"player {player_id} not found")
    return player


@router.get("", response_model=list[PlayerOut])
def list_players(db: Session = Depends(get_db)) -> list[PlayerOut]:
    return [profile.to_player_out(p) for p in db.scalars(select(Player).order_by(Player.id))]


@router.get("/creation-options")
def creation_options() -> dict:
    return {"budget": character.BUDGET, "perks": character.PERKS,
            "presets": character.PRESETS, "conflicts": character.CONFLICTS}


@router.post("", response_model=PlayerProfile, status_code=status.HTTP_201_CREATED)
def create_player(body: PlayerCreate, db: Session = Depends(get_db)) -> PlayerProfile:
    try:
        perks = character.resolve(body.preset, body.perks, body.unbalanced)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    seed = body.seed if body.seed is not None else secrets.randbits(31)
    occupation = body.occupation or life.default_occupation(body.age)
    if occupation not in life.OCCUPATIONS:
        raise HTTPException(422, f"occupation must be one of {', '.join(life.OCCUPATIONS)}")
    birth = body.start_date - timedelta(days=round(body.age * 365.25))
    player = simulation.new_career(body.name, body.country.upper(), body.start_date, seed, birth, occupation,
                                   body.gender)
    character.apply(player, body.preset, perks, body.unbalanced)
    db.add(player)
    db.flush()
    world_service.ensure_world(db, player)
    condition.ensure_gear(db, player)
    condition.refresh_ergonomics(db, player)
    db.commit()
    beatmap_index.syncer.request(player.in_game_date)
    return profile.to_profile(db, player)


@router.get("/{player_id}", response_model=PlayerProfile)
def get_player(player_id: int, db: Session = Depends(get_db)) -> PlayerProfile:
    return profile.to_profile(db, get_player_or_404(db, player_id))


@router.delete("/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_player(player_id: int, db: Session = Depends(get_db)) -> None:
    db.delete(get_player_or_404(db, player_id))
    db.commit()


@router.post("/{player_id}/scores", response_model=ScoreSubmitResult)
def submit_score(
    player_id: int, body: ScoreSubmit, db: Session = Depends(get_db)
) -> ScoreSubmitResult:
    player = get_player_or_404(db, player_id)
    try:
        beatmap_index.check_playable(db, player.in_game_date, body.beatmap_id)
    except beatmap_index.NotPlayable as e:
        raise HTTPException(e.status_code, str(e)) from e
    meta, mods, result = load_and_calculate(
        body.beatmap_id, body.mods, body.accuracy, body.misses, body.combo
    )
    rank_before = player.global_rank
    facts = leaderboards.map_facts(body.beatmap_id)
    combo = body.combo if body.combo is not None else result.max_combo
    n300, n100, n50 = scoring.counts_from_accuracy(facts.n_objects, body.accuracy, body.misses)
    rec = profile.record_score(
        db,
        player,
        meta,
        mods,
        accuracy=body.accuracy,
        max_combo=body.combo if body.combo is not None else result.max_combo,
        misses=body.misses,
        stars=result.stars,
        pp=result.pp,
        score_value=scoring.score_v1(n300, n100, n50, body.misses, combo, facts.max_combo,
                                     facts.difficulty[""], mods),
        pp_aim=result.pp_aim, pp_speed=result.pp_speed, pp_acc=result.pp_accuracy,
        map_max_combo=result.max_combo,
    )
    snipe = leaderboards.on_user_score(db, player, rec.score)
    if snipe:
        media.snipe_first_place(db, player, f"{meta.artist} - {meta.title} [{meta.version}]", snipe.sniped,
                                snipe.user_entry, leaderboards.map_play_count(db, body.beatmap_id))
        rivals.on_snipe(db, player, snipe.sniped.npc_id, user_sniped=True)
    if rec.top_play_position:
        fc_pp = pp.calculate(osu_files.get_osu_file(body.beatmap_id), mods, accuracy=body.accuracy).pp
        media.score_submission(db, player, rec.score, result.max_combo, fc_pp, rec.top_play_position)
    media.after_action(db, player, rank_before)
    db.commit()
    return ScoreSubmitResult(
        score=ScoreOut.model_validate(rec.score),
        is_new_top_play=rec.top_play_position is not None,
        top_play_position=rec.top_play_position,
        pp_gained=rec.pp_gained,
        player=profile.to_player_out(player),
    )
