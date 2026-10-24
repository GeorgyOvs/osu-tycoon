import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { formatLength, fmt, starColor } from '../api'
import { MapLeaderboard } from '../components/MapLeaderboard'
import { PlayerSelect } from '../components/PlayerSelect'
import { QuickSession } from '../components/QuickSession'
import { WorldPanel } from '../components/WorldPanel'
import { mockApi } from './setup'

describe('NPC profile compatibility', () => {
  const routes = {
    'GET /api/players/1/news': [],
    'GET /api/players/1/leaderboard': {
      date: '2017-01-01', you: null,
      rows: [{ rank: 2, name: 'Rafis', country: 'PL', pp: 13000, kind: 'legend', npc_id: 7, status: 'active' }],
    },
  }

  it('opens a profile returned by an older running backend', async () => {
    mockApi({ ...routes, 'GET /api/players/1/npcs/7': {
      id: 7, name: 'Rafis', country: 'PL', kind: 'legend', status: 'active', overall: 94,
      composites: { aim: 98 }, form: 0, pp: 13000, rank: 2, best_rank: 1, titles: 0,
      away_until: null, note: '', aliases: [], archetype: 'all-rounder',
    } })
    render(<WorldPanel playerId={1} dateKey="x" country="RU" />)
    await userEvent.click(await screen.findByText('Rafis'))
    expect(await screen.findByText('all-rounder')).toBeInTheDocument()
    expect(screen.getByText('94')).toBeInTheDocument()
    expect(screen.getByText('98')).toBeInTheDocument()
    expect(screen.getByText(/PP potential/)).toBeInTheDocument()
  })

  it('shows a load error and lets the user close the card', async () => {
    mockApi(routes)
    render(<WorldPanel playerId={1} dateKey="x" country="RU" />)
    await userEvent.click(await screen.findByText('Rafis'))
    expect(await screen.findByRole('alert')).toHaveTextContent('no mock for GET /api/players/1/npcs/7')
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('opens the exact beatmap leaderboard referenced by a record announcement', async () => {
    const calls = mockApi({ ...routes,
      'GET /api/players/1/news': [{ id: 3, date: '2024-01-01', type: 'FIRST_1000PP',
        message: 'Fictional player | Actual song | 1001pp', importance: 3, data: { beatmap_id: 987 } }],
      'GET /api/players/1/beatmaps/987/leaderboard': {
        beatmap_id: 987, date: '2024-01-01', user_rank: null, entries: [],
      },
    })
    render(<WorldPanel playerId={1} dateKey="x" country="RU" />)
    await userEvent.click(await screen.findByRole('button', { name: 'Open map leaderboard' }))
    await screen.findByText('Nobody has set a score here yet. Be the first.')
    expect(calls.some((c) => c.path === '/api/players/1/beatmaps/987/leaderboard')).toBe(true)
  })
})

describe('formatting helpers', () => {
  it('formats pp, ranks, mods and lengths', () => {
    expect(fmt.pp(538.4)).toBe('538pp')
    expect(fmt.rank(null)).toBe('—')
    expect(fmt.rank(12345)).toBe('#12,345')
    expect(fmt.mods('')).toBe('NM')
    expect(formatLength(125)).toBe('2:05')
  })

  it('colours stars along the osu! spectrum', () => {
    expect(starColor(1.5)).not.toBe(starColor(7))
    expect(starColor(9)).toBe(starColor(10))
  })
})

describe('PlayerSelect', () => {
  it('enforces the build budget and submits unlimited perks only after opting in', async () => {
    const calls = mockApi({
      'GET /api/players': [],
      'GET /api/players/creation-options': {
        budget: 4, presets: { farmer: { label: 'Farmer', perks: ['aim'] } }, conflicts: [],
        perks: {
          aim: { label: 'Aim talent', cost: 3, description: 'Learn aim faster' },
          speed: { label: 'Speed talent', cost: 3, description: 'Learn speed faster' },
        },
      },
      'POST /api/players': { id: 42 },
    })
    render(<PlayerSelect onSelect={() => {}} />)
    await userEvent.type(screen.getByPlaceholderText('Username'), 'Builder')
    await screen.findByRole('option', { name: 'Farmer' })
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Character preset' }), 'farmer')
    expect(screen.getByRole('checkbox', { name: /Aim talent/ })).toBeChecked()
    await userEvent.click(screen.getByRole('checkbox', { name: /Speed talent/ }))
    expect(screen.getByRole('button', { name: /start career/i })).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: /Unbalanced character/ }))
    await userEvent.click(screen.getByRole('button', { name: /start career/i }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({
      preset: 'custom', perks: ['aim', 'speed'], unbalanced: true,
    })
  })

  it('creates a career with the chosen age and selects it', async () => {
    const calls = mockApi({
      'GET /api/players': [],
      'POST /api/players': (body: unknown) => ({ id: 42, ...(body as object) }),
    })
    let selected: number | null = null
    render(<PlayerSelect onSelect={(id) => (selected = id)} />)
    await userEvent.type(screen.getByPlaceholderText('Username'), 'Tester')
    await userEvent.click(screen.getByRole('button', { name: /start career/i }))
    await waitFor(() => expect(selected).toBe(42))
    const create = calls.find((c) => c.method === 'POST')!
    expect(create.body).toMatchObject({ name: 'Tester', country: 'RU', age: 15, gender: 'unspecified' })
  })
})

describe('QuickSession', () => {
  it('sends the preset, hours and the stream flag', async () => {
    const calls = mockApi({
      'GET /api/players/1/presets': [
        { key: 'farm', label: 'Farm at your level', description: 'farm', mods: 'NM', available: true },
        { key: 'doubletime', label: 'DT session', description: 'dt', mods: 'DT', available: false },
      ],
      'POST /api/players/1/sessions/auto': { date: '2016-01-01', hours: 2, plays: [], training: {}, events: [], deltas: {} },
    })
    let played = false
    render(<QuickSession playerId={1} dateKey="x" disabledReason={null} onPlayed={() => (played = true)} />)
    expect(await screen.findByText('DT session')).toBeInTheDocument()
    expect(screen.getByText('DT session').closest('button')).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: /play \(ends the day\)/i }))
    await waitFor(() => expect(played).toBe(true))
    const auto = calls.find((c) => c.path.endsWith('/sessions/auto'))!
    expect(auto.body).toEqual({ preset: 'farm', hours: 2, stream: true })
  })

  it('explains why playing is blocked', async () => {
    mockApi({ 'GET /api/players/1/presets': [] })
    render(<QuickSession playerId={1} dateKey="x" disabledReason="Forced hiatus: no playing" onPlayed={() => {}} />)
    expect(await screen.findByRole('button', { name: 'Forced hiatus: no playing' })).toBeDisabled()
  })
})

describe('MapLeaderboard', () => {
  const entry = (rank: number, name: string, kind: string, score: number) => ({
    rank, kind, name, country: 'KR', mods: 'HD', score, accuracy: 99.1, max_combo: 900, misses: 0, pp: 400,
    set_on: '2014-01-01', npc_id: null, source: kind === 'anchor' ? 'https://example.org' : null,
  })

  it('shows the board, your position and links real scores to their source', async () => {
    mockApi({
      'GET /api/players/1/beatmaps/9/leaderboard': {
        beatmap_id: 9, date: '2016-01-01', user_rank: 12,
        entries: [entry(1, 'Cookiezi', 'legend', 100_000_000), entry(2, 'RealGuy', 'anchor', 90_000_000),
          ...Array.from({ length: 9 }, (_, i) => entry(i + 3, `npc${i}`, 'npc', 80_000_000 - i)),
          entry(12, 'Me', 'user', 1_000)],
      },
    })
    render(<MapLeaderboard playerId={1} beatmapId={9} dateKey="x" />)
    expect(await screen.findByText(/Cookiezi/)).toBeInTheDocument()
    expect(screen.getByText('you: #12')).toBeInTheDocument()
    expect(screen.getByText(/^Me/)).toBeInTheDocument() // shown even outside the top 10
    expect(screen.getByTitle('Real historical score')).toHaveAttribute('href', 'https://example.org')
  })
})
