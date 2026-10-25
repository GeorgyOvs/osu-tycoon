import { request } from './api'
import { getLang } from './i18n'

export interface MapHintDim {
  key: 'aim' | 'tapping' | 'reading' | 'stamina'
  label: string
  need_comfort: [number, number]
  need_pass: [number, number]
  yours: number
  verdict: 'comfortable' | 'passable' | 'over'
  verdict_label: string
}

export interface MapHintData {
  beatmap_id: number
  mods: string
  stars: number
  bpm: number
  length: number
  main_skills: { key: string; label: string; detail: string }[]
  dims: MapHintDim[]
  notes: string[]
  precision: 'rough' | 'decent' | 'sharp'
  precision_label: string
  experience: number
}

const cache = new Map<string, Promise<MapHintData>>()

/** Slot names (NM2, HD1, TB...) carry their mods; the backend treats NM/FM/TB as no forced mods. */
export const slotMods = (slot: string | undefined) => (slot ?? '').replace(/\d+$/, '')

export const hintsApi = {
  get: (playerId: number, beatmapId: number, mods = '', day = '') => {
    const key = `${playerId}:${beatmapId}:${mods}:${getLang()}:${day}`
    let hit = cache.get(key)
    if (!hit) {
      hit = request<MapHintData>(
        `/api/players/${playerId}/maps/${beatmapId}/hint?mods=${encodeURIComponent(mods)}&lang=${getLang()}`,
      )
      hit.catch(() => cache.delete(key))
      cache.set(key, hit)
    }
    return hit
  },
}
