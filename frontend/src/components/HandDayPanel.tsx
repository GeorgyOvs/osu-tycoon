import { useCallback, useEffect, useState } from 'react'
import { api, type HandDay } from '../api'
import { t, tx } from '../i18n'

/** The day being played by hand in the client: time spent so far, and closing it so the calendar moves on. */
export function HandDayPanel({ playerId, onFinished }: { playerId: number; onFinished: () => void }) {
  const [day, setDay] = useState<HandDay | null>(null)
  const [summary, setSummary] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => api.getHandDay(playerId).then(setDay).catch(() => setDay(null)), [playerId])
  useEffect(() => {
    load()
    const timer = window.setInterval(load, 10_000)
    return () => window.clearInterval(timer)
  }, [load])

  const finish = async () => {
    setBusy(true)
    setError(null)
    try {
      const done = await api.finishHandDay(playerId)
      setSummary([...done.events.map((e) => tx(e.message)), ...done.news.map((n) => tx(n))])
      await load()
      onFinished()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!day) return null
  const minutes = Math.round(day.hours * 60)
  const limit = Math.round(day.limit_hours * 60)

  return (
    <section className="space-y-3 rounded-xl bg-panel p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Today by hand')}</h2>
        <button
          onClick={finish}
          disabled={busy || day.attempts === 0}
          className="rounded-lg bg-osu-pink px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {t('Finish the day')}
        </button>
      </div>
      {day.blocked ? (
        <p className="text-sm text-red-400">{tx(day.blocked)}</p>
      ) : (
        <>
          <p className="text-sm">
            {t('{n} attempts, {m} of {l} minutes')
              .replace('{n}', String(day.attempts))
              .replace('{m}', String(minutes))
              .replace('{l}', String(limit))}
          </p>
          <div className="h-1.5 overflow-hidden rounded bg-bg">
            <div className="h-full bg-osu-pink" style={{ width: `${Math.min(100, (100 * minutes) / Math.max(1, limit))}%` }} />
          </div>
          <p className="text-xs text-muted">
            {t('Every attempt in the client costs time and energy. The longer you play, the worse your character plays. The day closes by itself at the limit.')}
          </p>
        </>
      )}
      {summary.length > 0 && (
        <ul className="space-y-0.5 text-xs text-muted">
          {summary.slice(0, 8).map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      )}
      {error && <p className="text-sm text-red-400">{tx(error)}</p>}
    </section>
  )
}
