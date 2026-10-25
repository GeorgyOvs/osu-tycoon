import { request } from './api'
import { getLang } from './i18n'

export type ItemStatus = 'available' | 'locked' | 'owned' | 'subscribed' | 'active' | 'cooldown'

export interface SpendingItem {
  key: string
  icon: string
  kind: 'one_off' | 'timed' | 'sub' | 'owned'
  name: string
  description: string
  perk: string
  price: number
  affordable: boolean
  status: ItemStatus
  reason: string
  cooldown_left: number
  days: number
  choices: { key: string; label: string }[]
}

export interface SpendingCategory {
  key: string
  name: string
  icon: string
  items: SpendingItem[]
}

export interface Spending {
  money: number
  categories: SpendingCategory[]
  subscriptions: { key: string; name: string; price: number; since: string; months: number }[]
  monthly_total: number
  effects: { label: string; days_left: number; source: string }[]
  owned: string[]
}

export interface BuyResult {
  key: string
  price: number
  choice: string | null
  applied: Record<string, unknown> & { skill?: Record<string, number>; mod?: { label: string } }
  message: string
  message_ru: string
}

const q = () => `lang=${getLang()}`

export const spendingApi = {
  get: (id: number) => request<Spending>(`/api/players/${id}/spending?${q()}`),
  buy: (id: number, key: string, choice?: string) =>
    request<BuyResult>(`/api/players/${id}/spending/${key}/buy`, { method: 'POST', body: JSON.stringify({ choice: choice ?? null }) }),
  cancel: (id: number, key: string) =>
    request<{ key: string; message: string; message_ru: string }>(`/api/players/${id}/spending/${key}/cancel`, { method: 'POST' }),
}
