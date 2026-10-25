import { useEffect, useState } from 'react'
import { t } from '../i18n'
import { MapLeaderboard } from './MapLeaderboard'
import { PreviewButton } from './PreviewButton'

/** The map's leaderboard in an overlay, so it can be opened from any list without losing your place. */
export function LeaderboardModal({
  playerId,
  beatmapId,
  title,
  dateKey,
  onClose,
  beatmapsetId,
}: {
  playerId: number
  beatmapId: number
  title: string
  dateKey: string
  onClose: () => void
  beatmapsetId?: number | null
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-16" onClick={onClose}>
      <div
        role="dialog"
        aria-label={title}
        className="w-full max-w-3xl space-y-3 rounded-xl bg-panel p-4 shadow-2xl ring-1 ring-panel-light"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          {beatmapsetId ? <PreviewButton beatmapsetId={beatmapsetId} title={title} /> : null}
          <h3 className="min-w-0 flex-1 font-semibold">🏆 {title}</h3>
          <button onClick={onClose} className="rounded px-2 text-muted hover:text-white" aria-label={t('Close')}>
            ✕
          </button>
        </div>
        <MapLeaderboard playerId={playerId} beatmapId={beatmapId} dateKey={dateKey} />
      </div>
    </div>
  )
}

/** A small 🏆 button that opens the leaderboard overlay. */
export function BoardButton({
  playerId,
  beatmapId,
  title,
  dateKey,
  label,
}: {
  playerId: number
  beatmapId: number
  title: string
  dateKey: string
  label?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          setOpen(true)
        }}
        title={t('Show the leaderboard of this map')}
        className="shrink-0 rounded-full bg-panel-light px-2 py-1 text-xs hover:bg-osu-pink"
      >
        🏆{label ? ` ${label}` : ''}
      </button>
      {open && <LeaderboardModal playerId={playerId} beatmapId={beatmapId} title={title} dateKey={dateKey} onClose={() => setOpen(false)} />}
    </>
  )
}
