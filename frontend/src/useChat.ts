import { useCallback, useEffect, useMemo, useState } from 'react'
import { socialApi, type ChannelSummary } from './api'

const POLL_MS = 5000

/** Conversation list + unread dots for the messenger. "Seen" is the last line id you have looked at, per channel. */
export function useChat(playerId: number) {
  const key = `tycoon.chatSeen.${playerId}`
  const [summary, setSummary] = useState<ChannelSummary[]>([])
  const [seen, setSeen] = useState<Record<string, number>>(() => {
    try {
      return JSON.parse(localStorage.getItem(key) ?? '{}')
    } catch {
      return {}
    }
  })

  const refresh = useCallback(() => socialApi.summary(playerId).then(setSummary).catch(() => undefined), [playerId])
  useEffect(() => {
    void refresh()
    const timer = setInterval(refresh, POLL_MS)
    return () => clearInterval(timer)
  }, [refresh])

  const markSeen = useCallback(
    (channel: string, id: number) =>
      setSeen((cur) => {
        if ((cur[channel] ?? 0) >= id) return cur
        const next = { ...cur, [channel]: id }
        try {
          localStorage.setItem(key, JSON.stringify(next))
        } catch {
          /* ignore */
        }
        return next
      }),
    [key],
  )

  const unread = useMemo(
    () =>
      new Set(
        summary
          .filter((c) => c.last_id > (seen[c.channel] ?? 0) && c.last_source !== 'user' && c.total > 0)
          // first visit: don't light up every public channel, only private messages
          .filter((c) => c.channel.startsWith('DM:') || c.channel in seen)
          .map((c) => c.channel),
      ),
    [summary, seen],
  )
  return { summary, refresh, unread, markSeen }
}
