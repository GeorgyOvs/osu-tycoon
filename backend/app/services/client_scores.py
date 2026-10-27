"""Scores sent by the tycoon client (personal osu!lazer fork) after each attempt."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ClientLink, Player, RealPlay
from app.services import hand_play, osu_files, pp

STATUSES = ("passed", "failed", "quit")


class NoActivePlayer(LookupError):
    pass


def active_player(db: Session) -> Player | None:
    link = db.get(ClientLink, 1)
    return db.get(Player, link.player_id) if link and link.player_id else None


def set_active_player(db: Session, player: Player) -> None:
    link = db.get(ClientLink, 1) or ClientLink(id=1)
    link.player_id = player.id
    db.add(link)


def known_mods(acronyms: list[str]) -> str:
    """Lazer acronyms -> engine mods. Lazer-only mods (CL, DA, the career mod CR, ...) are dropped."""
    found = [a.upper() for a in acronyms if a.upper() in pp.MOD_ORDER]
    return pp.normalize_mods("".join(found))


def record(db: Session, *, client_score_id: str, beatmap_id: int, beatmap_md5: str, artist: str, title: str,
           version: str, mods: list[str], n300: int, n100: int, n50: int, misses: int, max_combo: int,
           accuracy: float, total_score: int, status: str, progress: float, played_at,
           assist: dict[str, float] | None = None) -> RealPlay:
    player = active_player(db)
    if player is None:
        raise NoActivePlayer("open a career in the tycoon UI first; the client plays for that player")
    existing = db.scalar(select(RealPlay).where(RealPlay.player_id == player.id,
                                                RealPlay.replay_md5 == client_score_id))
    if existing is not None:  # the client retried the request
        return existing
    norm = known_mods(mods)
    result = None
    if beatmap_id > 0:
        try:
            content = osu_files.get_osu_file(beatmap_id)
            result = pp.calculate(content, norm, misses=misses, combo=max_combo, n100=n100, n50=n50)
        except Exception:  # offline, unknown map or unsupported file: keep the play without pp
            result = None
    row = RealPlay(
        player_id=player.id, replay_md5=client_score_id, beatmap_md5=beatmap_md5, beatmap_id=beatmap_id,
        artist=artist, title=title, difficulty_name=version, mods=norm, n300=n300, n100=n100, n50=n50,
        misses=misses, max_combo=max_combo, accuracy=accuracy, score_value=total_score,
        stars=result.stars if result else 0.0,
        pp=result.pp if result and status == "passed" else 0.0,
        played_at=played_at, source="client", status=status, progress=max(0.0, min(1.0, progress)),
        assist=assist or {},
    )
    db.add(row)
    db.flush()
    outcome = hand_play.on_attempt(db, player, beatmap_id=beatmap_id, mods=norm, n300=n300, n100=n100, n50=n50,
                                   misses=misses, max_combo=max_combo, accuracy=accuracy, status=status,
                                   progress=row.progress)
    if outcome.recorded is not None:
        row.career_score_id = outcome.recorded.score.id
        row.pp = outcome.recorded.score.pp  # the era's pp, as the career counts it
    row.career_note = (outcome.reason or "")[:256]
    if beatmap_id > 0:
        from app.services import draft, media  # draft -> tournaments is heavy; only needed here

        rank_before = player.global_rank
        note, news = draft.on_hand_play(db, player, beatmap_id=beatmap_id, mods=norm, accuracy=accuracy,
                                        max_combo=max_combo, misses=misses, status=status, completion=row.progress)
        if note:
            row.career_note = "; ".join(x for x in (note, row.career_note) if x)[:256]
        if news:
            media.after_action(db, player, rank_before, news=news)
    return row
