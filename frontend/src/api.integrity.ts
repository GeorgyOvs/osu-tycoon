import { request } from './api'
import { getLang } from './i18n'

export interface CaseOption {
  key: string
  label: string
  hint: string
}

export interface IntegrityCase {
  id: number
  kind: string
  title: string
  body: string
  status: 'open' | 'cleared' | 'closed' | 'restricted'
  opened: string
  expires: string
  resolved: string | null
  days_left: number | null
  response: string | null
  outcome: string
  auto: boolean
  rep_delta: number
  restricted_days: number | null
  options: CaseOption[]
}

export interface IntegrityOverview {
  reputation: number
  label: string
  restricted_until: string | null
  effects: { sponsor: number; followers: number }
  suspicion: { level: number; factors: { kind: string; level: number }[] }
  open: IntegrityCase[]
  history: IntegrityCase[]
  log: { date: string; delta: number; reason: string }[]
}

export interface WearRow {
  category: 'mouse' | 'tablet' | 'keyboard'
  item: string | null
  active: boolean
  wear: number
  condition: string
  penalty: number
  service_cost: number
  replace_cost: number | null
}

export interface SetupOverview {
  wear: WearRow[]
  comfort: number
  comfort_penalty: number
  network: {
    region: string
    region_name: string
    local_ping: number
    lobby_ping: number
    tier: string
    isp_level: number
    isp_max: number
    isp_price: number | null
    pressure_penalty: number
    regional_servers: boolean
  }
  money: number
}

const q = () => `lang=${getLang()}`
const post = (path: string, body?: unknown) =>
  request<SetupOverview>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined })

export const integrityApi = {
  overview: (id: number) => request<IntegrityOverview>(`/api/players/${id}/integrity?${q()}`),
  respond: (id: number, caseId: number, choice: string) =>
    request<IntegrityOverview>(`/api/players/${id}/integrity/cases/${caseId}/respond?${q()}`, {
      method: 'POST',
      body: JSON.stringify({ choice }),
    }),
  setup: (id: number) => request<SetupOverview>(`/api/players/${id}/setup`),
  maintain: (id: number, category: string) => post(`/api/players/${id}/setup/maintain`, { category }),
  replace: (id: number, category: string) => post(`/api/players/${id}/setup/replace`, { category }),
  upgradeIsp: (id: number) => post(`/api/players/${id}/setup/isp`),
}
