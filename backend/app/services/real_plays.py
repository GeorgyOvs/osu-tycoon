"""Sync hand-played osu!stable scores into the career database."""
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Player, RealPlay
from app.services import osu_files, pp, stable_files


def _osu_bytes(install: Path, beatmap: stable_files.StableBeatmap, allow_download: bool) -> bytes | None:
    local = install / "Songs" / beatmap.folder / beatmap.file
    if local.is_file():
        return local.read_bytes()
    if not allow_download:
        return None
    try:
        return osu_files.get_osu_file(beatmap.beatmap_id)
    except Exception:  # offline or unranked: the play is still recorded, just without pp
        return None


def _evaluate(content: bytes | None, play: stable_files.StableScore) -> pp.PpResult | None:
    if content is None:
        return None
    try:
        return pp.calculate(content, play.mods, misses=play.nmiss, combo=play.max_combo,
                            n100=play.n100, n50=play.n50)
    except (pp.InvalidBeatmap, pp.InvalidMods):
        return None


def sync(db: Session, player: Player, install: Path | None = None) -> list[RealPlay]:
    """Store scores not seen yet and return them. The very first sync marks everything as baseline."""
    install = install or stable_files.default_install_dir()
    scores = stable_files.load_scores(install)
    beatmaps = stable_files.load_beatmaps(install)
    known = set(db.scalars(select(RealPlay.replay_md5).where(RealPlay.player_id == player.id)))
    first_sync = not known
    added: list[RealPlay] = []
    for play in sorted(scores, key=lambda p: p.played_at):
        beatmap = beatmaps.get(play.beatmap_md5)
        if play.replay_md5 in known or beatmap is None or beatmap.beatmap_id <= 0:
            continue
        known.add(play.replay_md5)
        result = _evaluate(_osu_bytes(install, beatmap, allow_download=not first_sync), play)
        row = RealPlay(
            player_id=player.id, replay_md5=play.replay_md5, beatmap_md5=play.beatmap_md5,
            beatmap_id=beatmap.beatmap_id, beatmapset_id=beatmap.beatmapset_id, artist=beatmap.artist,
            title=beatmap.title, difficulty_name=beatmap.version, mods=play.mods, n300=play.n300,
            n100=play.n100, n50=play.n50, misses=play.nmiss, max_combo=play.max_combo,
            accuracy=play.accuracy, score_value=play.score, stars=result.stars if result else 0.0,
            pp=result.pp if result else 0.0, played_at=play.played_at, baseline=first_sync,
        )
        db.add(row)
        added.append(row)
    db.flush()
    return added
