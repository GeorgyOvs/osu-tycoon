import { request } from './api'
import { getLang } from './i18n'

export interface AchievementInfo {
  key: string
  category: string
  rarity: 'common' | 'uncommon' | 'rare' | 'epic' | 'legendary'
  name: string
  description: string
  unlocked_on?: string
  progress?: number
}

export interface LegacyRecord {
  key: string
  label: string
  value: number
  date?: string | null
}

export interface BudgetMonth {
  month: string
  categories: Record<string, number>
  income: number
  costs: number
  net: number
}

export interface Budget {
  realistic: boolean
  money: number
  loan: number
  loan_limit: number
  months: BudgetMonth[]
  runway: { weekly_burn: number; winnings_per_week: number; weeks_left_now: number | null; weeks_left_pro: number | null }
  occupation: string
}

export interface Epilogue {
  reason: string
  retired_on: string
  years: number
  age: number | null
  best_rank: number | null
  peak_pp: number
  play_count: number
  achievements: number
  tournament_wins: number
  score: number
  hardcore: boolean
  lines: string[]
  arcs: string[]
  rivals: string[]
}

export interface Legacy {
  status: {
    retired: boolean
    retired_on: string | null
    reason: string | null
    hardcore: boolean
    economy: 'simple' | 'realistic'
    started_on: string | null
  }
  score: number
  records: LegacyRecord[]
  achievements: {
    unlocked: AchievementInfo[]
    next: AchievementInfo[]
    total: number
    unlocked_count: number
    categories: Record<string, string>
  }
  budget: Budget
  epilogue: Epilogue | null
}

export interface HallEntry {
  id: number
  name: string
  country: string
  hardcore: boolean
  reason: string
  retired_on: string
  best_rank: number | null
  peak_pp: number
  achievements: number
  score: number
  years: number
}

const q = () => `lang=${getLang()}`

export const legacyApi = {
  get: (id: number) => request<Legacy>(`/api/players/${id}/legacy?${q()}`),
  retire: (id: number) => request<Legacy>(`/api/players/${id}/retire?${q()}`, { method: 'POST', body: JSON.stringify({}) }),
  loan: (id: number, amount: number) =>
    request<Budget>(`/api/players/${id}/economy/loan`, { method: 'POST', body: JSON.stringify({ amount }) }),
  repay: (id: number, amount: number) =>
    request<Budget>(`/api/players/${id}/economy/repay`, { method: 'POST', body: JSON.stringify({ amount }) }),
  hall: () => request<HallEntry[]>('/api/hall-of-fame'),
}
