# osu! Tycoon Engine & SillyTavern Integration Spec

## 1. Project Overview & Vision

A standalone, lightweight simulation game ("osu! Tycoon / Road to Legend") modeling an esports career in *osu!* from any starting year (e.g., 2008–2024).
The system acts as a deterministic state engine (progression, gear, stats, tournament brackets, beatmap databases, player lifecycles, and scoring logic) that communicates bidirectionally with **SillyTavern** via Webhooks/REST API.

The engine handles all math, attribute simulations, calendar progression, dynamic decay, and tournament brackets. The LLM acts as the **Community & Social Simulator**: generating authentic forum threads (r/osugame, osu! forums), in-game IRC chat channels (`#osu`, `#russian`, private DMs), Twitch chat reactions, and distinct personalities of legendary players.

---

## 2. Granular Attribute System (FIFA-Style Hierarchy)

Attributes range from `1` to `99` (with uncapped potential up to `115` for transcendent historical peaks). Each composite attribute is calculated as a weighted average of granular sub-stats:

```
[Composite: AIM] ────────┬── Snap Aim (Instant jumps, sharp angles, triangle patterns)
                         ├── Flow Aim (Smooth cross-screen sliders, spaced stream tracking)
                         ├── Precision & Small CS (Hitcircle size 5-7 competence)
                         └── High-Velocity Distance (Cross-screen fullscreen DT jumps)

[Composite: TAPPING] ────┬── Low/Mid BPM Control (140-190 BPM: accuracy, rhythm stability)
                         ├── High BPM Burst (240-300+ BPM: short 5-9 note stamina)
                         ├── Deathstream Stamina (200-240+ BPM continuous 32+ note streams)
                         └── Finger Independence (Complex triples, quintuples, alternating)

[Composite: READING] ────┬── Low AR / Density Reading (AR 6-8: overlapping note clusters)
                         ├── High AR Reaction (AR 10.33 - 11.0: sub-300ms reaction windows)
                         ├── Low-BPM Finger Control Rhythms (Swing, polymeter, complex offsets)
                         └── Hidden Mod Competence (Fading circles, spatial awareness)

[Composite: TECHNICAL] ──┬── Complex Slider Velocity (Fast SV changes, buzz sliders)
                         ├── Awkward Angle Correction (Non-linear geometric snapping)
                         └── HardRock / Strict OD Offset (OD 10+ timing window tightness)

[Composite: MENTALITY] ──┬── Nerve Resistance (Anti-shake on 2000x+ combo / last 100 notes)
                         ├── Match Clutchness (Tiebreaker performance under tournament pressure)
                         └── Tilt & Reset Resilience (Ability to recover after consecutive chokes)

[Composite: PHYSICAL] ───┬── Hand Stamina & Energy (Daily play tolerance before fatigue hits)
                         ├── RSI Risk Index (Injury threshold; accumulates from unergonomic gear)
                         └── Visual Endurance (Eye strain resistance on long tournament days)
```

---

## 3. Dynamic Player Lifecycles, Form & Era Scaling

### 3.1 Historical Prime Curves & Archetypes

Players are not static stat blocks. Their attributes are dynamically evaluated relative to the `current_in_game_date`:

* **mrekk:**
  * *2015–2017:* Untriggered / 9-year-old amateur (`Overall: 25`). Plays nomod on tablet with low star ratings.
  * *2018–2019:* Rising prodigy (`Overall: 68-82`). Rapidly climbing ranks via DT jumps.
  * *2021–2024:* Uncontested Prime (`Overall: 99+`). Maxed High BPM Burst, Flow Aim, High AR Reaction (AR11).
* **Cookiezi / Shigetora:**
  * *2010–2011:* Raw phenom (`Overall: 88`). Unmatched HD reading and stream snapping.
  * *2012–2013:* Peak Dominance (`Overall: 99`). FDFD, master of all non-DT mods.
  * *Late 2013–Mid 2015:* Self-Ban / Inactive (`Status: Restricted / Offline`).
  * *2016–2017:* The Return (`Overall: 98`). Legendary HDHR / HD tech run.
  * *2018+:* Health Decay (`Overall: 89-93`). Eye fatigue, severe hand pain/ergonomic struggles; refuses to farm standard maps, shifts strictly to technical play.
* **rrtyui:**
  * *2012–2014:* Prime (`Overall: 96`). Incomparable reading, high spinner speed, godly match clutchness ("plz enjoy game").
  * *2015+:* Retirement (`Status: Inactive / Mapping`). Low tournament participation, skills locked to legacy meta.

### 3.2 Decay, Inactivity & Hand Health Mechanics

1. **Rust / Skill Decay:**
   * If a player does not train an attribute group for $>14$ in-game days, a temporary `-1` to `-5` debuff is applied.
   * Rust clears twice as fast as building new raw skill once active play resumes.
2. **RSI & Injury State Machine:**
   * Grinding high-BPM streams (>240 BPM) or playing $>8$ hours daily without rest days accumulates `Fatigue`.
   * High `Fatigue` + cheap unergonomic gear = **Minor Wrist Strain** (-15% Stamina, -10% Speed).
   * Ignoring Strain leads to **Severe Tendonitis / RSI** (Forced 1–3 month hiatus; permanent loss of maximum Stamina ceiling unless treated with ergonomic gear/physiotherapy).
3. **The Butterfly Effect (Player Interaction):**
   * Sniping a pro's #1 score early or beating them in a tournament sends an event to the state machine.
   * Pros with high `Tilt Resistance` gain a `Rivalry Boost` (+5 Motivation, delays historical retirement).
   * Pros with low motivation may trigger early hiatuses.

---

## 4. Era-Appropriate Training Systems

The way players train reflects the reality of mapping history:

* **2007–2011 (Old-School Era):**
  * *No Training Maps / Practice Tools.* Practice consists solely of grinding full ranked beatmap packs (DJ POP, SiFa, James).
  * Focuses heavily on *Low AR Reading*, *Awkward Angles*, and *Rhythm Memory*.
  * No custom speed/BPM scaling available; players cannot isolate stream patterns.
* **2012–2015 (The Competitive Revolution):**
  * Introduction of dedicated long-stream maps (Long Stream Practice Maps), unranked tech maps, and high-AR edits.
  * Players begin using specialized training maps to drill specific BPM thresholds (180 $\rightarrow$ 200 $\rightarrow$ 220).
* **2016–2020 (The Farm & Toolset Era):**
  * Widespread adoption of osu!trainer, BPM changers, and AR modifiers.
  * Training becomes hyper-efficient: players spam 1-minute jump maps (Sotarks, Monstrata) to pump raw aim and reaction speed.
* **2021+ (Modern Science):**
  * Finger-control maps, Rapid Trigger optimization drills, and customized health/stamina warmup routines.

---

## 5. Tournament Engine & Bracket Generation

### 5.1 Tournament Tiers & Eligibility

Tournaments are split into distinct tiers based on rank brackets:
* **Amateur / Community Cups:** 5-Digit & 6-Digit tourneys (Rank #10,000 to #100,000+). Pro players **never** enter these.
* **Regional / National Opens:** Rank #1,000 to #10,000. Semi-pro level.
* **Major Invitational Tournaments:** Corsace Open, The Roundtable, Suiji Cup (Top 500 only).
* **osu! World Cup (OWC):** National qualification held annually in late autumn. Only top-ranked players of each country qualify for tryouts.

### 5.2 Dynamic Map Pooling & Stage Progression

A tournament consists of progressive rounds: `Group Stage` $\rightarrow$ `Round of 16` $\rightarrow$ `Quarterfinals` $\rightarrow$ `Semifinals` $\rightarrow$ `Finals` $\rightarrow$ `Grand Finals`.

Each stage generates a structured map pool containing specific slots:
* **NM (NoMod 1–6):** NM1 (Pure Aim), NM2 (High-BPM Jump/Burst), NM3 (Speed/Stamina Stream), NM4 (Finger Control/Tech), NM5 (Low-AR / High-Density Reading).
* **HD (Hidden 1–3):** Precision aim and complex slider reading with Hidden.
* **HR (HardRock 1–3):** Precision CS5+, OD10 timing, high AR9.8–10.
* **DT (DoubleTime 1–4):** High-velocity speed, burst stamina, AR10.3+.
* **TB (Tiebreaker):** High-difficulty marathon map combining aim, stamina, and consistency (played when match reaches match point: e.g., 6–6).

**Stage Difficulty Scaling:**
$$\text{Star Rating}(\text{Stage}) = \text{Base Tournament Stars} + \Delta_{\text{Stage}}$$
*(e.g., OWC: Group Stage ~6.6★ $\rightarrow$ Grand Finals ~7.8★–8.2★).*

### 5.3 Match Simulation Logic

Matches are simulated point-by-point:
1. Captains take turns banning 1–2 maps from the pool.
2. Teams/players take turns picking maps.
3. For each selected map, the engine evaluates the required skills against each player's attributes:
   $$\text{Player Performance} = \sum (\text{Required Attribute}_i \times \text{Skill}_i) + \text{Nerve Check} + \text{RNG Roll } [-3\% \text{ to } +3\%]$$
4. If a player has low `Nerve Resistance` during match point or on high-star maps, their choke probability multiplies by $3\times$.
5. The first player to reach the required point threshold wins the match and advances in the Double Elimination bracket.

---

## 6. The Virtual Social Simulator (r/osugame & IRC)

### 6.1 Procedural Media Generation

The system features an in-game forum tab reproducing community culture across eras:

* **Scoreposts (Standard Formatting):**
  `Player | Artist - Title [Diff] +MODS (99.14%) 2380/2384x 1xSb | 784pp (812pp if FC) | Their new top play!`
* **Discussions & Drama Threads:**
  * Accusations of cursor-dance / relax hacking.
  * Controversial map rankings (e.g., *"Is Sotarks ruining the game?"*).
  * Sudden retirement / military service announcements.
  * Post-tournament drama (e.g., bad referee calls, controversial tiebreakers).

### 6.2 SillyTavern Event Dispatcher

Whenever a notable event occurs (match win, #1 snipe, choke, injury), the engine posts a structured JSON payload to SillyTavern:

```json
{
  "event_type": "TOURNAMENT_UPSET",
  "data": {
    "in_game_date": "2014-11-23",
    "tournament_name": "osu! World Cup 2014",
    "stage": "Semifinals",
    "match_result": {
      "player_team": "Team Russia",
      "opponent_team": "Team Japan",
      "score": "5 - 4",
      "deciding_map": "xi - FREEDOM DiVE [FOUR DIMENSIONS] (Tiebreaker)"
    },
    "key_moments": [
      "User held a 1,800x combo on the tiebreaker with 98.8% accuracy.",
      "rrtyui dropped combo at the final spaced stream."
    ],
    "npc_reactions_needed": [
      {
        "name": "rrtyui",
        "attitude": "Graceful defeat, types 'plz enjoy game' in IRC match lobby.",
        "context": "Shocked by User's stamina resilience on 222 BPM."
      }
    ],
    "reddit_thread_spec": {
      "upvotes": 1420,
      "tone": "Complete disbelief, memes about Russian vodka stamina, praise for rrtyui's sportsmanship."
    }
  }
}
```

---

## 7. Implementation Roadmap for Claude Code

### Phase 1: Database & Core Stat Engine
* Set up SQLite schema: `Players`, `Attributes`, `Scores`, `Inventory`, `TournamentBrackets`.
* Implement the 18-attribute calculation model and weighted total PP formula.
* Implement the decay, injury, and fatigue state machines.

### Phase 2: Beatmap Mirror & Audio Streaming
* Integrate client for Nerinyan/Catboy API with date-bound queries (`ranked_date <= in_game_date`).
* Embed native HTML5 audio stream player (`https://b.ppy.sh/preview/{beatmapset_id}.mp3`).
* Integrate `rosu-pp-py` / `rosu-pp-js` for deterministic star rating and PP outputs.

### Phase 3: Tournament & Lifecycle Modules
* Implement the procedural Double Elimination bracket generator.
* Build the stage-by-stage map pool generator (NM, HD, HR, DT, TB slots).
* Seed dynamic stat/age curves for 40+ historical legends (Cookiezi, rrtyui, hvick225, Rafis, Vaxei, WhiteCat, mrekk, etc.).

### Phase 4: Social UI & SillyTavern Integration
* Build the frontend Reddit forum feed and IRC chat overlay.
* Implement bidirectional REST/Webhook handlers connecting game engine events to SillyTavern prompts.