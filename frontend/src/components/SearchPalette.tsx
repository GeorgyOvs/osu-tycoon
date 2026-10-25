import { useEffect, useMemo, useRef, useState } from 'react'
import { starColor } from '../api'
import { searchApi, type SearchMap, type SearchPlayer } from '../api.search'
import { t, tx } from '../i18n'
import { openNpc } from '../npcBus'
import { GeneratedAvatar } from './Avatar'
import { LeaderboardModal } from './LeaderboardModal'
import { flag } from './NpcProfile'
import { PreviewButton } from './PreviewButton'

type Item =
  | { kind: 'player'; player: SearchPlayer }
  | { kind: 'map'; map: SearchMap; diff: SearchMap['diffs'][number] }

/** Ctrl/Cmd+K: find a map (as ranked by the in-game date) or a player of this world. */
export function SearchPalette({ playerId, dateKey, onClose }: { playerId: number; dateKey: string; onClose: () => void }) {
  const [q, setQ] = useState('')
  const [result, setResult] = useState<{ players: SearchPlayer[]; maps: SearchMap[] }>({ players: [], maps: [] })
  const [active, setActive] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [board, setBoard] = useState<{ id: number; setId: number; title: string } | null>(null)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => input.current?.focus(), [])
  useEffect(() => {
    if (q.trim().length < 2) {
      setResult({ players: [], maps: [] })
      return
    }
    let cancelled = false
    const timer = setTimeout(() => {
      searchApi
        .search(playerId, q)
        .then((r) => {
          if (!cancelled) {
            setResult(r)
            setActive(0)
            setError(null)
          }
        })
        .catch((e: Error) => !cancelled && setError(e.message))
    }, 180)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [playerId, q])

  const items: Item[] = useMemo(
    () => [
      ...result.players.map((player) => ({ kind: 'player' as const, player })),
      ...result.maps.flatMap((map) => map.diffs.slice(0, 3).map((diff) => ({ kind: 'map' as const, map, diff }))),
    ],
    [result],
  )

  const choose = (item: Item) => {
    if (item.kind === 'player') {
      openNpc({ id: item.player.id })
      onClose()
    } else {
      setBoard({ id: item.diff.beatmap_id, setId: item.map.beatmapset_id, title: `${item.map.artist} - ${item.map.title} [${item.diff.version}]` })
    }
  }

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') onClose()
    else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => Math.min(items.length - 1, a + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(0, a - 1))
    } else if (e.key === 'Enter' && items[active]) {
      e.preventDefault()
      choose(items[active])
    }
  }

  if (board) {
    return <LeaderboardModal playerId={playerId} beatmapId={board.id} beatmapsetId={board.setId} title={board.title} dateKey={dateKey} onClose={() => setBoard(null)} />
  }

  let index = -1
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-20" onClick={onClose}>
      <div className="w-full max-w-xl overflow-hidden rounded-xl bg-panel shadow-2xl ring-1 ring-panel-light" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={t('Search')}>
        <div className="flex items-center gap-2 border-b border-panel-light px-3">
          <span aria-hidden>🔍</span>
          <input
            ref={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
            placeholder={t('Search maps and players…')}
            aria-label={t('Search')}
            className="min-w-0 flex-1 bg-transparent py-3 text-sm outline-none"
          />
          <kbd className="rounded bg-bg px-1.5 text-[10px] text-muted">Esc</kbd>
        </div>
        <div className="max-h-[60vh] overflow-y-auto p-2">
          {error && <p className="p-2 text-sm text-red-400">{tx(error)}</p>}
          {q.trim().length >= 2 && items.length === 0 && !error && <p className="p-2 text-sm text-muted">{t('Nothing found.')}</p>}
          {q.trim().length < 2 && <p className="p-2 text-xs text-muted">{t('Type a map, artist, mapper or player name. ↑↓ to move, Enter to open.')}</p>}
          {result.players.length > 0 && <h3 className="px-2 pt-1 text-[10px] uppercase tracking-wider text-muted">{t('Players')}</h3>}
          {result.players.map((p) => {
            index += 1
            const i = index
            return (
              <button
                key={`p${p.id}`}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose({ kind: 'player', player: p })}
                className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm ${active === i ? 'bg-panel-light' : ''}`}
              >
                <GeneratedAvatar seed={p.name} size={26} />
                <span className="min-w-0 flex-1 truncate">
                  {p.name} <span className="text-muted">{flag(p.country)}</span>
                  {p.kind === 'legend' && <span className="ml-1 rounded bg-amber-500/20 px-1 text-[10px] text-amber-300">{t('legend')}</span>}
                </span>
                <span className="text-xs text-muted">{p.rank ? `#${p.rank.toLocaleString('en-US')}` : tx(p.status)}</span>
              </button>
            )
          })}
          {result.maps.length > 0 && <h3 className="px-2 pt-2 text-[10px] uppercase tracking-wider text-muted">{t('Maps')}</h3>}
          {result.maps.map((m) => (
            <div key={`m${m.beatmapset_id}`} className="flex items-center gap-2 rounded-lg px-2 py-1.5">
              <PreviewButton beatmapsetId={m.beatmapset_id} artist={m.artist} title={m.title} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm">
                  {m.artist} - {m.title} <span className="text-xs text-muted">· {m.creator} · {m.ranked_date}</span>
                </div>
                <div className="flex flex-wrap gap-1 pt-0.5">
                  {m.diffs.slice(0, 3).map((d) => {
                    index += 1
                    const i = index
                    return (
                      <button
                        key={d.beatmap_id}
                        onMouseEnter={() => setActive(i)}
                        onClick={() => choose({ kind: 'map', map: m, diff: d })}
                        title={t('Show the leaderboard of this map')}
                        className={`rounded px-1.5 py-0.5 text-xs ${active === i ? 'bg-osu-pink' : 'bg-bg hover:bg-panel-light'}`}
                      >
                        <span style={{ color: active === i ? undefined : starColor(d.stars) }}>{d.stars.toFixed(2)}★</span> {d.version}
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
