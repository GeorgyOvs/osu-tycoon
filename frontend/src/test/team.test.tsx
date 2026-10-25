import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { TeamPanel } from '../components/TeamPanel'
import type { Team, TeamState } from '../api.team'
import { mockApi } from './setup'

const member = (id: number, name: string, role: string) => ({
  npc_id: id, name, country: 'JP', role, bond: 40, rank: 1200 * id, pp: 3000, overall: 50, status: 'active', joined_on: '2016-03-01',
})
const team = (over: Partial<Team> = {}): Team => ({
  id: 3, name: 'Pixel Pact', tag: 'PXP', status: 'active', founded_on: '2016-03-01', chemistry: 40, reputation: 20,
  user_role: 'anchor', channel: '#pxp', size: 2, members: [member(1, 'Mioto', 'leader')], log: [], ready_for_cup: false,
  scrim_today: false, last_scrim: null, cups_won: 0, expires_on: null, invited_by: null,
  perks: { learning_bonus_pct: 0, nerve_bonus_pct: 2.4, sponsor_monthly: 0, followers_weekly: 0 }, ...over,
})
const state = (over: Partial<TeamState> = {}): TeamState => ({
  date: '2016-03-10', team: null, invite: null, history: [], cups: [], can_found: true, found_blocker: null, found_cost: 25,
  limits: { max_size: 5, cup_size: 3, max_scrim_hours: 4 }, ...over,
})

describe('TeamPanel', () => {
  it('founds a team from the form', async () => {
    const calls = mockApi({
      'GET /api/players/1/team': state(),
      'POST /api/players/1/team/found': state({ team: team({ members: [], size: 1 }), can_found: false }),
    })
    const user = userEvent.setup()
    render(<TeamPanel playerId={1} dateKey="a" onChanged={vi.fn()} />)
    await user.type(await screen.findByPlaceholderText('Team name'), 'Pixel Pact')
    await user.type(screen.getByPlaceholderText('Tag'), 'pxp')
    await user.click(screen.getByText('Found'))
    expect(await screen.findByText('Pixel Pact')).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith('/found'))?.body).toEqual({ name: 'Pixel Pact', tag: 'PXP' })
  })

  it('shows an invitation and accepts it', async () => {
    const invite = team({ id: 9, status: 'invited', name: 'Nimbus Crew', tag: 'NIM', invited_by: 'Mioto', expires_on: '2016-04-01' })
    const calls = mockApi({
      'GET /api/players/1/team': state({ invite }),
      'POST /api/players/1/team/invites/9/accept': state({ team: team({ id: 9, name: 'Nimbus Crew' }), can_found: false }),
    })
    const user = userEvent.setup()
    render(<TeamPanel playerId={1} dateKey="a" onChanged={vi.fn()} />)
    await user.click(await screen.findByText('Accept'))
    expect(await screen.findByText('Nimbus Crew')).toBeInTheDocument()
    expect(calls.some((c) => c.path.endsWith('/invites/9/accept'))).toBe(true)
  })

  it('plays a scrim and reports the chemistry change', async () => {
    mockApi({
      'GET /api/players/1/team': state({ team: team(), can_found: false }),
      'POST /api/players/1/team/scrim': {
        message: 'Scrim with Pixel Pact: 2h, chemistry 40 -> 46.', chemistry: 46,
        state: state({ team: team({ chemistry: 46, scrim_today: true }), can_found: false }),
      },
    })
    const user = userEvent.setup()
    render(<TeamPanel playerId={1} dateKey="a" onChanged={vi.fn()} />)
    await user.click(await screen.findByText('Play a scrim'))
    expect(await screen.findByText(/chemistry 40 -> 46/)).toBeInTheDocument()
    expect(screen.getByText('Played today')).toBeDisabled()
  })
})
