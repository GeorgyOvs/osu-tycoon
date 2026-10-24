# osu! Tycoon

Career simulation engine for osu! (see `osu_tycoon_architecture_claude_code_plan.md`).

- `backend/` — FastAPI + SQLite + rosu-pp-py (stable PP)
- `frontend/` — React + Vite + Tailwind

## Run

```bash
# backend (http://127.0.0.1:8642, docs at /docs) - not 8000, that's SillyTavern's default
cd backend
python3 -m venv .venv                 # Windows: python -m venv .venv
# Windows:      .venv/Scripts/pip ...   |   macOS/Linux: .venv/bin/pip ...
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8642

# frontend (http://localhost:5173, proxies /api to the backend)
cd frontend
npm install
npm run dev
```

Tests: `cd backend && .venv/bin/python -m pytest` (Windows: `.venv/Scripts/python`)

Data (SQLite DB and cached `.osu` files) lives in `backend/data/`; override with `TYCOON_DATA_DIR`.

## API

| Method | Path | Description |
|---|---|---|
| POST | `/api/pp/calculate` | PP for `{beatmap_id, mods, accuracy, misses, combo, n100, n50}` |
| GET/POST | `/api/players` | List / create careers (`{name, country, start_date}`) |
| GET/DELETE | `/api/players/{id}` | Profile with top plays and recent scores |
| POST | `/api/players/{id}/scores` | Submit `{beatmap_id, mods, accuracy, misses, combo}`; recomputes weighted PP, accuracy, rank |
| GET | `/api/players/{id}/drills` | Training drills and whether the current era has them |
| POST | `/api/players/{id}/train` | `{drill, hours_per_day, days}`: simulate training days |
| POST | `/api/players/{id}/rest` | `{days, physio}`: rest days, recovery, physiotherapy |
| GET | `/api/beatmaps?before=YYYY-MM-DD` | Ranked/approved sets ranked by that date. Filters: `q`, `min_stars`, `max_stars`, `sort`, `limit`, `offset` |
| GET | `/api/beatmaps/index` | Progress of the background beatmap index sync |
| POST | `/api/players/{id}/sessions` | `{plays: [{beatmap_id, mods, attempts}]}`: simulate a day of playing; passes become scores |
| GET | `/api/players/{id}/assess/{beatmap_id}?mods=` | Pass/FC chance, typical score and the weakest skill for a map today |
| GET | `/api/players/{id}/news` | World news feed (`min_importance` 1-3) |
| GET | `/api/players/{id}/leaderboard` | Global or `?country=` rankings: legends, procedural players and you |
| GET | `/api/players/{id}/npcs/{npc_id}` | An NPC's profile |
| GET | `/api/players/{id}/tournaments` | Calendar window (recent, ongoing, upcoming) and your pending match |
| GET | `/api/players/{id}/tournaments/{tid}` | Bracket, entries, pools, map-by-map results |
| POST | `/api/players/{id}/tournaments/{tid}/register` | Sign up (rank band and registration window apply; OWC teams are automatic) |
| POST | `/api/players/{id}/tournaments/{tid}/matches/{mid}/play` | Play your match: every map simulated for both sides |

## Beatmap index

Ranked and approved osu!standard sets are crawled from the [osu.direct](https://osu.direct) mirror oldest-first
(`sort=ranked_date:asc`) into SQLite, but only up to the furthest in-game date of any career, so a 2010 career
needs a few thousand sets rather than all ~33k. The crawl runs in a background thread, resumes where it stopped,
and extends automatically as careers advance. Score submission rejects maps that aren't ranked/approved or that
get ranked after the player's in-game date. Star ratings in the browser come from the mirror (today's algorithm);
PP is computed locally with rosu-pp (stable).

## Engine (`backend/app/engine/`)

- `attributes.py`: 21 sub-stats in 6 composites (Aim, Tapping, Reading, Technical, Mentality, Physical), 1-99, up to 115 for legends.
- `training.py`: eras (2007-11 / 2012-15 / 2016-20 / 2021+) and the drills each one allows.
- `simulation.py`: the day tick. Training gains scale with hidden talent and per-skill affinity, autocorrelated daily form, plateaus and breakthroughs. Also fatigue, rust (more than 14 idle days: -1..-5) and the injury state machine (healthy -> minor strain -> severe RSI hiatus, with permanent ceiling loss unless treated with physio). Randomness is seeded per career and per day, so careers are reproducible.

- `map_analysis.py`: per-object demands from rosu-pp (aim/speed difficulty, 400ms strains, hit windows, AR/CS/HP after mods) plus `.osu` parsing (stream BPM and length, jump velocity and angles, SV changes, odd rhythm snaps).
- `play.py`: object-by-object attempt simulation. The weakest relevant skill sets demand/capability, which drives a steep miss curve with panic streaks. Timing error vs. OD windows has a heavy tail, the HP bar fails the run (unless NF), nerves choke long combos, and long maps drain endurance. Form, fatigue, warm-up, session length and tilt apply. Key moments explain fails ("Failed at 1:23 (64%) during a 245 BPM stream").
- Sessions (`services/sessions.py`): several maps with retries take one in-game day. The best pass per map is recorded, and what the maps demanded becomes that day's training, most effective near the edge of ability.

## Living world (`engine/world*.py`, `services/world_service.py`, `services/tournaments.py`)

- Each career has its own world: 24 historical legends (one person = one legend; other names go in `aliases`, e.g. Cookiezi aka chocomint, nathan on osu) following approximate career curves (prime, hiatus, decline, retirement; edit `engine/world_data.py`) and 400 procedural players with generated careers.
- NPCs tick weekly on composites only: random walk around the curve, form, motivation, injuries, hiatuses and retirements. pp follows skill with a lag. A year of world takes about 1.5 seconds.
- Era-aware rankings: the pp -> rank curve scales with each year's top pp and player base.
- Tournaments: 6/5-digit cups, Opens (#1k-10k), Majors (top 500) and the OWC (country teams of 3), with 32-player double-elimination brackets, weekly rounds, stage map pools (NM/HD/HR/DT/TB) with stars rising per stage, and bans/picks/tiebreakers. NPC matches are resolved from composites. Your matches use real maps from the index, simulated note by note with NoFail and ScoreV2, plus match-point pressure (nerves, clutch) and morale.
- Butterfly effect: beating NPCs fires them up (delayed decline) or knocks their motivation, depending on their tilt resilience. Notable events land in the news feed.
- The calendar stops on your match days; nothing else happens until the match is played.

The DB schema has a version check; if the engine reports an outdated schema, delete `backend/data/tycoon.db`.

## Social layer and SillyTavern (`services/media.py`, `routers/social.py`, `sillytavern-extension/`)

Notable moments (new top plays, your tournament matches and wins, big world news, rank milestones, injuries, community drama) each produce three things:

1. **A forum thread** on the osu! forums (before 2013) or r/osugame. Scoreposts use the canonical title
   `Player | Artist - Title [Diff] +MODS (acc%) combo/maxx NxMiss | pp (pp if FC) | Their new top play!`.
   Upvotes scale with significance and the era's community size. A few procedural comments come from world NPCs.
2. **IRC lines** in `#osu` or your country channel (`#russian`, `#korean`, ...).
3. **An outbox event** for SillyTavern in the plan's `{event_type, data}` shape (`npc_reactions_needed`, `reddit_thread_spec`, `key_moments`, ...), bundled with ready-made prompts and JSON schemas.

SillyTavern has no inbound webhook, so the bridge is pull-based. Install the extension:

1. Copy `sillytavern-extension/osu-tycoon` to `SillyTavern/data/<your-user>/extensions/osu-tycoon` (usually `data/default-user/extensions/`), or to `public/scripts/extensions/third-party/osu-tycoon`, then reload SillyTavern.
2. Extensions panel → **osu! Tycoon Bridge**: set the engine URL (`http://127.0.0.1:8642`), choose a career, tick **Enabled**.
3. It polls for events, writes forum comments and IRC chatter with your current model, and posts them back; the Tycoon UI picks them up live (✦ marks LLM-written comments). Optionally it narrates events into the open chat via `/sys`.
4. Put `{{tycoon}}` in an Author's Note or World Info entry to give the model the career's state (rank, skills, condition, top plays, tournaments, headlines).

Structured outputs are used on Chat Completion APIs, with a plain-prompt fallback that pulls the JSON out of the reply. If SillyTavern runs on a non-default origin, add it to `TYCOON_CORS_ORIGINS`.

Bridge API: `GET /api/st/careers`, `GET /api/st/careers/{id}/events`, `POST .../events/{eid}/ack`, `POST .../threads/{tid}/comments`, `POST .../irc`, `GET .../context`.

## Play presets and map leaderboards

- **Play sessions from presets** (`services/autoplay.py`): warm-up, farm, push, streams, jumps, low AR, HD/HR/DT, newly ranked. The engine picks indexed maps around your current level for the hours you choose. `POST /api/players/{id}/sessions/auto {preset, hours}`, list via `GET .../presets`.
- **Drills that are really ranked play** (pack grind, HD/HR practice, jump farm, multiplayer) set real scores: each training day plays a few maps from a weekly rotation. Unranked practice (stream maps, tech maps, osu!trainer, ...) gives no pp.
- **Per-map leaderboards** (`services/leaderboards.py`): simulated month by month from the ranked date using NPC careers (retired players keep their scores), map popularity and the era's mod meta, scored with ScoreV1. Stored as snapshots, so they only ever move forward. Sniping #1 creates `SNIPE_FIRST_PLACE` (a thread only when it matters: legends, top players, popular maps), and NPCs can take your #1 back. Real historical scores can be added to `backend/app/data/anchor_scores.json` (a source is required; see the README there). `GET /api/players/{id}/beatmaps/{bid}/leaderboard`.
- **Scoreposts are era-relative**: only plays worth roughly 45% of the era's best play get a thread.

## Roadmap

- [x] Phase 1: profile, rosu-pp with mods, weighted PP, attribute hierarchy, calendar, training, rust/fatigue/injury state machines
- [x] Phase 2: beatmap mirror with `ranked_date <= in_game_date`, SQLite index, browser, audio mini-player
- [x] Phase 2.5: skill-based map play simulation (fails, NF, per-section skill gaps, sessions)
- [x] Phase 3: living world (legends with career curves, procedural players, injuries/hiatuses/retirements), era-aware rankings, tournaments with double-elimination brackets and stage pools
- [x] Phase 4: social UI (forum feed, IRC overlay) and the SillyTavern bridge
- [x] Per-map historical leaderboards (anchor scores + NPC fill, #1 sniping), play presets, scores from map-playing drills
- [ ] Phase 4: forum feed and IRC overlay, SillyTavern bridge

## Career depth

- **Map familiarity**: replaying a map builds muscle memory (up to +5% skill, fewer lapses); it fades over weeks.
- **Gear and money** (`engine/gear.py`, `services/condition.py`): mouse/tablet, keyboard, monitor, chair by release year (the 144Hz monitor unlocks high AR reading, a 60Hz one caps it; Wooting from 2022). Money comes from allowance/jobs, prizes, sponsors and streams; physio costs money. Prices and some years are approximate.
- **Life** (`services/life.py`): age, school/university/work/pro, free hours per day (holidays and exams matter), sleep debt, learning speed by age, reflexes fading after 25.
- **Playstyle**: mouse vs tablet and alternate vs singletap change sub-stats and ceilings; switching starts a slow adaptation.
- **pp history** (`engine/pp_history.py`): ranked score until Jul 2012, ppv1 with decay, ppv2 (Jan 2014), the 2021 updates and the Oct 2024 rework (combo scaling removed). Your scores are repriced when the system changes, with a megathread. Per-era multipliers are approximations of the direction of each change; sources are listed in the file.
- **Rivals**: 2-3 NPCs near your rank with heat, DMs, snipe hunting and shared tournaments.
- **Streaming** (from June 2011): live sessions add pressure, followers, money and highlight events for SillyTavern.
- **Watching replays**: a low-strain, motivating drill that teaches more the further you are from the top.

## Tournaments in depth

- **Pools are released a week before each stage** and can be practised (`POST /api/players/{id}/sessions/pool`); map familiarity carries straight into the match.
- **Qualifiers** seed the bracket when you take part (everyone plays the first-stage pool; practice and form count).
- **Your own bans and picks**: `POST .../matches/{mid}/play` accepts `{bans: [...], picks: [...]}` (slot names, priority order); the AI fills the rest. In the UI: click to ban, shift-click to queue picks.
- **Badges and BWS**: winning an Open, Major or the OWC gives a profile badge. From 2019 rank-restricted tournaments use badge-weighted seeding, `rank^(0.9937^(badges^2))`, so badged players can't farm lower tiers.
- **Viewers**: streamed tournament matches bring followers by tier and stage.

## Real players

`python -m app.tools.import_real_players --count 1000` imports the current top players from the osu! API v2 (set `OSU_CLIENT_ID` / `OSU_CLIENT_SECRET` from an OAuth application in your osu! account settings). Careers are built from real anchors (join date, highest rank with date, current rank); players don't appear before they joined osu!, and anyone who is already a hand-written legend (by name or previous name) is skipped. osu! only records highest ranks from recent years, so earlier peaks are approximate. The data goes to `backend/app/data/real_players.json`, shared by all worlds created afterwards. With 1000 real players a year of world simulation takes ~3 s.

## Tests

- Backend: `cd backend && .venv/Scripts/python -m pytest` (add `-m "not slow"` to skip the two-year career run).
- Frontend: `cd frontend && npm test` (Vitest + Testing Library, API mocked).
- Balance report on the real index: `python -m app.tools.balance_report --months 30` (creates and deletes its own careers).

## Week planner

Training tab → **Plan the week**: one row per day (train / play / rest, hours, stream, physio), saved in the browser. **Live this week** runs it in one go (`POST /api/players/{id}/week`): refused days (free time, missing maps, no money for physio) turn into rest, an injury hiatus forces rest, and the week stops on a tournament match day. The summary shows skill changes, scores, money and followers.

## Playing from SillyTavern (extension v0.2)

- `/tycoon status` — the career summary
- `/tycoon train <drill> [hours/day] [days]` — e.g. `/tycoon train jump_farm 4 3`
- `/tycoon play <preset> [hours] [stream]` — e.g. `/tycoon play push 3 stream`
- `/tycoon rest [days] [physio]`
- `/tycoon week` — live a standard week
- `/tycoon dm <player> <message>` — write to any player in your world

Results are posted into the chat. **Private messages** (from the IRC window, an NPC's card in the World tab, or `/tycoon dm`) are answered by your SillyTavern model in character: the engine sends who the NPC is, their rank and attitude, your rivalry history and the last messages.

Character gender is role-play only (pronouns for the community and the LLM); it never affects gameplay. Careers can start from age 7; under 12 the parents decide: 3h of free time on school days, 6h at weekends.

## Character builds and ranking size

Score-record stories now require a saved play on an era-available ranked/approved beatmap. Weekly fictional NPC attempts use cached `.osu` files, actual mods/accuracy/combo/misses, and the same era-adjusted pp calculation as user plays. Attempts exceeding 120% of the era's calibrated best single play are rejected, rather than assigned an invented pp value. Single-play record announcements include the map and result; their community thread and World news open that map's leaderboard. Real players never receive fictional record announcements, and pp milestones are suppressed before pp was introduced. NPC map leaderboard pp is recalculated for the current era, including ppv1 decay. News preserves the pp earned at the time of the play. Schema v14 preserves announced NPC results; startup marks legacy unbacked 1000pp stories as retracted without deleting the discussion.

New careers use the original seeded random talent generation by default. The creation form also offers Farmer, Streamer, Technician, Tournament Player and Prodigy presets, or a custom build. There are 4 balance points: talents cost points and weaknesses refund them. The unlimited-points checkbox bypasses the budget; contradictory perks remain mutually exclusive. Selected perks modify the generated starting attributes, learning affinities, learning speed or skill ceilings and remain visible in the profile's traits. Existing characters keep their attributes.

`GET /api/players/creation-options` supplies the shared perk catalog and costs. `POST /api/players` accepts `preset`, `perks` and `unbalanced`; the server validates costs and conflicts. Schema v13 migrates existing saves automatically on backend restart.

The World ranking now supports 25, 50, 100, 200, 500 or 1000 displayed rows (100 by default). Worlds contain 1600 procedural careers, or 1200 alongside imported real players, spread across eras. Existing worlds receive missing NPCs once when loaded; only players active in the chosen era appear in the ranking, so a large display limit may return fewer rows.
