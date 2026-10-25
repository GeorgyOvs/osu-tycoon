import { request, type ActionResult } from './api'

export interface Mind {
  confidence: Record<string, number>
  fear: { npc_id: number; name: string; value: number }[]
  big_stage: number | null
  big_stage_maps: number
}

export interface MentorState {
  npc_id: number
  name: string
  country: string
  group: string
  since: string
  bond: number
  interest: number
  sessions: number
  last_session: string
  boost: number
  boost_until: string
  boost_active: boolean
  rank: number | null
  overall: number | null
  gap: number | null
}

export interface MentorCandidate {
  npc_id: number
  name: string
  country: string
  rank: number
  overall: number
  focus: string
  chance: number
  blocked: string | null
}

export interface MentorOverview {
  available: boolean
  reason: string | null
  mentor: MentorState | null
  candidates: MentorCandidate[]
  log: { date: string; text: string }[]
  mind: Mind
}

export const mentorApi = {
  get: (id: number) => request<MentorOverview>(`/api/players/${id}/mentor`),
  ask: (id: number, npcId: number) =>
    request<MentorOverview & { accepted: boolean; message: string }>(`/api/players/${id}/mentor/ask`, {
      method: 'POST',
      body: JSON.stringify({ npc_id: npcId }),
    }),
  session: (id: number, hours: number) =>
    request<{ action: ActionResult; advice: string | null; mentor: MentorState | null }>(`/api/players/${id}/mentor/session`, {
      method: 'POST',
      body: JSON.stringify({ hours }),
    }),
  end: (id: number) => request<MentorOverview>(`/api/players/${id}/mentor/end`, { method: 'POST' }),
}
