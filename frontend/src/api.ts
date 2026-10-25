export interface CharacterOptions {
  budget: number
  perks: Record<string, { label: string; description: string; cost: number }>
  presets: Record<string, { label: string; perks: string[] }>
  conflicts: [string, string][]
  scenarios?: Record<string, { label: string; description: string; min_age: number }>
}

export interface BeatmapInfo {
  beatmap_id: number
  beatmapset_id: number | null
  artist: string
  title: string
  version: string
  creator: string
  preview_url: string | null
}

export interface PpResponse {
  beatmap: BeatmapInfo
  mods: string
  pp: number
  pp_aim: number
  pp_speed: number
  pp_accuracy: number
  stars: number
  aim_difficulty: number
  speed_difficulty: number
  max_combo: number
  ar: number
  od: number
  cs: number
  hp: number
  bpm: number
}

export interface SubStat {
  key: string
  label: string
  value: number
  base: number
  cap: number
  rust: number
  plateau: number
}

export interface AttributeGroup {
  key: string
  label: string
  value: number
  subs: SubStat[]
}

export interface PlayerConditions {
  fatigue: number
  motivation: number
  morale: number
  consecutive_training_days: number
}

export type InjuryState = 'healthy' | 'minor_strain' | 'severe_rsi'

export interface Injury {
  state: InjuryState
  until: string | null
  strain_recovery_days: number
  physio_days: number
}

export interface Life {
  gender: string
  pronouns: string
  age: number | null
  occupation: string
  money: number
  free_hours_today: number
  followers: number
  input_device: string
  tap_style: string
  style_adaptation: number
}

export interface Player {
  character_build?: { preset?: string; perks?: string[]; unbalanced?: boolean; hardcore?: boolean; economy?: string }
  id: number
  life: Life | null
  pp_system: { key: string; name: string; summary: string; ranking: string; since: string } | null
  badges: { name: string; tournament_id: number; date: string; tier?: string }[]
  name: string
  country: string
  in_game_date: string
  era: string
  era_label: string
  overall: number
  pp_potential: number
  tournament_strength: number
  potential: number
  form: number
  traits: string[]
  ergonomics: number
  attributes: AttributeGroup[]
  conditions: PlayerConditions
  injury: Injury
  total_pp: number
  accuracy: number
  play_count: number
  global_rank: number | null
  previous_rank: number | null
}

export interface Score {
  id: number
  beatmap_id: number
  beatmapset_id: number | null
  artist: string
  title: string
  difficulty_name: string
  mods: string
  accuracy: number
  max_combo: number
  misses: number
  stars: number
  pp: number
  played_on: string
  grade?: string
}

export interface TopPlay extends Score {
  weight: number
  weighted_pp: number
}

export interface PlayerProfile extends Player {
  top_plays: TopPlay[]
  recent_scores: Score[]
}

export interface RealPlay {
  id: number
  beatmap_id: number
  artist: string
  title: string
  difficulty_name: string
  mods: string
  accuracy: number
  max_combo: number
  misses: number
  stars: number
  pp: number
  played_at: string
  baseline: boolean
}

export interface RealSync {
  baseline: boolean
  imported: number
  plays: RealPlay[]
}

export interface ScoreSubmitResult {
  score: Score
  is_new_top_play: boolean
  top_play_position: number | null
  pp_gained: number
  player: Player
}

export interface PlayInput {
  beatmap_id: number
  mods: string
  accuracy: number
  misses: number
  combo?: number
}

export interface Drill {
  key: string
  label: string
  description: string
  targets: Record<string, number>
  strain: number
  efficiency: number
  available: boolean
  available_from: string
  sets_scores: boolean
}

export interface GameEvent {
  date: string
  type: string
  message: string
  data: Record<string, unknown>
}

export interface ActionResult {
  start_date: string
  end_date: string
  days: number
  events: GameEvent[]
  deltas: Record<string, number>
  player: Player
  scores?: Score[]
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!resp.ok) {
    const body = await resp.json().catch(() => null)
    const detail = body?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg).join('; ')
          : `${resp.status} ${resp.statusText}`
    throw new Error(message)
  }
  return resp.status === 204 ? (undefined as T) : resp.json()
}

export const api = {
  listPlayers: () => request<Player[]>('/api/players'),
  getPlayer: (id: number) => request<PlayerProfile>(`/api/players/${id}`),
  creationOptions: () => request<CharacterOptions>('/api/players/creation-options'),
  createPlayer: (body: { name: string; country: string; start_date: string; age?: number; gender?: string; preset?: string; perks?: string[]; unbalanced?: boolean; scenario?: string; hardcore?: boolean; realistic_economy?: boolean }) =>
    request<PlayerProfile>('/api/players', { method: 'POST', body: JSON.stringify(body) }),
  deletePlayer: (id: number, confirmName?: string) =>
    request<void>(`/api/players/${id}${confirmName ? `?confirm=${encodeURIComponent(confirmName)}` : ''}`, { method: 'DELETE' }),
  calculatePp: (body: PlayInput) =>
    request<PpResponse>('/api/pp/calculate', { method: 'POST', body: JSON.stringify(body) }),
  submitScore: (playerId: number, body: PlayInput) =>
    request<ScoreSubmitResult>(`/api/players/${playerId}/scores`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  syncRealPlays: (playerId: number) =>
    request<RealSync>(`/api/players/${playerId}/real/sync`, { method: 'POST' }),
  listRealPlays: (playerId: number) => request<RealPlay[]>(`/api/players/${playerId}/real?limit=20`),
  listDrills: (playerId: number) => request<Drill[]>(`/api/players/${playerId}/drills`),
  train: (playerId: number, body: { drill: string; hours_per_day: number; days: number }) =>
    request<ActionResult>(`/api/players/${playerId}/train`, { method: 'POST', body: JSON.stringify(body) }),
  rest: (playerId: number, body: { days: number; physio: boolean }) =>
    request<ActionResult>(`/api/players/${playerId}/rest`, { method: 'POST', body: JSON.stringify(body) }),
}

export const fmt = {
  pp: (n: number) => `${Math.round(n).toLocaleString('en-US')}pp`,
  acc: (n: number) => `${n.toFixed(2)}%`,
  stars: (n: number) => `${n.toFixed(2)}★`,
  rank: (n: number | null) => (n == null ? '—' : `#${n.toLocaleString('en-US')}`),
  mods: (m: string) => m || 'NM',
}

export interface Beatmap {
  id: number
  version: string
  stars: number
  ar: number
  cs: number
  od: number
  hp: number
  bpm: number
  total_length: number
  hit_length: number
  max_combo: number | null
  count_circles: number
  count_sliders: number
  play_count: number
  pass_count: number
}

export interface BeatmapSet {
  id: number
  artist: string
  title: string
  creator: string
  source: string
  status: string
  ranked_date: string
  play_count: number
  favourite_count: number
  bpm: number
  preview_url: string
  cover_url: string
  beatmaps: Beatmap[]
}

export interface IndexStatus {
  synced_until: string | null
  target: string | null
  running: boolean
  error: string | null
  indexed_sets: number
}

export interface BeatmapSearch {
  before: string
  total: number
  complete: boolean
  index: IndexStatus
  results: BeatmapSet[]
}

export type BeatmapSort = 'ranked_desc' | 'ranked_asc' | 'plays' | 'favourites' | 'stars_desc' | 'stars_asc'

export interface BeatmapQuery {
  before: string
  q?: string
  min_stars?: number
  max_stars?: number
  sort?: BeatmapSort
  limit?: number
  offset?: number
}

export function searchBeatmaps(query: BeatmapQuery) {
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== '') params.set(k, String(v))
  return request<BeatmapSearch>(`/api/beatmaps?${params}`)
}

/** osu!'s difficulty colour spectrum, simplified. */
export function starColor(stars: number): string {
  if (stars < 2) return '#4fc0ff'
  if (stars < 2.7) return '#4fffd5'
  if (stars < 4) return '#c6ff4f'
  if (stars < 5.3) return '#ff8c4f'
  if (stars < 6.5) return '#ff4f75'
  if (stars < 8) return '#a64fff'
  return '#6563de'
}

export function formatLength(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export interface TimelineBucket {
  misses: number
  hp_min: number
  reached: boolean
}

/** Columnar replay data: bucket start times, combo, health, cumulative misses, running accuracy, strain 0-1. */
export interface Replay {
  duration: number
  end: number
  max_combo: number
  objects: number
  t: number[]
  combo: number[]
  hp: number[]
  misses: number[]
  acc: number[]
  strain: number[]
  kind: string[]
  moments: { t: number; type: string; text: string; n?: number; cause?: string; combo?: number }[]
}

export interface CommentaryLine {
  t: number
  text: string
  tone: 'neutral' | 'hype' | 'tense' | 'sad'
  who: string
}

export interface MatchCommentary {
  pre: CommentaryLine[]
  maps: CommentaryLine[][]
  between: CommentaryLine[][]
  post: CommentaryLine[]
}

export interface Attempt {
  passed: boolean
  fail_progress: number | null
  fail_time: number | null
  n300: number
  n100: number
  n50: number
  misses: number
  max_combo: number
  accuracy: number
  grade: string
  pp: number | null
  choked: boolean
  miss_causes: Record<string, number>
  key_moments: string[]
  timeline: TimelineBucket[]
  replay?: Replay
  commentary?: CommentaryLine[]
}

export interface PlayResult {
  beatmap: BeatmapInfo
  mods: string
  stars: number
  attempts: Attempt[]
  best_index: number | null
  score: Score | null
  is_new_top_play: boolean
  top_play_position: number | null
  pp_gained: number
  previous_best_pp?: number | null
  board_rank?: number | null
  board_size?: number | null
}

export interface SessionResult {
  date: string
  hours: number
  plays: PlayResult[]
  training: Record<string, number>
  events: GameEvent[]
  deltas: Record<string, number>
  player: Player
}

export interface MapDemand {
  stars: number
  aim: number
  speed: number
  ar: number
  od: number
  cs: number
  hp: number
  bpm: number
  drain_seconds: number
  max_combo: number
  fastest_stream_bpm: number
  longest_stream: number
}

export interface Assessment {
  block?: { at_seconds: number; severity: number } | null
  familiarity?: number
  mastery?: number
  beatmap: BeatmapInfo
  mods: string
  map: MapDemand
  pass_rate: number
  fc_rate: number
  median_accuracy: number | null
  median_misses: number | null
  peak_ratios: Record<string, number>
  weakest: string
}

export interface QueuedPlay {
  beatmap_id: number
  beatmapset_id: number
  title: string
  version: string
  stars: number
  length: number // seconds
  mods: string
  attempts: number
}

export const playApi = {
  assess: (playerId: number, beatmapId: number, mods: string) =>
    request<Assessment>(`/api/players/${playerId}/assess/${beatmapId}?mods=${encodeURIComponent(mods)}`),
  session: (playerId: number, plays: { beatmap_id: number; mods: string; attempts: number }[]) =>
    request<SessionResult>(`/api/players/${playerId}/sessions`, { method: 'POST', body: JSON.stringify({ plays }) }),
  history: (playerId: number) =>
    request<{ id: number; mode: 'auto' | 'manual'; result: SessionResult; preset?: string | null; hours?: number | null; stream?: boolean }[]>(
      `/api/players/${playerId}/sessions/history?limit=20`,
    ),
}

export interface NewsItem {
  id: number
  date: string
  type: string
  message: string
  importance: number
  data: Record<string, unknown>
}

export interface LeaderboardRow {
  rank: number | null
  name: string
  country: string
  pp: number
  overall: number | null
  kind: 'user' | 'legend' | 'procedural'
  npc_id: number | null
  status: string
}

export interface Leaderboard {
  date: string
  rows: LeaderboardRow[]
  you: LeaderboardRow | null
}

export interface NpcProfile {
  id: number
  name: string
  country: string
  kind: string
  status: string
  overall: number
  composites: Record<string, number>
  form: number
  pp: number
  rank: number | null
  best_rank: number | null
  titles: number
  away_until: string | null
  note: string
  aliases: string[]
  archetype: string
  pp_potential: number
  tournament_strength: number
  best_score_types: string[]
  peaks: string[]
  weaknesses: string[]
  match_stats: { played?: number; wins?: number; losses?: number; upset_wins?: number; summary?: string }
  development: Record<string, unknown>
  storyline: Record<string, unknown>
  rival: { id: number; name: string; rank: number | null } | null
}

export interface TournamentSummary {
  id: number
  name: string
  tier: string
  rank_min: number
  rank_max: number
  size: number
  team_size: number
  registration_opens: string
  start_date: string
  base_stars: number
  status: 'upcoming' | 'ongoing' | 'finished'
  user_registered: boolean
  can_register: boolean
  eligible: boolean
  winner: string | null
  user_placement: string | null
}

export interface MatchPlayer {
  side: 'a' | 'b'
  name: string
  kind: string
  score: number
  accuracy: number
  misses: number
  combo: number
  max_combo: number
  choked: boolean
  key_moments: string[]
  passed?: boolean
  grade?: string
  replay?: Replay
}

export interface MatchMap {
  slot?: string
  picked_by?: string
  score_a?: number
  score_b?: number
  beatmap_id?: number
  title?: string
  mods?: string
  stars?: number
  players?: MatchPlayer[]
  bans?: { a: string[]; b: string[] }
  winner?: 'a' | 'b'
  tie?: 'accuracy' | 'misses' | 'sudden_death'
}

export interface DraftSlot {
  slot: string
  family: string
  mods: string
  stars: number
  title: string
  beatmap_id: number | null
  state: 'open' | 'banned' | 'picked' | 'played'
  by: 'a' | 'b' | null
  legal: boolean
  score_a?: number
  score_b?: number
  winner?: 'a' | 'b'
}

export interface DraftLogLine {
  kind: 'ban' | 'pick' | 'tb' | 'result'
  side: 'a' | 'b' | null
  slot: string
  who: string
  mine: boolean
  score_a?: number
  score_b?: number
}

export interface DraftState {
  match_id: number
  tournament_id: number
  stage: string
  first_to: number
  finished: boolean
  user_side: 'a' | 'b'
  names: { a: string; b: string }
  seeds: { a: number; b: number }
  score: { a: number; b: number }
  turn: { kind: 'ban' | 'pick' | 'tb' | 'play' | 'done'; side: 'a' | 'b' | null; mine: boolean }
  legal: string[]
  slots: DraftSlot[]
  bans: { a: string[]; b: string[] }
  first_ban: 'a' | 'b'
  first_pick: 'a' | 'b'
  bans_per_side: number
  log: DraftLogLine[]
  maps: MatchMap[]
  warmup: { used: boolean; available: boolean }
}

export interface TournamentMatch {
  id: number
  key: string
  week: number
  stage: string
  first_to: number
  due: string
  entry_a: number | null
  entry_b: number | null
  winner: number | null
  score_a: number
  score_b: number
  played_on: string | null
  is_user_match: boolean
  maps: MatchMap[]
  commentary?: MatchCommentary | null
}

export interface TournamentEntry {
  id: number
  kind: string
  name: string
  country: string
  seed: number
  npc_id: number | null
  includes_user: boolean
  placement: string | null
  members: string[]
}

export interface PoolEntry {
  slot?: string
  stars?: number
  beatmap_id?: number | null
  title?: string
  // qualifier rows reuse the pools map under the "qualifiers" key
  seed?: number
  name?: string
  country?: string
  kind?: string
  score?: number
}

export interface TournamentDetail extends TournamentSummary {
  entries: TournamentEntry[]
  matches: TournamentMatch[]
  pools: Record<string, PoolEntry[]>
}

export interface TournamentList {
  date: string
  pending_match: TournamentMatch | null
  pending_tournament_id: number | null
  tournaments: TournamentSummary[]
}

export const worldApi = {
  news: (playerId: number, minImportance = 1) =>
    request<NewsItem[]>(`/api/players/${playerId}/news?min_importance=${minImportance}`),
  leaderboard: (playerId: number, country?: string, limit = 100) =>
    request<Leaderboard>(`/api/players/${playerId}/leaderboard?limit=${limit}${country ? `&country=${encodeURIComponent(country)}` : ''}`),
  npc: (playerId: number, npcId: number) => request<NpcProfile>(`/api/players/${playerId}/npcs/${npcId}`),
  tournaments: (playerId: number) => request<TournamentList>(`/api/players/${playerId}/tournaments`),
  tournament: (playerId: number, id: number) => request<TournamentDetail>(`/api/players/${playerId}/tournaments/${id}`),
  register: (playerId: number, id: number) =>
    request<TournamentSummary>(`/api/players/${playerId}/tournaments/${id}/register`, { method: 'POST' }),
  playMatch: (playerId: number, tournamentId: number, matchId: number, strategy?: { bans: string[]; picks: string[] }) =>
    request<TournamentDetail>(`/api/players/${playerId}/tournaments/${tournamentId}/matches/${matchId}/play`, {
      method: 'POST',
      body: JSON.stringify(strategy ?? {}),
    }),
  draft: (playerId: number, tournamentId: number, matchId: number) =>
    request<DraftState>(`/api/players/${playerId}/tournaments/${tournamentId}/matches/${matchId}/draft`),
  draftAct: (playerId: number, tournamentId: number, matchId: number, slot: string) =>
    request<DraftState>(`/api/players/${playerId}/tournaments/${tournamentId}/matches/${matchId}/draft/act`, {
      method: 'POST',
      body: JSON.stringify({ slot }),
    }),
  draftAuto: (playerId: number, tournamentId: number, matchId: number) =>
    request<DraftState>(`/api/players/${playerId}/tournaments/${tournamentId}/matches/${matchId}/draft/auto`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  draftWarmup: (playerId: number, tournamentId: number, matchId: number) =>
    request<DraftState>(`/api/players/${playerId}/tournaments/${tournamentId}/matches/${matchId}/draft/warmup`, { method: 'POST' }),
  practicePool: (playerId: number, tournamentId: number, week: number, hours: number) =>
    request<SessionResult>(`/api/players/${playerId}/sessions/pool`, {
      method: 'POST',
      body: JSON.stringify({ tournament_id: tournamentId, week, hours }),
    }),
}

export interface Duel {
  id: number
  date: string
  opponent: string
  opponent_country: string
  opponent_rank: number | null
  kind: 'friendly' | 'rival'
  best_of: number
  bans_per_side: number
  difficulty: 'comfortable' | 'even' | 'hard'
  status: 'pending' | 'played' | 'expired'
  pool: PoolEntry[]
  maps: MatchMap[]
  score_user: number
  score_npc: number
  won: boolean | null
  commentary?: MatchCommentary | null
}

export interface DuelChallenge {
  npc_id: number
  best_of: number
  kind: 'friendly' | 'rival'
  difficulty: 'comfortable' | 'even' | 'hard'
  bans_per_side: number
}

export const duelApi = {
  challenge: (playerId: number, body: DuelChallenge) =>
    request<Duel>(`/api/players/${playerId}/duels`, { method: 'POST', body: JSON.stringify(body) }),
  play: (playerId: number, duelId: number, strategy: { bans: string[]; picks: string[] }) =>
    request<Duel>(`/api/players/${playerId}/duels/${duelId}/play`, { method: 'POST', body: JSON.stringify(strategy) }),
  history: (playerId: number) => request<Duel[]>(`/api/players/${playerId}/duels`),
}

export interface ThreadSummary {
  id: number
  date: string
  board: string
  kind: string
  title: string
  author: string
  flair: string
  upvotes: number
  comment_count: number
  llm_status: string
}

export interface ForumComment {
  id: number
  parent_id: number | null
  author: string
  content: string
  upvotes: number
  source: string
}

export interface Thread extends ThreadSummary {
  body: string
  comments: ForumComment[]
}

export interface ChatLine {
  id: number
  date: string
  channel: string
  author: string
  content: string
  source: string
}

export const socialApi = {
  forum: (playerId: number, kind?: string) =>
    request<ThreadSummary[]>(`/api/players/${playerId}/forum${kind ? `?kind=${kind}` : ''}`),
  thread: (playerId: number, id: number) => request<Thread>(`/api/players/${playerId}/forum/${id}`),
  irc: (playerId: number, channel: string, afterId = 0) =>
    request<ChatLine[]>(`/api/players/${playerId}/irc?channel=${encodeURIComponent(channel)}&after_id=${afterId}`),
  channels: (playerId: number) => request<string[]>(`/api/players/${playerId}/irc/channels`),
  summary: (playerId: number) => request<ChannelSummary[]>(`/api/players/${playerId}/irc/summary`),
  nudge: (playerId: number) => request<{ new_lines: number }>(`/api/players/${playerId}/chatter/nudge`, { method: 'POST' }),
  say: (playerId: number, channel: string, text: string) =>
    request<ChatLine>(`/api/players/${playerId}/irc/say`, { method: 'POST', body: JSON.stringify({ channel, text }) }),
  dm: (playerId: number, to: string, text: string) =>
    request<ChatLine[]>(`/api/players/${playerId}/dm`, { method: 'POST', body: JSON.stringify({ to, text }) }),
}

export interface MapLeaderboardEntry {
  rank: number
  kind: 'user' | 'legend' | 'npc' | 'anchor'
  name: string
  country: string
  mods: string
  score: number
  accuracy: number
  max_combo: number
  misses: number
  pp: number
  set_on: string
  npc_id: number | null
  source: string | null
}

export interface MapLeaderboard {
  beatmap_id: number
  date: string
  entries: MapLeaderboardEntry[]
  user_rank: number | null
  record_history?: MapLeaderboardEntry[]
  first_place_history?: { date: string; sniper: string; sniped: string; score: number; mods: string; accuracy: number }[]
}

export const leaderboardApi = {
  map: (playerId: number, beatmapId: number) =>
    request<MapLeaderboard>(`/api/players/${playerId}/beatmaps/${beatmapId}/leaderboard`),
}

export interface SessionPreset {
  key: string
  label: string
  description: string
  mods: string
  available: boolean
}

export const presetApi = {
  list: (playerId: number) => request<SessionPreset[]>(`/api/players/${playerId}/presets`),
  auto: (playerId: number, preset: string, hours: number, stream = false) =>
    request<SessionResult>(`/api/players/${playerId}/sessions/auto`, {
      method: 'POST',
      body: JSON.stringify({ preset, hours, stream }),
    }),
}

export interface ShopItem {
  key: string
  name: string
  category: string
  year: number
  month: number
  until: number | null
  price: number
  launch_price: number
  is_new: boolean
  aim: number
  tapping: number
  ar_cap: number | null
  ergonomics: number | null
  notes: string
  available: boolean
  owned: boolean
  equipped: boolean
}

export interface Shop {
  money: number
  input_device: string
  ergonomics: number
  effects: { aim: number; tapping: number; ar_cap: number | null; missing: string[] }
  items: ShopItem[]
}

export interface Rival {
  npc_id: number
  name: string
  country: string
  kind: string
  rank: number | null
  overall: number
  heat: number
  since: string
  record: Record<string, number>
}

export const lifeApi = {
  shop: (id: number) => request<Shop>(`/api/players/${id}/shop`),
  buy: (id: number, key: string) => request<Shop>(`/api/players/${id}/shop/${key}/buy`, { method: 'POST' }),
  equip: (id: number, key: string) => request<Shop>(`/api/players/${id}/shop/${key}/equip`, { method: 'POST' }),
  playstyle: (id: number, body: { input_device?: string; tap_style?: string }) =>
    request<Player>(`/api/players/${id}/playstyle`, { method: 'POST', body: JSON.stringify(body) }),
  occupation: (id: number, occupation: string) =>
    request<Player>(`/api/players/${id}/occupation`, { method: 'POST', body: JSON.stringify({ occupation }) }),
  rivals: (id: number) => request<Rival[]>(`/api/players/${id}/rivals`),
}

export interface WeekDay {
  type: 'train' | 'session' | 'rest' | 'pool'
  hours?: number
  drill?: string
  preset?: string
  stream?: boolean
  physio?: boolean
  tournament_id?: number
  week?: number
}

export interface WeekResult {
  start_date: string
  end_date: string
  days: { date: string; type: string; ok: boolean; summary: string; events: GameEvent[] }[]
  stopped_early: string | null
  deltas: Record<string, number>
  scores: Score[]
  money_change: number
  followers_change: number
  player: Player
}

export const weekApi = {
  live: (playerId: number, days: WeekDay[]) =>
    request<WeekResult>(`/api/players/${playerId}/week`, { method: 'POST', body: JSON.stringify({ days }) }),
}

export interface ChannelSummary {
  channel: string
  last_id: number
  last_author: string
  last_content: string
  last_date: string
  last_source: string
  total: number
}

export interface OsuProfile {
  joined: string
  global_rank: number | null
  country_rank: number | null
  peak_rank: number | null
  peak_date: string | null
  pp: number
  accuracy: number
  play_count: number
  ranked_score: number
  total_score: number
  level: number
  level_progress: number
  total_hits: number
  max_combo: number
  play_time_seconds: number
  grades: Record<'XH' | 'X' | 'SH' | 'S' | 'A', number>
  followers: number
  me: string
  input_device: string
  tap_style: string
  history: { date: string; rank: number | null; pp: number }[]
}

export const profileApi = {
  get: (id: number) => request<OsuProfile>(`/api/players/${id}/osu-profile`),
  setMe: (id: number, text: string) => request<OsuProfile>(`/api/players/${id}/me`, { method: 'PUT', body: JSON.stringify({ text }) }),
}
