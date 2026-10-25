import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AudioProvider } from '../audio'
import { CompareChart } from '../components/CompareChart'
import { SearchPalette } from '../components/SearchPalette'
import { OPEN_NPC } from '../npcBus'
import { mockApi } from './setup'

describe('search palette', () => {
  it('finds a player and opens their profile with the keyboard', async () => {
    mockApi({
      'GET /api/players/1/search': {
        players: [{ id: 7, name: 'Cookiezi', country: 'KR', kind: 'legend', status: 'active', rank: 1, pp: 9000 }],
        maps: [{ beatmapset_id: 3, artist: 'xi', title: 'FREEDOM DiVE', creator: 'Nakagawa', ranked_date: '2012-06-01',
                 play_count: 1000, diffs: [{ beatmap_id: 30, version: 'FOUR DIMENSIONS', stars: 7.1 }] }],
      },
    })
    const opened = vi.fn()
    window.addEventListener(OPEN_NPC, (e) => opened((e as CustomEvent).detail))
    const onClose = vi.fn()
    render(
      <AudioProvider>
        <SearchPalette playerId={1} dateKey="x" onClose={onClose} />
      </AudioProvider>,
    )
    await userEvent.type(screen.getByRole('textbox'), 'cook')
    expect(await screen.findByText('Cookiezi')).toBeInTheDocument()
    expect(screen.getByText(/FOUR DIMENSIONS/)).toBeInTheDocument()
    await userEvent.keyboard('{Enter}')
    await waitFor(() => expect(opened).toHaveBeenCalledWith({ id: 7 }))
    expect(onClose).toHaveBeenCalled()
  })
})

describe('compare chart', () => {
  it('draws both series with a legend and end labels', () => {
    render(
      <CompareChart
        label="Rank history"
        series={[
          { name: 'Me', color: '#e8579e', points: [{ date: '2016-01-01', value: 50000 }, { date: '2016-06-01', value: 9000 }] },
          { name: 'Rival', color: '#3a94dc', points: [{ date: '2016-01-01', value: 20000 }, { date: '2016-06-01', value: 12000 }] },
        ]}
      />,
    )
    expect(screen.getAllByText('Me').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('Rival').length).toBeGreaterThanOrEqual(2)
  })
})
