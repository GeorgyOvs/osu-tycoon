import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { DraftSlot, DraftState } from '../api'
import { DraftRoom } from '../components/DraftRoom'
import { mockApi } from './setup'

const slot = (name: string, over: Partial<DraftSlot> = {}): DraftSlot => ({
  slot: name, family: name.slice(0, 2), mods: name.startsWith('NM') ? 'NM' : name.slice(0, 2), stars: 5.4, title: `Map ${name}`,
  beatmap_id: 100, state: 'open', by: null, legal: true, ...over,
})

const state = (over: Partial<DraftState> = {}): DraftState => ({
  match_id: 7, tournament_id: 3, stage: 'Round of 16', first_to: 5, finished: false, user_side: 'a',
  names: { a: 'Me', b: 'Rival' }, seeds: { a: 3, b: 9 }, score: { a: 0, b: 0 },
  turn: { kind: 'ban', side: 'a', mine: true }, legal: ['NM1', 'HD1'],
  slots: [slot('NM1'), slot('HD1'), slot('DT1', { state: 'banned', by: 'b', legal: false })],
  bans: { a: [], b: ['DT1'] }, first_ban: 'b', first_pick: 'a', bans_per_side: 2,
  log: [{ kind: 'ban', side: 'b', slot: 'DT1', who: 'Rival', mine: false }], maps: [],
  warmup: { used: false, available: true }, ...over,
})

describe('DraftRoom', () => {
  it('shows what the opponent already took and lets you act on your turn', async () => {
    const after = state({
      turn: { kind: 'ban', side: 'a', mine: true }, legal: ['HD1'],
      slots: [slot('NM1', { state: 'banned', by: 'a', legal: false }), slot('HD1'), slot('DT1', { state: 'banned', by: 'b', legal: false })],
      bans: { a: ['NM1'], b: ['DT1'] },
    })
    const calls = mockApi({
      'GET /api/players/1/tournaments/3/matches/7/draft': state(),
      'POST /api/players/1/tournaments/3/matches/7/draft/act': after,
    })
    const user = userEvent.setup()
    render(<DraftRoom playerId={1} tournamentId={3} matchId={7} onPlayed={vi.fn()} />)
    expect(await screen.findByText('Your turn: ban a map')).toBeInTheDocument()
    expect(screen.getByText('🚫 banned by Rival')).toBeInTheDocument() // the opponent's ban is visible before you choose
    await user.click(screen.getByLabelText('ban NM1'))
    expect(calls.find((c) => c.path.endsWith('/draft/act'))?.body).toEqual({ slot: 'NM1' })
    expect(await screen.findByText('🚫 banned by Me')).toBeInTheDocument()
  })

  it('does not let you click a taken map and reports the final result', async () => {
    const onPlayed = vi.fn()
    mockApi({
      'GET /api/players/1/tournaments/3/matches/7/draft': state({
        finished: true, score: { a: 5, b: 2 }, turn: { kind: 'done', side: null, mine: false }, legal: [],
        slots: [slot('NM1', { state: 'played', by: 'a', winner: 'a', score_a: 900, score_b: 800, legal: false }),
          slot('DT1', { state: 'banned', by: 'b', legal: false })],
      }),
    })
    const user = userEvent.setup()
    render(<DraftRoom playerId={1} tournamentId={3} matchId={7} onPlayed={onPlayed} />)
    expect(await screen.findByText('You win 5–2')).toBeInTheDocument()
    expect(screen.queryByLabelText('ban DT1')).toBeNull()
    expect(screen.queryByText('Warm up (30 min)')).toBeNull()
    await user.click(screen.getByText('Continue'))
    expect(onPlayed).toHaveBeenCalled()
  })

  it('warms up once and then disables the button', async () => {
    const calls = mockApi({
      'GET /api/players/1/tournaments/3/matches/7/draft': state(),
      'POST /api/players/1/tournaments/3/matches/7/draft/warmup': state({ warmup: { used: true, available: false } }),
    })
    const user = userEvent.setup()
    render(<DraftRoom playerId={1} tournamentId={3} matchId={7} onPlayed={vi.fn()} />)
    await user.click(await screen.findByText('Warm up (30 min)', { exact: false }))
    expect(calls.some((c) => c.path.endsWith('/draft/warmup'))).toBe(true)
    expect(await screen.findByText('Warmed up: a bit more form and nerve for this match', { exact: false })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Warmed up/ })).toBeDisabled()
  })
})
