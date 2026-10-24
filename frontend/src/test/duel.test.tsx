import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DuelChallenger } from '../components/DuelPanel'
import { mockApi } from './setup'

const pool = [
  { slot: 'NM1', stars: 4.1, beatmap_id: 1, title: 'Alpha' },
  { slot: 'NM2', stars: 4.1, beatmap_id: 2, title: 'Beta' },
  { slot: 'HD1', stars: 4.1, beatmap_id: 3, title: 'Gamma' },
  { slot: 'HR1', stars: 4.1, beatmap_id: 4, title: 'Delta' },
  { slot: 'DT1', stars: 4.1, beatmap_id: 5, title: 'Epsilon' },
  { slot: 'TB', stars: 4.35, beatmap_id: 6, title: 'Omega' },
]
const base = {
  id: 7, date: '2016-10-17', opponent: 'Mioto', opponent_country: 'JP', opponent_rank: 1200, kind: 'friendly',
  best_of: 3, bans_per_side: 1, difficulty: 'even', pool, score_user: 0, score_npc: 0, won: null, maps: [],
}

describe('DuelChallenger', () => {
  it('challenges, plans a ban and a pick, plays and shows the result', async () => {
    const onPlayed = vi.fn()
    const calls = mockApi({
      'POST /api/players/1/duels': { ...base, status: 'pending' },
      'POST /api/players/1/duels/7/play': {
        ...base, status: 'played', score_user: 2, score_npc: 1, won: true,
        maps: [
          { slot: 'NM1', picked_by: 'a', score_a: 900000, score_b: 800000, title: 'Alpha', stars: 4.1, players: [] },
          { bans: { a: ['DT1'], b: ['HR1'] } },
        ],
      },
    })
    const user = userEvent.setup()
    render(<DuelChallenger playerId={1} npcId={5} npcName="Mioto" onPlayed={onPlayed} />)

    await user.click(screen.getByText(/Challenge to 1v1/))
    await user.selectOptions(screen.getByLabelText('Format'), '3')
    await user.click(screen.getByText('Send challenge'))
    expect(await screen.findByText(/Mioto accepted/)).toBeInTheDocument()
    expect(calls.at(-1)?.body).toMatchObject({ npc_id: 5, best_of: 3, kind: 'friendly' })

    await user.click(screen.getByText('Epsilon')) // ban mode by default
    await user.click(screen.getByRole('radio', { name: /Pick order/ }))
    await user.click(screen.getByText('Alpha'))
    await user.click(screen.getByText('Play 1v1'))

    expect(await screen.findByText('WIN')).toBeInTheDocument()
    expect(screen.getByText('2–1')).toBeInTheDocument()
    expect(calls.at(-1)?.body).toEqual({ bans: ['DT1'], picks: ['NM1'] })
    await waitFor(() => expect(onPlayed).toHaveBeenCalled())
  })

  it('shows why a challenge was declined', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'Mioto declined' }), { status: 409 })))
    const user = userEvent.setup()
    render(<DuelChallenger playerId={1} npcId={5} npcName="Mioto" />)
    await user.click(screen.getByText(/Challenge to 1v1/))
    await user.click(screen.getByText('Send challenge'))
    expect(await screen.findByText('Mioto declined')).toBeInTheDocument()
  })
})
