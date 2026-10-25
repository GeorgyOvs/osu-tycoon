import { request } from './api'

export interface SearchPlayer {
  id: number
  name: string
  country: string
  kind: string
  status: string
  rank: number | null
  pp: number
}

export interface SearchMap {
  beatmapset_id: number
  artist: string
  title: string
  creator: string
  ranked_date: string
  play_count: number
  diffs: { beatmap_id: number; version: string; stars: number }[]
}

export interface HistoryPoint {
  date: string
  rank: number | null
  pp: number
}

export interface NpcTopPlay {
  beatmap_id: number
  beatmapset_id: number | null
  artist: string
  title: string
  version: string
  stars: number
  mods: string
  accuracy: number
  max_combo: number
  misses: number
  score: number
  pp: number
  set_on: string
}

export interface NpcOsuProfile {
  id: number
  name: string
  country: string
  kind: 'legend' | 'procedural' | 'real'
  status: string
  away_until: string | null
  joined: string
  note: string
  aliases: string[]
  archetype: string
  overall: number
  composites: Record<string, number>
  strengths: string[]
  weaknesses: string[]
  pp: number
  global_rank: number | null
  country_rank: number | null
  peak_rank: number | null
  peak_date: string | null
  titles: number
  form: number
  motivation: number
  history: HistoryPoint[]
  top_plays: NpcTopPlay[]
  news: { date: string; type: string; message: string }[]
  relationship: {
    rival: { heat: number; record: Record<string, number>; since: string } | null
    teammate: boolean
    team: string | null
    mentor: boolean
    messages: number
  }
}

export interface CompareSide {
  name: string
  country: string
  rank: number | null
  pp: number
  accuracy: number | null
  peak_rank: number | null
  composites: Record<string, number>
  history: HistoryPoint[]
}

export interface Comparison {
  you: CompareSide
  them: CompareSide & { id: number }
  head_to_head: Record<string, number>
}

export const searchApi = {
  search: (id: number, q: string) =>
    request<{ players: SearchPlayer[]; maps: SearchMap[] }>(`/api/players/${id}/search?q=${encodeURIComponent(q)}`),
  npc: (id: number, npcId: number) => request<NpcOsuProfile>(`/api/players/${id}/npcs/${npcId}/osu-profile`),
  compare: (id: number, npcId: number) => request<Comparison>(`/api/players/${id}/npcs/${npcId}/compare`),
  byName: (id: number, name: string) => request<{ id: number; name: string }>(`/api/players/${id}/npc-by-name/${encodeURIComponent(name)}`),
}
