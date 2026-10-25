import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MentorPanel } from '../components/MentorPanel'
import type { MentorOverview } from '../api.mentors'
import { mockApi } from './setup'

const mind = { confidence: { jumps: 0.5, streams: -0.4 }, fear: [{ npc_id: 4, name: 'Rafis', value: 0.6 }], big_stage: 0.7, big_stage_maps: 10 }
const overview = (over: Partial<MentorOverview> = {}): MentorOverview => ({
  available: true, reason: null, mentor: null, log: [], mind,
  candidates: [{ npc_id: 9, name: 'Mioto', country: 'JP', rank: 120, overall: 62.3, focus: 'aim', chance: 41, blocked: null }],
  ...over,
})

describe('MentorPanel', () => {
  it('shows the mind section and asks a candidate', async () => {
    const calls = mockApi({
      'GET /api/players/1/mentor': overview(),
      'POST /api/players/1/mentor/ask': { ...overview(), accepted: false, message: 'Mioto turned you down: too busy right now.' },
    })
    const user = userEvent.setup()
    render(<MentorPanel playerId={1} dateKey="a" onChanged={vi.fn()} />)
    expect(await screen.findByText(/Rattled by Rafis/)).toBeInTheDocument()
    expect(screen.getByText(/70%/)).toBeInTheDocument()
    await user.click(await screen.findByText('Ask'))
    expect(await screen.findByText(/turned you down/)).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith('/mentor/ask'))?.body).toEqual({ npc_id: 9 })
  })

  it('runs a session with the current mentor', async () => {
    const mentor = {
      npc_id: 9, name: 'Mioto', country: 'JP', group: 'aim', since: '2016-03-01', bond: 34, interest: 78, sessions: 1,
      last_session: '2016-03-05', boost: 1.3, boost_until: '2016-03-12', boost_active: true, rank: 120, overall: 62.3, gap: 12,
    }
    const calls = mockApi({
      'GET /api/players/1/mentor': overview({ mentor, candidates: [] }),
      'POST /api/players/1/mentor/session': { action: { events: [], deltas: {} }, advice: 'Warm up before ranked, always.', mentor },
    })
    const user = userEvent.setup()
    const changed = vi.fn()
    render(<MentorPanel playerId={1} dateKey="a" onChanged={changed} />)
    await user.click(await screen.findByText('Train with the mentor (a day)'))
    expect(await screen.findByText(/Warm up before ranked/)).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith('/mentor/session'))?.body).toEqual({ hours: 2 })
    expect(changed).toHaveBeenCalled()
  })
})
