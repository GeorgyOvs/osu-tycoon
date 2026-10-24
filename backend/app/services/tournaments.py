"""Tournaments in the living world: calendar, brackets, NPC matches and the user's matches."""

import random
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import bracket, match, play, simulation, world
from app.engine.world_data import COUNTRIES, TIER_STARS, TOURNAMENTS
from app.models import Beatmap, BeatmapSet, Match, Npc, Player, Tournament, TournamentEntry, WorldEvent, WorldState
from app.services import condition, familiarity, media, osu_files, pp, ranking, rivals, sessions

REGISTRATION_DAYS = 28
UNRANKED = 10_000_000
OWC_TEAM_SIZE = 3


class TournamentError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class News:
    date: date
    type: str
    message: str
    importance: int
    data: dict


def _news(db: Session, player: Player, on: date, type_: str, message: str, importance: int, data: dict | None,
          out: list) -> None:
    db.add(WorldEvent(player_id=player.id, date=on, type=type_, message=message, data=data or {},
                      importance=importance))
    out.append(News(on, type_, message, importance, data or {}))


# --- calendar ---------------------------------------------------------------------------


def generate_through(db: Session, player: Player, state: WorldState, year: int) -> None:
    for y in range(state.generated_through + 1, year + 1):
        for tpl in TOURNAMENTS:
            if not tpl.first_year <= y <= tpl.last_year:
                continue
            start = date(y, tpl.month, tpl.day)
            if start < player.in_game_date - timedelta(days=60):
                continue  # long over before this career began
            db.add(Tournament(
                player_id=player.id, template=tpl.key, name=tpl.name.format(year=y), tier=tpl.tier,
                rank_min=tpl.rank_min, rank_max=tpl.rank_max, size=tpl.size, team_size=tpl.team_size,
                registration_opens=start - timedelta(days=REGISTRATION_DAYS), start_date=start,
                base_stars=round(TIER_STARS[tpl.tier] * match.era_star_factor(start), 2),
                status="upcoming", user_registered=False, pools={}, winner_entry_id=None,
            ))
        state.generated_through = y
    db.flush()


def due_date(t: Tournament, week: int) -> date:
    return t.start_date + timedelta(days=7 * (week - 1))


def user_rank(player: Player) -> int:
    return player.global_rank or UNRANKED


# Badge-weighted seeding (community standard): rank^(0.9937^(badges^2)). Badged players count as
# higher ranked, so they can't farm rank-restricted tournaments. Approximate adoption date.
BWS_FROM = date(2019, 1, 1)
BADGE_TIERS = ("open", "major", "owc")


def seeding_rank(player: Player, t: Tournament) -> float:
    rank = user_rank(player)
    badges = len(player.badges or [])
    if badges and t.start_date >= BWS_FROM and t.tier in ("open", "major"):
        return rank ** (0.9937 ** (badges**2))
    return rank


def eligible(player: Player, t: Tournament) -> bool:
    return t.tier != "owc" and t.rank_min <= seeding_rank(player, t) <= t.rank_max


# --- starting a tournament ----------------------------------------------------------------


def _filler(rng: random.Random, t: Tournament, taken: set[str], country: str | None = None,
            rank: float | None = None) -> dict:
    """A one-off entrant whose strength sits inside the tournament's rank band."""
    lo, hi = max(1, t.rank_min), min(t.rank_max, 1_500_000)
    target = rank if rank is not None else lo * (hi / lo) ** rng.random()
    p = ranking.pp_for_rank(target, t.start_date)
    overall = world.overall_for_pp(p, t.start_date)
    style = {g: rng.uniform(-1, 1) for g in world.GROUP_KEYS}
    return {"name": world.generate_name(rng, taken), "country": country or world.generate_country(rng),
            "kind": "filler", "npc_id": None, "pp": p, "seed": rng.randint(0, 2**31 - 1),
            "composites": world.composites(overall, style)}


def _npc_member(n: Npc) -> dict:
    return {"name": n.name, "country": n.country, "kind": "npc", "npc_id": n.id, "pp": n.pp, "seed": n.seed,
            "composites": world.composites(n.overall, n.style)}


def _user_member(player: Player) -> dict:
    return {"name": player.name, "country": player.country, "kind": "user", "npc_id": None,
            "pp": player.total_pp, "seed": player.seed,
            "composites": A.composites(simulation.effective_values(player))}


def _mean_comps(members: list[dict]) -> dict[str, float]:
    return {g: sum(m["composites"][g] for m in members) / len(members) for g in world.GROUP_KEYS}


def _solo_field(db: Session, player: Player, t: Tournament, rng: random.Random, taken: set[str]) -> list[dict]:
    npcs = [n for n in db.scalars(select(Npc).where(Npc.player_id == player.id, Npc.status == "active"))
            if n.rank and t.rank_min <= n.rank <= t.rank_max]
    rng.shuffle(npcs)
    if t.user_registered:  # rivals make a point of entering the same tournaments
        hunting = rivals.rival_npc_ids(db, player)
        npcs.sort(key=lambda n: n.id not in hunting)
    slots = t.size - (1 if t.user_registered else 0)
    field = [_npc_member(n) for n in npcs[: int(slots * 0.75)]]  # leave room for unknown hopefuls
    while len(field) < slots:
        field.append(_filler(rng, t, taken))
    if t.user_registered:
        field.append(_user_member(player))
    return field


def _owc_field(db: Session, player: Player, t: Tournament, rng: random.Random, taken: set[str],
               out: list) -> list[dict]:
    countries = dict(COUNTRIES)
    countries.setdefault(player.country, 1)
    active = [n for n in db.scalars(select(Npc).where(Npc.player_id == player.id, Npc.status == "active")) if n.rank]
    teams = []
    for country, weight in countries.items():
        members = sorted((_npc_member(n) for n in active if n.country == country), key=lambda m: -m["pp"])
        if country == player.country and player.total_pp > 0:
            better = sum(1 for m in members if m["pp"] > player.total_pp)
            if better < OWC_TEAM_SIZE:
                members.insert(better, _user_member(player))
        members = members[:OWC_TEAM_SIZE]
        best_rank = 30 * (15 / weight) ** 1.6  # deep scenes have stronger benches
        while len(members) < OWC_TEAM_SIZE:
            members.append(_filler(rng, t, taken, country, rank=best_rank * (1 + 2 * len(members)) * rng.uniform(0.7, 1.5)))
        teams.append({"name": f"Team {country}", "country": country, "kind": "team", "npc_id": None,
                      "pp": sum(m["pp"] for m in members) / len(members), "seed": rng.randint(0, 2**31 - 1),
                      "composites": _mean_comps(members), "members": members,
                      "includes_user": any(m["kind"] == "user" for m in members)})
    teams.sort(key=lambda e: -e["pp"])
    field = teams[: t.size]
    while len(field) < t.size:  # never short of a full bracket
        members = [_filler(rng, t, taken, rank=5000 * rng.uniform(1, 4)) for _ in range(OWC_TEAM_SIZE)]
        field.append({"name": f"Team {members[0]['country']}", "country": members[0]["country"], "kind": "team",
                      "npc_id": None, "pp": sum(m["pp"] for m in members) / len(members),
                      "seed": rng.randint(0, 2**31 - 1), "composites": _mean_comps(members), "members": members,
                      "includes_user": False})
    if any(e["includes_user"] for e in field):
        t.user_registered = True
        _news(db, player, t.start_date, "OWC_SELECTED",
              f"You've been selected for Team {player.country} at {t.name}!", 3, {"tournament_id": t.id}, out)
    return field


def start(db: Session, player: Player, t: Tournament, out: list) -> None:
    rng = random.Random(f"{player.seed}:tournament:{t.id}")
    taken = set(db.scalars(select(Npc.name).where(Npc.player_id == player.id)))
    field = _owc_field(db, player, t, rng, taken, out) if t.tier == "owc" else _solo_field(db, player, t, rng, taken)
    if t.tier != "owc" and t.user_registered:
        field = _qualifiers(db, player, t, field, rng, out)
    else:
        field.sort(key=lambda e: -e["pp"])  # seed by strength
    entries = []
    for seed, e in enumerate(field, start=1):
        entry = TournamentEntry(
            kind=e["kind"], npc_id=e["npc_id"], name=e["name"], country=e["country"], seed=seed,
            composites={**e["composites"], "_seed": e["seed"]}, members=e.get("members", []),
            includes_user=e["kind"] == "user" or e.get("includes_user", False), placement=None,
        )
        t.entries.append(entry)
        entries.append(entry)
    for spec in bracket.double_elimination(t.size):
        t.matches.append(Match(key=spec.key, order=spec.order, week=spec.week, stage=spec.stage,
                               first_to=spec.first_to, source_a=spec.source_a, source_b=spec.source_b,
                               score_a=0, score_b=0, maps=[]))
    t.status = "ongoing"
    db.flush()


# --- progressing brackets -----------------------------------------------------------------


QUALIFIER_SCALE = 250_000


def _qualifiers(db: Session, player: Player, t: Tournament, field: list[dict], rng: random.Random,
                out: list) -> list[dict]:
    """Everyone plays the first-stage pool once (TB excluded); seeds follow the totals."""
    slots = [s for s in pool_for(t, 1) if s.slot != "TB"]
    known = [familiarity.level(db, player, s.beatmap_id) for s in slots if s.beatmap_id]
    practice = 1 + 0.05 * (sum(known) / len(known) if known else 0.0)  # practising the pool pays off
    results = []
    for e in field:
        if e["kind"] == "user":
            comps, form, bonus = A.composites(condition.play_skills(db, player)), player.form, practice
        else:
            npc = db.get(Npc, e["npc_id"]) if e.get("npc_id") else None
            comps, form, bonus = e["composites"], npc.form if npc else 0.0, 1.0
        total = sum(world.map_performance(comps, s.slot, s.stars, form, rng) * bonus for s in slots)
        results.append((round(total * QUALIFIER_SCALE), e))
    results.sort(key=lambda r: -r[0])
    t.pools = {**t.pools, "qualifiers": [
        {"seed": i, "name": e["name"], "country": e["country"], "kind": e["kind"], "score": score}
        for i, (score, e) in enumerate(results, start=1)
    ]}
    place = next(i for i, (_, e) in enumerate(results, start=1) if e["kind"] == "user")
    _news(db, player, t.start_date, "QUALIFIERS", f"{t.name} qualifiers: you placed #{place} of {len(results)}.",
          2, {"tournament_id": t.id, "seed": place}, out)
    return [e for _, e in results]


def reveal_pools(db: Session, player: Player, today: date, out: list) -> None:
    """Pools go public a week before their stage, so they can be practised."""
    for t in db.scalars(select(Tournament).where(
        Tournament.player_id == player.id, Tournament.user_registered.is_(True), Tournament.status != "finished"
    )):
        weeks = t.size.bit_length()  # log2(size) winners rounds + grand finals
        for week in range(1, weeks + 1):
            if due_date(t, week) - timedelta(days=7) > today:
                break
            if all(s.beatmap_id for s in pool_for(t, week)):
                continue
            try:
                _fill_pool_maps(db, t, week)
            except TournamentError:
                continue  # not enough indexed maps yet; try again later
            _news(db, player, today, "POOL_RELEASED", f"{t.name}: the week {week} pool is out.", 1,
                  {"tournament_id": t.id, "week": week}, out)


def _resolve_source(t: Tournament, source: str) -> int | None:
    kind, ref = source.split(":")
    if kind == "seed":
        return next(e.id for e in t.entries if e.seed == int(ref))
    m = next(m for m in t.matches if m.key == ref)
    return m.winner if kind == "winner" else m.loser


def _entry(t: Tournament, entry_id: int | None) -> TournamentEntry | None:
    return next((e for e in t.entries if e.id == entry_id), None)


def pool_for(t: Tournament, week: int) -> list[match.Slot]:
    key = str(week)
    if key not in t.pools:
        t.pools = {**t.pools, key: [vars(s) for s in match.pool_layout(week, t.base_stars)]}
    return [match.Slot(**s) for s in t.pools[key]]


def _form(db: Session, e: TournamentEntry) -> float:
    if e.kind == "npc" and e.npc_id:
        npc = db.get(Npc, e.npc_id)
        return npc.form if npc else 0.0
    return 0.0


# First-place prize per tier (USD, era-agnostic); places below get a share.
PRIZES = {"community6": 25, "community": 100, "open": 400, "major": 3000, "owc": 6000}
PLACE_SHARE = {"1st": 1.0, "2nd": 0.5, "3rd": 0.3, "4th": 0.2, "5th–6th": 0.1, "7th–8th": 0.07}


def _pay_prize(db: Session, player: Player, t: Tournament, entry: TournamentEntry, on: date, out: list) -> None:
    share = PLACE_SHARE.get(entry.placement or "", 0.0)
    if not entry.includes_user or share == 0:
        return
    amount = PRIZES.get(t.tier, 0) * share / max(1, t.team_size)
    if amount:
        player.money += amount
        _news(db, player, on, "PRIZE", f"Prize money from {t.name}: ${amount:,.0f} ({entry.placement}).", 1,
              {"tournament_id": t.id, "amount": amount}, out)


def _finish_match(db: Session, player: Player, t: Tournament, m: Match, winner_side: str, on: date,
                  out: list) -> None:
    m.winner = m.entry_a if winner_side == "a" else m.entry_b
    m.loser = m.entry_b if winner_side == "a" else m.entry_a
    m.played_on = on
    loser = _entry(t, m.loser)
    if loser:
        loser.placement = bracket.placement(m.key, t.size)
        _pay_prize(db, player, t, loser, on, out)
    if m.key == "GF":
        champion = _entry(t, m.winner)
        champion.placement = "1st"
        _pay_prize(db, player, t, champion, on, out)
        t.winner_entry_id = champion.id
        t.status = "finished"
        importance = 3 if t.tier in ("major", "owc") else 2
        if champion.includes_user:
            _news(db, player, on, "TOURNAMENT_WIN", f"You won {t.name}!", 3, {"tournament_id": t.id}, out)
            if t.tier in BADGE_TIERS:
                player.badges = [*(player.badges or []), {"name": t.name, "tournament_id": t.id,
                                                          "date": on.isoformat()}]
        else:
            _news(db, player, on, "TOURNAMENT_WINNER", f"{champion.name} wins {t.name}.", importance,
                  {"tournament_id": t.id, "npc_id": champion.npc_id}, out)
            if champion.npc_id:
                npc = db.get(Npc, champion.npc_id)
                if npc:
                    npc.titles += 1
        if loser and loser.includes_user:
            _news(db, player, on, "TOURNAMENT_RESULT", f"You finished 2nd at {t.name}.", 2,
                  {"tournament_id": t.id}, out)
    elif loser and loser.includes_user and loser.placement:
        _news(db, player, on, "TOURNAMENT_RESULT", f"Eliminated from {t.name}: {loser.placement}.", 2,
              {"tournament_id": t.id}, out)


def process(db: Session, player: Player, today: date) -> list[News]:
    """Start tournaments that are due and play every NPC match whose day has come."""
    out: list[News] = []
    reveal_pools(db, player, today, out)
    upcoming = list(db.scalars(select(Tournament).where(
        Tournament.player_id == player.id, Tournament.status != "finished", Tournament.start_date <= today
    ).order_by(Tournament.start_date)))
    for t in upcoming:
        if t.status == "upcoming":
            start(db, player, t, out)
        for m in t.matches:
            if due_date(t, m.week) > today:
                break
            if m.winner is not None:
                continue
            m.entry_a = m.entry_a or _resolve_source(t, m.source_a)
            m.entry_b = m.entry_b or _resolve_source(t, m.source_b)
            a, b = _entry(t, m.entry_a), _entry(t, m.entry_b)
            if a is None or b is None or a.includes_user or b.includes_user:
                continue  # waiting on an earlier match, or the user has to play this one
            rng = random.Random(f"{player.seed}:match:{t.id}:{m.key}")
            outcome = match.light_match(a.composites, b.composites, _form(db, a), _form(db, b),
                                        pool_for(t, m.week), m.first_to, rng)
            m.score_a, m.score_b = outcome.score_a, outcome.score_b
            _finish_match(db, player, t, m, outcome.winner, due_date(t, m.week), out)
    db.flush()
    return out


def forfeit(db: Session, player: Player, t: Tournament, m: Match, reason: str) -> list[News]:
    """The user doesn't show up: the opponent wins the match first_to-0 and the bracket moves on."""
    out: list[News] = []
    a = _entry(t, m.entry_a)
    user_side = "a" if a and a.includes_user else "b"
    winner = "b" if user_side == "a" else "a"
    m.score_a, m.score_b = (0, m.first_to) if user_side == "a" else (m.first_to, 0)
    m.maps = [{"forfeit": reason}]
    _finish_match(db, player, t, m, winner, player.in_game_date, out)
    _news(db, player, player.in_game_date, "FORFEIT", f"You forfeited your {m.stage} match at {t.name}: {reason}.", 2,
          {"tournament_id": t.id, "match_id": m.id}, out)
    out.extend(process(db, player, player.in_game_date))
    return out


def forfeit_if_unable(db: Session, player: Player) -> list[News]:
    """A forced hiatus on match day means a forfeit; otherwise the calendar would be stuck forever."""
    out: list[News] = []
    while player.injury == simulation.SEVERE_RSI:
        pending = pending_user_match(db, player)
        if pending is None or due_date(pending[0], pending[1].week) > player.in_game_date:
            break
        out += forfeit(db, player, *pending, reason="injured (forced hiatus)")
    return out


def pending_user_match(db: Session, player: Player) -> tuple[Tournament, Match] | None:
    """The user's next unplayed match whose opponent is known, if any."""
    best = None
    for t in db.scalars(select(Tournament).where(
        Tournament.player_id == player.id, Tournament.status == "ongoing", Tournament.user_registered.is_(True)
    )):
        for m in t.matches:
            if m.winner is not None or m.entry_a is None or m.entry_b is None:
                continue
            a, b = _entry(t, m.entry_a), _entry(t, m.entry_b)
            if (a and a.includes_user) or (b and b.includes_user):
                if best is None or due_date(t, m.week) < due_date(best[0], best[1].week):
                    best = (t, m)
                break
    return best


def next_deadline(db: Session, player: Player) -> date | None:
    """When the calendar has to stop: the next user match, or the start of a registered tournament."""
    dates = []
    pending = pending_user_match(db, player)
    if pending:
        dates.append(due_date(pending[0], pending[1].week))
    starts = db.scalars(select(Tournament.start_date).where(
        Tournament.player_id == player.id, Tournament.status == "upcoming", Tournament.user_registered.is_(True)
    ))
    dates.extend(starts)
    return min(dates, default=None)


def register(db: Session, player: Player, t: Tournament) -> None:
    today = player.in_game_date
    if t.tier == "owc":
        raise TournamentError(422, "World Cup teams are picked automatically from each country's top players")
    if t.status != "upcoming" or today >= t.start_date:
        raise TournamentError(409, "registration has closed")
    if today < t.registration_opens:
        raise TournamentError(409, f"registration opens on {t.registration_opens}")
    if not eligible(player, t):
        bws = seeding_rank(player, t)
        label = f"BWS rank #{round(bws):,}" if round(bws) != user_rank(player) else f"rank #{user_rank(player):,}"
        raise TournamentError(409, f"{label} is outside {t.rank_min:,}–{t.rank_max:,}")
    t.user_registered = True


# --- the user's matches ----------------------------------------------------------------------


def _loadable(db: Session, beatmap: Beatmap) -> bool:
    try:
        osu_files.get_osu_file(beatmap.id)
        return True
    except osu_files.BeatmapNotFound:
        db.delete(beatmap)
        db.flush()
        return False


def _validate_pool(db: Session, t: Tournament, week: int) -> list[match.Slot]:
    """Maps can vanish after a pool is published; replace those before playing."""
    slots = pool_for(t, week)
    changed = False
    for s in slots:
        if s.beatmap_id:
            try:
                osu_files.get_osu_file(s.beatmap_id)
            except osu_files.BeatmapNotFound:
                bm = db.get(Beatmap, s.beatmap_id)
                if bm is not None:
                    db.delete(bm)
                s.beatmap_id, s.title, changed = None, "", True
    if changed:
        t.pools = {**t.pools, str(week): [vars(s) for s in slots]}
        db.flush()
    return _fill_pool_maps(db, t, week)


def _fill_pool_maps(db: Session, t: Tournament, week: int) -> list[match.Slot]:
    slots = pool_for(t, week)
    if all(s.beatmap_id for s in slots):
        return slots
    fill_slots(db, slots, t.start_date, random.Random(f"pool:{t.id}:{week}"))
    t.pools = {**t.pools, str(week): [vars(s) for s in slots]}
    return slots


def fill_slots(db: Session, slots: list[match.Slot], ranked_before: date, rng: random.Random) -> list[match.Slot]:
    """Pick indexed, downloadable maps for every empty slot (mods, stars and style per slot)."""
    used: set[int] = set()
    for s in slots:
        if s.beatmap_id:
            used.add(s.beatmap_id)
            continue
        family = world.slot_family(s.slot)[:2]
        nm_target = s.stars / {"DT": 1.45, "HR": 1.08}.get(family, 1.0)
        lo_len, hi_len = (180, 420) if family == "TB" else (90, 300)
        for window in (0.15, 0.3, 0.6, 1.2):
            q = (select(Beatmap, BeatmapSet).join(BeatmapSet)
                 .where(BeatmapSet.ranked_date <= ranked_before, Beatmap.stars.between(nm_target - window, nm_target + window),
                        Beatmap.hit_length.between(lo_len, hi_len)))
            if s.slot == "NM3":
                q = q.where(Beatmap.bpm >= 175)
            elif s.slot == "NM5":
                q = q.where(Beatmap.ar <= 8.5)
            elif family == "HR":
                q = q.where(Beatmap.cs <= 4.5)
            elif family == "DT":
                q = q.where(Beatmap.bpm <= 210, Beatmap.ar <= 9.4)
            rows = [r for r in db.execute(q.order_by(BeatmapSet.play_count.desc()).limit(60)) if r[1].id not in used]
            rng.shuffle(rows)
            for b, bset in rows[:30]:
                if not _loadable(db, b):
                    continue  # gone from osu.ppy.sh: purged from the index, try another
                s.beatmap_id = b.id
                s.title = f"{bset.artist} - {bset.title} [{b.version}]"
                used.add(bset.id)
                break
            if s.beatmap_id:
                break
        if not s.beatmap_id:
            raise TournamentError(409, "not enough indexed beatmaps to build the map pool yet; try again shortly")
    return slots


@dataclass
class _Competitor:
    name: str
    kind: str
    skills: dict[str, float]
    form: float
    day: play.DayModifiers
    seed: int
    npc_id: int | None


def _competitors(db: Session, player: Player, e: TournamentEntry) -> list[_Competitor]:
    members = e.members or [{"name": e.name, "kind": e.kind, "npc_id": e.npc_id, "composites": e.composites,
                             "seed": e.composites.get("_seed", e.seed)}]
    out = []
    for m in members:
        if m["kind"] == "user":
            day = sessions.day_modifiers(player)
            day.morale = player.morale
            out.append(_Competitor(player.name, "user", condition.play_skills(db, player), player.form, day,
                                   player.seed, None))
        else:
            comps = {g: v for g, v in m["composites"].items() if not g.startswith("_")}
            npc = db.get(Npc, m["npc_id"]) if m.get("npc_id") else None
            form = npc.form if npc else 0.0
            out.append(_Competitor(m["name"], m["kind"], world.substats(comps, m.get("seed", 0)), form,
                                   play.DayModifiers(form=form), m.get("seed", 0), m.get("npc_id")))
    return out


def _side_comps(comps: list[_Competitor]) -> dict[str, float]:
    per = [{g.key: A.composite(c.skills, g) for g in A.GROUPS} for c in comps]
    return {g: sum(p[g] for p in per) / len(per) for g in world.GROUP_KEYS}


# Peak viewers of a tournament stream by tier (scaled by era community size and stage).
MATCH_VIEWERS = {"community6": 0, "community": 30, "open": 300, "major": 4000, "owc": 20000}


def map_simulator(db: Session, player: Player, side_a: list["_Competitor"], side_b: list["_Competitor"],
                  seed_key: str, no_fail: bool = True):
    """(advantage, play_map) callbacks for match.run_match: every map simulated note by note for
    everyone on both sides, ScoreV2, pressure on decisive maps, the user's map knowledge."""
    comps_a, comps_b = _side_comps(side_a), _side_comps(side_b)

    def advantage(s: match.Slot) -> float:
        return world.slot_strength(comps_a, s.slot) - world.slot_strength(comps_b, s.slot)

    def play_map(s: match.Slot, decisive: bool) -> tuple[int, int, dict]:
        mods = pp.normalize_mods(s.mods + ("NF" if no_fail else ""))
        prof = sessions.map_profile(s.beatmap_id, mods)
        detail = {"beatmap_id": s.beatmap_id, "title": s.title, "mods": s.mods or "NM", "stars": round(prof.stars, 2),
                  "players": []}
        totals = []
        for side_name, side in (("a", side_a), ("b", side_b)):
            total = 0
            for i, c in enumerate(side):
                day = play.DayModifiers(**vars(c.day))
                day.pressure, day.clutch = play.match_pressure(c.skills["nerve_resistance"], c.skills["clutch"], decisive)
                if c.kind == "user":
                    day.familiarity = familiarity.level(db, player, s.beatmap_id)
                rng = random.Random(f"{player.seed}:{seed_key}:{s.slot}:{side_name}:{i}")
                attempt = play.simulate(prof, c.skills, mods, day, rng)
                if c.kind == "user":
                    familiarity.record_attempt(db, player, s.beatmap_id, 1.0 if attempt.passed else attempt.fail_progress or 0)
                score = play.score_v2(attempt, prof, s.mods)
                total += score
                detail["players"].append({
                    "side": side_name, "name": c.name, "kind": c.kind, "score": score,
                    "accuracy": round(attempt.accuracy, 2), "misses": attempt.misses, "combo": attempt.max_combo,
                    "max_combo": prof.max_combo, "choked": attempt.choked, "key_moments": attempt.key_moments,
                })
            totals.append(total)
        return totals[0], totals[1], detail

    return advantage, play_map


def play_user_match(db: Session, player: Player, t: Tournament, m: Match,
                    strategy: dict[str, list[str]] | None = None) -> tuple[match.MatchOutcome, list[News]]:
    pending = pending_user_match(db, player)
    if pending is None or pending[1].id != m.id:
        raise TournamentError(409, "this isn't your next match")
    if player.injury == simulation.SEVERE_RSI:
        raise TournamentError(409, "you're on a forced hiatus: this match is forfeited")
    if due_date(t, m.week) > player.in_game_date:
        raise TournamentError(409, f"this match is scheduled for {due_date(t, m.week)}")

    pool = _validate_pool(db, t, m.week)
    a, b = _entry(t, m.entry_a), _entry(t, m.entry_b)
    side_a, side_b = _competitors(db, player, a), _competitors(db, player, b)
    advantage, play_map = map_simulator(db, player, side_a, side_b, seed_key=f"{m.id}")
    rng = random.Random(f"{player.seed}:usermatch:{m.id}")
    user_side_key = "a" if a.includes_user else "b"
    outcome = match.run_match(pool, m.first_to, advantage, play_map, rng, bans_per_side=2 if m.week >= 4 else 1,
                              prefs={user_side_key: strategy} if strategy else None)
    m.score_a, m.score_b = outcome.score_a, outcome.score_b
    m.maps = [{"slot": r.slot, "picked_by": r.picked_by, "score_a": r.score_a, "score_b": r.score_b, **r.detail}
              for r in outcome.maps] + [{"bans": outcome.bans}]
    out: list = []
    user_side = "a" if a.includes_user else "b"
    won = outcome.winner == user_side
    _finish_match(db, player, t, m, outcome.winner, player.in_game_date, out)

    # Consequences: morale, a tiring day, and rivalries with the NPCs involved.
    player.morale = A.clamp(player.morale + (8 if won else -6), 0, 100)
    viewers = MATCH_VIEWERS.get(t.tier, 0) * media.community_size(player.in_game_date) * (1 + 0.25 * (m.week - 1))
    if viewers >= 10:
        gained = round(viewers * 0.01 * (1.5 if won else 1.0))
        player.followers += gained
        _news(db, player, player.in_game_date, "MATCH_VIEWERS",
              f"~{round(viewers):,} watched your {m.stage} match: +{gained} followers.", 1,
              {"tournament_id": t.id, "viewers": round(viewers)}, out)
    player.fatigue = A.clamp(player.fatigue + 2 + 0.6 * len(outcome.maps), 0, 100)
    opponent = b if user_side == "a" else a
    opp_side = side_b if user_side == "a" else side_a
    rivals.on_match(db, player, [c.npc_id for c in opp_side if c.npc_id], won)
    for c in opp_side:
        npc = db.get(Npc, c.npc_id) if c.npc_id else None
        if npc is None or not won:
            continue
        if c.skills["tilt_resilience"] >= 60:
            npc.motivation = min(100.0, npc.motivation + 5)
            npc.curve_shift_weeks += 26  # fired up: the decline comes later
        else:
            npc.motivation = max(0.0, npc.motivation - 10)
    user_entry = a if user_side == "a" else b
    upset = won and opponent.seed + 4 <= user_entry.seed
    media.tournament_match(db, player, t, m, user_entry, opponent, won, upset)
    if won and m.key == "GF":
        media.tournament_victory(db, player, t, user_entry)
    if upset:
        moments = [p["key_moments"] for p in m.maps[-2].get("players", []) if p.get("key_moments")] if len(m.maps) > 1 else []
        _news(db, player, player.in_game_date, "TOURNAMENT_UPSET",
              f"Upset at {t.name}: {player.name} (seed {user_entry.seed}) beats {opponent.name} "
              f"(seed {opponent.seed}) {max(m.score_a, m.score_b)}-{min(m.score_a, m.score_b)} in {m.stage}.", 3,
              {"tournament_id": t.id, "match_id": m.id, "key_moments": moments[:2]}, out)
    out.extend(process(db, player, player.in_game_date))
    return outcome, out
