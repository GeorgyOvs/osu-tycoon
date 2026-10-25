import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SpendingPanel } from '../components/SpendingPanel'
import type { Spending } from '../api.spending'
import { mockApi } from './setup'

const item = (over: object) => ({
  key: 'gym', icon: '🏋', kind: 'sub', name: 'Gym', description: 'Hands', perk: '-15% RSI risk', price: 20, affordable: true,
  status: 'available', reason: '', cooldown_left: 0, days: 0, choices: [], ...over,
})
const shop = (items: object[], over: Partial<Spending> = {}): Spending =>
  ({
    money: 100, categories: [{ key: 'health', name: 'Health', icon: '💪', items }], subscriptions: [], monthly_total: 0,
    effects: [], owned: [], ...over,
  }) as unknown as Spending

describe('SpendingPanel', () => {
  it('buys an item and refreshes', async () => {
    const calls = mockApi({
      'GET /api/players/1/spending': shop([item({})]),
      'POST /api/players/1/spending/gym/buy': { key: 'gym', price: 20, choice: null, applied: {}, message: 'Bought: Gym ($20).', message_ru: 'Куплено' },
    })
    const onChanged = vi.fn()
    render(<SpendingPanel playerId={1} dateKey="a" onChanged={onChanged} />)
    await userEvent.setup().click(await screen.findByText('Subscribe'))
    expect(await screen.findByText(/Bought: Gym/)).toBeInTheDocument()
    expect(calls.some((c) => c.path.endsWith('/gym/buy'))).toBe(true)
    expect(onChanged).toHaveBeenCalled()
  })

  it('disables what cannot be bought and says why', async () => {
    mockApi({
      'GET /api/players/1/spending': shop([
        item({ key: 'agent', name: 'Agent', status: 'locked', reason: 'Needs a rank of #3,000 or better' }),
        item({ key: 'vacation', name: 'Vacation', kind: 'one_off', price: 500, affordable: false }),
      ]),
    })
    render(<SpendingPanel playerId={1} dateKey="a" onChanged={vi.fn()} />)
    expect(await screen.findByText('Locked')).toBeDisabled()
    expect(screen.getByText('Needs a rank of #3,000 or better')).toBeInTheDocument()
    expect(screen.getByText('Buy')).toBeDisabled()
  })

  it('needs a skill group for coaching and lists subscriptions with a monthly total', async () => {
    const calls = mockApi({
      'GET /api/players/1/spending': shop(
        [item({ key: 'coach_session', kind: 'timed', choices: [{ key: 'aim', label: 'Aim' }, { key: 'reading', label: 'Reading' }] })],
        { subscriptions: [{ key: 'gym', name: 'Gym', price: 20, since: '2014-01-01', months: 3 }], monthly_total: 20 },
      ),
      'POST /api/players/1/spending/coach_session/buy': { key: 'coach_session', price: 30, choice: 'reading', applied: {}, message: 'ok', message_ru: 'ок' },
    })
    const user = userEvent.setup()
    render(<SpendingPanel playerId={1} dateKey="a" onChanged={vi.fn()} />)
    expect(await screen.findByText('$20/mo')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Skill group'), 'reading')
    await user.click(screen.getByText('Buy'))
    expect(calls.find((c) => c.path.endsWith('/coach_session/buy'))?.body).toEqual({ choice: 'reading' })
  })
})
