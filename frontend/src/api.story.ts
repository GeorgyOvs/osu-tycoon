import { request } from './api'
import { getLang } from './i18n'

export interface EventOption {
  key: string
  label: string
  hint: string
}

export interface LifeEvent {
  id: number
  key: string
  category: string
  title: string
  body: string
  created_on: string
  expires_on: string | null
  status: 'pending' | 'resolved' | 'expired'
  options: EventOption[]
  choice: string | null
  outcome: string
  applied: {
    motivation?: number
    morale?: number
    fatigue?: number
    form?: number
    money?: number
    followers?: number
    skill?: Record<string, number>
    rival_heat?: number
    reputation?: number
    wear?: number
    injury?: string
    mod?: { label: string; until: string }
  }
  auto: boolean
  default: string
}

export interface ActiveEffect {
  label: string
  until: string
  days_left: number
  free_hours: number
  learning: number
  play: number
}

export interface EventsOverview {
  pending: LifeEvent[]
  history: LifeEvent[]
  effects: ActiveEffect[]
}

export interface Goal {
  id: number
  key: string
  title: string
  description: string
  status: 'active' | 'done' | 'failed' | 'dropped'
  progress: number
  created_on: string
  deadline: string | null
  days_left: number | null
  finished_on: string | null
  reward: { money?: number; motivation?: number; morale?: number; followers?: number }
  inspired: boolean
}

export interface StoryArc {
  id: number
  key: string
  title: string
  status: 'active' | 'resolved'
  started_on: string
  ended_on: string | null
  chapters: { date: string; text: string }[]
}

export interface GoalsOverview {
  active: Goal[]
  finished: Goal[]
  arcs: StoryArc[]
}

const q = () => `lang=${getLang()}`

export const storyApi = {
  events: (id: number) => request<EventsOverview>(`/api/players/${id}/events?${q()}`),
  pendingCount: (id: number) => request<{ pending: number }>(`/api/players/${id}/events/count`),
  choose: (id: number, eventId: number, choice: string) =>
    request<LifeEvent>(`/api/players/${id}/events/${eventId}/choose?${q()}`, { method: 'POST', body: JSON.stringify({ choice }) }),
  goals: (id: number) => request<GoalsOverview>(`/api/players/${id}/goals?${q()}`),
  dropGoal: (id: number, goalId: number) =>
    request<GoalsOverview>(`/api/players/${id}/goals/${goalId}/drop?${q()}`, { method: 'POST' }),
}
