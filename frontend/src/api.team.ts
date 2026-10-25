import { request } from './api'

export interface TeamMember {
  npc_id: number
  name: string
  country: string
  role: string
  bond: number
  rank: number | null
  pp: number
  overall: number
  status: string
  joined_on: string
}

export interface TeamLog {
  date: string
  text: string
}

export interface TeamPerks {
  learning_bonus_pct: number
  nerve_bonus_pct: number
  sponsor_monthly: number
  followers_weekly: number
}

export interface Team {
  id: number
  name: string
  tag: string
  status: string
  founded_on: string
  chemistry: number
  reputation: number
  user_role: string
  channel: string
  size: number
  members: TeamMember[]
  log: TeamLog[]
  ready_for_cup: boolean
  scrim_today: boolean
  last_scrim: string | null
  cups_won: number
  expires_on: string | null
  perks: TeamPerks
  invited_by: string | null
}

export interface TeamCup {
  id: number
  name: string
  start_date: string
  registration_opens: string
  registered: boolean
  status: string
  size: number
  can_register: boolean
}

export interface TeamState {
  date: string
  team: Team | null
  invite: Team | null
  history: { name: string; tag: string; status: string; founded_on: string; left_on: string | null }[]
  cups: TeamCup[]
  can_found: boolean
  found_blocker: string | null
  found_cost: number
  limits: { max_size: number; cup_size: number; max_scrim_hours: number }
}

export interface TeamCandidate {
  npc_id: number
  name: string
  country: string
  rank: number | null
  pp: number
  overall: number
  odds: number
  rival: boolean
  strength: string
  refused_until: string | null
}

const base = (id: number) => `/api/players/${id}/team`
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const teamApi = {
  state: (id: number) => request<TeamState>(base(id)),
  candidates: (id: number) => request<TeamCandidate[]>(`${base(id)}/candidates?limit=24`),
  found: (id: number, name: string, tag: string) => post<TeamState>(`${base(id)}/found`, { name, tag }),
  accept: (id: number, teamId: number) => post<TeamState>(`${base(id)}/invites/${teamId}/accept`),
  decline: (id: number, teamId: number) => post<TeamState>(`${base(id)}/invites/${teamId}/decline`),
  recruit: (id: number, npcId: number) =>
    post<{ accepted: boolean; message: string; state: TeamState }>(`${base(id)}/recruit`, { npc_id: npcId }),
  kick: (id: number, npcId: number) => post<TeamState>(`${base(id)}/kick`, { npc_id: npcId }),
  leave: (id: number) => post<TeamState>(`${base(id)}/leave`),
  scrim: (id: number, hours: number) =>
    post<{ message: string; chemistry: number; state: TeamState }>(`${base(id)}/scrim`, { hours }),
}
