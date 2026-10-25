import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NotificationCenter } from '../components/NotificationCenter'
import type { NotificationItem } from '../api.notify'
import { mockApi } from './setup'

const reg: NotificationItem = {
  id: 'reg:5:open', kind: 'registration', date: '2016-03-02', message: 'Registration is open: Spring Open 2016 (until 2016-03-20).',
  tab: 'tournaments', priority: 2, action: { type: 'register', tournament_id: 5, name: 'Spring Open 2016' },
}
const old: NotificationItem = { ...reg, id: 'we:1', kind: 'tournament', message: 'Old news', action: null }

describe('NotificationCenter', () => {
  beforeEach(() => localStorage.clear())

  it('marks what is already there as seen, toasts new items once, and registers from the toast', async () => {
    let feed: NotificationItem[] = [old]
    const calls = mockApi({
      'GET /api/players/1/notifications': () => feed,
      'POST /api/players/1/tournaments/5/register': { id: 5 },
    })
    const onChanged = vi.fn()
    const onOpenTab = vi.fn()
    const { rerender } = render(
      <NotificationCenter playerId={1} refreshKey="a" chatSummary={[]} chatUnread={new Set()} onOpenTab={onOpenTab} onChanged={onChanged} />,
    )
    await act(async () => {})
    expect(screen.queryByText('Old news')).toBeNull() // first visit: no flood of toasts

    feed = [reg, old]
    rerender(<NotificationCenter playerId={1} refreshKey="b" chatSummary={[]} chatUnread={new Set()} onOpenTab={onOpenTab} onChanged={onChanged} />)
    const toast = await screen.findByText(/Registration is open/)
    expect(toast).toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Register' }))
    expect(calls.some((c) => c.method === 'POST' && c.path === '/api/players/1/tournaments/5/register')).toBe(true)
    expect(onChanged).toHaveBeenCalled()

    rerender(<NotificationCenter playerId={1} refreshKey="c" chatSummary={[]} chatUnread={new Set()} onOpenTab={onOpenTab} onChanged={onChanged} />)
    await act(async () => {})
    expect(screen.queryByText(/Registration is open/)).toBeNull() // shown once

    await user.click(screen.getByRole('button', { name: 'Notifications' }))
    await user.click(await screen.findByText('Old news'))
    expect(onOpenTab).toHaveBeenCalledWith('tournaments')
  })
})
