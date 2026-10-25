import { request } from './api'
import { getLang } from './i18n'

export interface NotificationItem {
  id: string
  kind: string
  date: string
  message: string
  tab: string
  priority: number
  action: { type: 'register'; tournament_id: number; name: string } | null
}

export const notifyApi = {
  list: (playerId: number) => request<NotificationItem[]>(`/api/players/${playerId}/notifications?lang=${getLang()}`),
}
