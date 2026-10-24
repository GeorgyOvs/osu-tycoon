import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import type { Player } from '../api'
import { WeekPlanner } from '../components/WeekPlanner'
import { mockApi } from './setup'

const player = {
  id: 1, in_game_date: '2016-10-17', era: 'farm',
  life: { occupation: 'school', free_hours_today: 5 },
} as unknown as Player

describe('WeekPlanner', () => {
  beforeEach(() => localStorage.clear())

  it('sends the planned days and shows the summary', async () => {
    const calls = mockApi({
      'GET /api/players/1/drills': [
        { key: 'ranked_pack_grind', label: 'Ranked Pack Grind', available: true, sets_scores: true },
        { key: 'tech_maps', label: 'Unranked Tech Maps', available: true, sets_scores: false },
        { key: 'watch_replays', label: 'Watch Replays', available: true, sets_scores: false },
      ],
      'GET /api/players/1/presets': [
        { key: 'farm', label: 'Farm at your level', available: true },
        { key: 'push', label: 'Push your limits', available: true },
      ],
      'POST /api/players/1/week': {
        start_date: '2016-10-17', end_date: '2016-10-24', stopped_early: null,
        days: [{ date: '2016-10-17', type: 'train', ok: true, summary: 'ranked pack grind 2h', events: [] }],
        deltas: { snap_aim: 0.4 }, scores: [{ pp: 42 }], money_change: 10, followers_change: 0, player,
      },
    })
    let lived = false
    render(<WeekPlanner player={player} onLived={() => (lived = true)} />)
    expect(await screen.findByText('Mon 10-17')).toBeInTheDocument()
    expect(screen.getByText('Sun 10-23')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Live this week' }))
    await waitFor(() => expect(lived).toBe(true))
    const sent = calls.find((c) => c.path.endsWith('/week'))!.body as { days: { type: string }[] }
    expect(sent.days).toHaveLength(7)
    expect(sent.days.map((d) => d.type)).toEqual(['train', 'train', 'session', 'train', 'rest', 'session', 'rest'])
    expect(await screen.findByText(/best 42pp/)).toBeInTheDocument()
    expect(localStorage.getItem('tycoon.weekPlan')).toContain('ranked_pack_grind')
  })
})
