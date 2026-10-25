import { useCallback, useEffect, useState } from 'react'
import { api, type RealPlay } from '../api'
import { t } from '../i18n'

/** Hand-played osu!stable scores, pulled from the local client files on demand. */
export function RealPlaysPanel({ playerId }: { playerId: number }) {
  const [plays, setPlays] = useState<RealPlay[]>([])
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => api.listRealPlays(playerId).then(setPlays).catch(() => setPlays([])), [playerId])
  useEffect(() => {
    load()
  }, [load])

  const sync = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await api.syncRealPlays(playerId)
      setNote(
        r.baseline
          ? t('Imported {n} earlier plays as history.').replace('{n}', String(r.imported))
          : r.imported
            ? t('{n} new plays found.').replace('{n}', String(r.imported))
            : t('No new plays.'),
      )
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="space-y-3 rounded-xl bg-panel p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Plays from osu! client')}</h2>
        <button
          onClick={sync}
          disabled={busy}
          className="rounded-lg bg-osu-pink px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? t('Syncing...') : t('Sync with client')}
        </button>
      </div>
      {note && <p className="text-sm text-muted">{note}</p>}
      {error && <p className="text-sm text-red-400">{error}</p>}
      <ul className="space-y-1 text-sm">
        {plays.map((p) => (
          <li key={p.id} className="flex justify-between gap-3">
            <span className="truncate">
              {p.artist} - {p.title} [{p.difficulty_name}] {p.mods && `+${p.mods}`}
            </span>
            <span className="shrink-0 text-muted">
              {p.accuracy.toFixed(2)}% · {p.misses}x · {p.pp.toFixed(0)}pp
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
