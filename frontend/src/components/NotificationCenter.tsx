import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { worldApi, type ChannelSummary } from '../api'
import { notifyApi, type NotificationItem } from '../api.notify'
import { t, tx } from '../i18n'

const POLL_MS = 20_000
const TOAST_MS = 6_000
const MAX_TOASTS = 4
const KEEP = 400

const ICON: Record<string, string> = {
  snipe: '🎯',
  top_play: '⭐',
  milestone: '📈',
  rank: '📉',
  match: '⚔',
  decision: '❔',
  registration: '📝',
  tournament: '🏆',
  team: '👥',
  achievement: '🏅',
  goal: '✅',
  integrity: '⚠',
  legacy: '📜',
  dm: '✉',
}

function load(key: string): string[] | null {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as string[]) : null
  } catch {
    return null
  }
}

function save(key: string, ids: Set<string>) {
  try {
    localStorage.setItem(key, JSON.stringify([...ids].slice(-KEEP)))
  } catch {
    /* storage unavailable */
  }
}

/** Toasts for new things plus a 🔔 with the recent list. Each item id is shown as a toast once. */
export function NotificationCenter({
  playerId,
  refreshKey,
  chatSummary,
  chatUnread,
  onOpenTab,
  onChanged,
}: {
  playerId: number
  refreshKey: string
  chatSummary: ChannelSummary[]
  chatUnread: Set<string>
  onOpenTab: (tab: string) => void
  onChanged: () => void
}) {
  const seenKey = `tycoon.notify.seen.${playerId}`
  const readKey = `tycoon.notify.read.${playerId}`
  const [server, setServer] = useState<NotificationItem[]>([])
  const [read, setRead] = useState<Set<string>>(() => new Set(load(readKey) ?? []))
  const [toasts, setToasts] = useState<NotificationItem[]>([])
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const seen = useRef<Set<string> | null>(null)
  const loaded = useRef(false)

  const dms = useMemo<NotificationItem[]>(
    () =>
      chatSummary
        .filter((c) => c.channel.startsWith('DM:') && chatUnread.has(c.channel))
        .map((c) => ({
          id: `dm:${c.channel}:${c.last_id}`,
          kind: 'dm',
          date: c.last_date,
          message: t('New message from {name}', { name: c.channel.slice(3) }),
          tab: 'chat',
          priority: 2,
          action: null,
        })),
    [chatSummary, chatUnread],
  )
  const items = useMemo(() => [...dms, ...server].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : b.priority - a.priority)), [dms, server])

  const refresh = useCallback(
    () =>
      notifyApi
        .list(playerId)
        .then((rows) => {
          loaded.current = true
          setServer(rows)
        })
        .catch(() => undefined),
    [playerId],
  )
  useEffect(() => {
    void refresh()
    const timer = setInterval(refresh, POLL_MS)
    return () => clearInterval(timer)
  }, [refresh, refreshKey])

  // New ids become toasts; on the very first visit everything already there is just marked as seen.
  useEffect(() => {
    if (!loaded.current) return
    if (seen.current === null) {
      const stored = load(seenKey)
      seen.current = new Set(stored ?? [])
      if (stored === null) {
        items.forEach((i) => seen.current?.add(i.id))
        save(seenKey, seen.current)
        return
      }
    }
    const fresh = items.filter((i) => !seen.current?.has(i.id))
    if (fresh.length === 0) return
    fresh.forEach((i) => seen.current?.add(i.id))
    save(seenKey, seen.current)
    setToasts((cur) => [...[...fresh].sort((a, b) => b.priority - a.priority), ...cur].slice(0, MAX_TOASTS))
  }, [items, seenKey])

  useEffect(() => {
    if (toasts.length === 0) return
    const timer = setTimeout(() => setToasts((cur) => cur.slice(0, -1)), TOAST_MS)
    return () => clearTimeout(timer)
  }, [toasts])

  const markRead = (ids: string[]) =>
    setRead((cur) => {
      const next = new Set(cur)
      ids.forEach((id) => next.add(id))
      save(readKey, next)
      return next
    })

  const openItem = (item: NotificationItem) => {
    markRead([item.id])
    setToasts((cur) => cur.filter((x) => x.id !== item.id))
    setOpen(false)
    onOpenTab(item.tab)
  }

  const register = async (item: NotificationItem) => {
    if (!item.action) return
    setBusy(item.action.tournament_id)
    setError(null)
    try {
      await worldApi.register(playerId, item.action.tournament_id)
      markRead([item.id])
      setToasts((cur) => cur.filter((x) => x.id !== item.id))
      onChanged()
      void refresh()
    } catch (e) {
      setError(tx((e as Error).message))
    } finally {
      setBusy(null)
    }
  }

  const unread = items.filter((i) => !read.has(i.id))
  const recent = items.slice(0, 30)

  const row = (item: NotificationItem, toast: boolean) => (
    <div
      key={`${toast ? 't' : 'l'}-${item.id}`}
      role="button"
      tabIndex={0}
      onClick={() => openItem(item)}
      onKeyDown={(e) => e.key === 'Enter' && openItem(item)}
      className={`flex cursor-pointer gap-2 rounded-lg px-3 py-2 text-sm hover:bg-panel-light ${
        toast ? 'bg-panel shadow-xl ring-1 ring-panel-light' : read.has(item.id) ? 'opacity-60' : ''
      }`}
    >
      <span aria-hidden>{ICON[item.kind] ?? '•'}</span>
      <div className="min-w-0 flex-1">
        <div className="break-words">{tx(item.message)}</div>
        <div className="text-[10px] text-muted">{item.date}</div>
        {item.action?.type === 'register' && (
          <button
            disabled={busy === item.action.tournament_id}
            onClick={(e) => {
              e.stopPropagation()
              void register(item)
            }}
            className="mt-1 rounded-full bg-osu-pink px-3 py-0.5 text-xs font-semibold hover:bg-osu-pink-dark disabled:opacity-50"
          >
            {t('Register')}
          </button>
        )}
      </div>
      {toast && (
        <button
          aria-label={t('Close')}
          onClick={(e) => {
            e.stopPropagation()
            setToasts((cur) => cur.filter((x) => x.id !== item.id))
          }}
          className="self-start text-muted hover:text-white"
        >
          ✕
        </button>
      )}
    </div>
  )

  return (
    <>
      <div className="relative">
        <button
          onClick={() => setOpen((o) => !o)}
          title={t('Notifications')}
          aria-label={t('Notifications')}
          className="relative rounded-full bg-panel-light px-2.5 py-1 text-sm hover:bg-osu-pink"
        >
          🔔
          {unread.length > 0 && (
            <span className="absolute -top-1 -right-1 rounded-full bg-osu-pink px-1.5 text-[10px] font-bold">{Math.min(99, unread.length)}</span>
          )}
        </button>
        {open && (
          <div className="absolute right-0 z-50 mt-2 w-80 rounded-xl bg-panel p-2 shadow-2xl ring-1 ring-panel-light">
            <div className="flex items-center justify-between px-2 pb-1">
              <span className="text-xs uppercase tracking-wider text-muted">{t('Notifications')}</span>
              {unread.length > 0 && (
                <button onClick={() => markRead(items.map((i) => i.id))} className="text-xs text-muted hover:text-white">
                  {t('Mark all as read')}
                </button>
              )}
            </div>
            {error && <p className="px-2 text-xs text-red-400">{error}</p>}
            <div className="max-h-96 space-y-0.5 overflow-y-auto">
              {recent.length === 0 && <p className="px-2 py-3 text-sm text-muted">{t('Nothing new.')}</p>}
              {recent.map((i) => row(i, false))}
            </div>
          </div>
        )}
      </div>
      {toasts.length > 0 && (
        <div className="fixed top-4 right-4 z-[60] w-80 space-y-2" aria-live="polite">
          {toasts.map((i) => row(i, true))}
        </div>
      )}
    </>
  )
}
