import { useState } from 'react'
import { fmt, type Score } from '../api'
import { t } from '../i18n'
import { beatmapUrl } from '../links'
import { LeaderboardModal } from './LeaderboardModal'
import { PreviewButton } from './PreviewButton'

const GRADE_STYLE: Record<string, string> = {
  XH: 'text-slate-200', X: 'text-yellow-200', SH: 'text-slate-300', S: 'text-yellow-300', A: 'text-green-400', B: 'text-sky-400',
}

/** One score: click anywhere to open the map's leaderboard. */
export function ScoreRow({
  score,
  extra,
  playerId,
  dateKey,
  grade,
}: {
  score: Score
  extra?: React.ReactNode
  playerId: number
  dateKey: string
  grade?: string
}) {
  const [open, setOpen] = useState(false)
  const url = beatmapUrl(score.beatmap_id)
  const g = grade ?? score.grade
  const title = `${score.artist} - ${score.title} [${score.difficulty_name}]`
  return (
    <>
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen(true)}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setOpen(true)}
        className="flex cursor-pointer items-center gap-3 rounded-lg bg-panel px-3 py-2 hover:bg-panel-light/40"
        title={t('Show the leaderboard of this map')}
      >
        <PreviewButton beatmapsetId={score.beatmapset_id} artist={score.artist} title={score.title} />
        {g && <span className={`w-7 text-center text-lg font-black ${GRADE_STYLE[g] ?? 'text-muted'}`}>{g.replace('X', 'SS').replace('H', '')}</span>}
        <div className="min-w-0 flex-1">
          {url ? (
            <a href={url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="block truncate hover:text-osu-pink">
              {score.artist} - {score.title} <span className="text-muted">[{score.difficulty_name}]</span>
            </a>
          ) : (
            <div className="truncate">
              {score.artist} - {score.title} <span className="text-muted">[{score.difficulty_name}]</span>
            </div>
          )}
          <div className="text-xs text-muted">
            {fmt.stars(score.stars)} · {fmt.acc(score.accuracy)} · x{score.max_combo}
            {score.misses > 0 && <span className="text-red-400"> · {score.misses}❌</span>} · {score.played_on}
          </div>
        </div>
        <span className="rounded bg-panel-light px-2 py-0.5 text-xs font-bold">{fmt.mods(score.mods)}</span>
        <div className="w-24 text-right">
          <div className="font-bold text-osu-pink">{fmt.pp(score.pp)}</div>
          {extra}
        </div>
        <span className="text-xs text-muted" aria-hidden>
          🏆
        </span>
      </div>
      {open && <LeaderboardModal playerId={playerId} beatmapId={score.beatmap_id} title={title} dateKey={dateKey} onClose={() => setOpen(false)} />}
    </>
  )
}
