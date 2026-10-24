import { useEffect, useState } from 'react'
import { leaderboardApi, type MapLeaderboard as Board } from '../api'
import { t, tx } from '../i18n'

const KIND_STYLE: Record<string, string> = {
  user: 'bg-osu-pink/20 font-semibold',
  legend: 'text-amber-300',
  anchor: 'text-sky-300',
  npc: '',
}

export function MapLeaderboard({ playerId, beatmapId, dateKey }: { playerId: number; beatmapId: number; dateKey: string }) {
  const [board, setBoard] = useState<Board | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    let cancelled = false
    setBoard(null)
    setError(null)
    leaderboardApi
      .map(playerId, beatmapId)
      .then((b) => !cancelled && setBoard(b))
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [playerId, beatmapId, dateKey])

  if (error) return <p className="text-xs text-red-400">{tx(error)}</p>
  if (!board) return <p className="text-xs text-muted">{t('Loading the leaderboard…')}</p>

  const rows = expanded ? board.entries : board.entries.slice(0, 10)
  const you = board.entries.find((e) => e.kind === 'user')
  if (!expanded && you && !rows.includes(you)) rows.push(you)

  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-xs text-muted">
        <span className="uppercase tracking-wider">{t('Leaderboard')} · {board.date}</span>
        <span>{board.user_rank ? t('you: #{n}', { n: board.user_rank }) : t('no score yet')}</span>
      </div>
      {board.entries.length === 0 && <p className="text-xs text-muted">{t('Nobody has set a score here yet. Be the first.')}</p>}
      <table className="w-full text-xs">
        <tbody>
          {rows.map((e) => (
            <tr key={`${e.kind}-${e.name}-${e.rank}`} className={KIND_STYLE[e.kind]}>
              <td className="w-8 py-0.5 text-muted">#{e.rank}</td>
              <td className="truncate py-0.5">
                {e.name} <span className="text-muted">[{e.country}]</span>
                {e.source && (
                  <a href={e.source} target="_blank" rel="noreferrer" title={t('Real historical score')} className="ml-1">
                    ↗
                  </a>
                )}
              </td>
              <td className="py-0.5 text-right font-mono">{e.score.toLocaleString('en-US')}</td>
              <td className="w-12 py-0.5 text-right">{e.mods || 'NM'}</td>
              <td className="w-14 py-0.5 text-right">{e.accuracy.toFixed(2)}%</td>
              <td className="w-16 py-0.5 text-right">
                {e.max_combo}x{e.misses > 0 && <span className="text-red-400"> {e.misses}❌</span>}
              </td>
              <td className="w-12 py-0.5 text-right text-osu-pink">{Math.round(e.pp)}pp</td>
              <td className="w-20 py-0.5 text-right text-muted">{e.set_on}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {Boolean(board.record_history?.length) && <div className="space-y-1 rounded bg-panel p-2">
        <p className="text-xs text-muted">{t('Announced records (pp at the time of the play)')}</p>
        {board.record_history?.map((r, i) => <p key={i} className="text-xs">
          <b>{r.name}</b> · {r.set_on} · +{r.mods || 'NM'} · {r.accuracy.toFixed(2)}% · {r.max_combo}x · {r.misses}xMiss
          {' · '}<b className="text-osu-pink">{r.pp.toFixed(2)}pp</b>
        </p>)}
      </div>}
      {board.entries.length > 10 && (
        <button onClick={() => setExpanded((v) => !v)} className="text-xs text-muted hover:text-white">
          {expanded ? t('Show top 10') : t('Show all {n}', { n: board.entries.length })}
        </button>
      )}
    </div>
  )
}
