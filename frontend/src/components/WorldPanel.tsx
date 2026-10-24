import { useEffect, useState } from 'react'
import { fmt, socialApi, worldApi, type Leaderboard, type NewsItem, type NpcProfile } from '../api'
import { t, tx } from '../i18n'
import { DuelChallenger } from './DuelPanel'
import { MapLeaderboard } from './MapLeaderboard'

const NEWS_ICONS: Record<string, string> = {
  NEW_NUMBER_ONE: '👑',
  TOURNAMENT_WINNER: '🏆',
  TOURNAMENT_WIN: '🏆',
  TOURNAMENT_RESULT: '🎖',
  TOURNAMENT_UPSET: '⚡',
  OWC_SELECTED: '🌍',
  RISING_STAR: '🌟',
  INJURY: '✚',
  HIATUS: '⏸',
  RETIRED: '👋',
  INACTIVE: '💤',
  RETURN: '🔥',
  SNIPED: '🎯',
}

const STATUS_LABEL: Record<string, string> = {
  injured: t('injured'),
  hiatus: t('on hiatus'),
  retired: t('retired'),
  inactive: t('inactive'),
  active: t('active'),
}

function NpcCard({ playerId, npcId, onClose, onChanged }: { playerId: number; npcId: number; onClose: () => void; onChanged?: () => void }) {
  const [npc, setNpc] = useState<NpcProfile | null>(null)
  const [message, setMessage] = useState('')
  const [sent, setSent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    setNpc(null)
    setError(null)
    worldApi.npc(playerId, npcId).then((profile) => {
      if (!cancelled) setNpc(profile)
    }).catch((err: Error) => {
      if (!cancelled) setError(err.message)
    })
    return () => { cancelled = true }
  }, [playerId, npcId])
  if (!npc) return (
    <div className="rounded-lg bg-bg p-3 text-sm" role={error ? 'alert' : 'status'}>
      <button onClick={onClose} aria-label={t('Close')} className="float-right text-muted">✕</button>
      {error ? tx(error) : t('Loading…')}
    </div>
  )
  return (
    <div className="space-y-2 rounded-lg bg-bg p-3 text-sm">
      <div className="flex items-baseline justify-between">
        <div>
          <b>{npc.name}</b> <span className="text-muted">[{npc.country}]</span>
          {npc.kind === 'legend' && <span className="ml-2 rounded bg-amber-500/20 px-1.5 text-xs text-amber-300">{t('legend')}</span>}
        </div>
        <button onClick={onClose} className="text-muted hover:text-white">
          ✕
        </button>
      </div>
      {npc.archetype && <p className="text-xs text-muted">{t('Playstyle')}: <b className="text-white">{t(npc.archetype)}</b></p>}
      {npc.aliases.length > 0 && <p className="text-xs text-muted">{t('aka')} {npc.aliases.join(', ')}</p>}
      {npc.note && <p className="text-xs italic text-muted">{tx(npc.note)}</p>}
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          {t('Rank')} <b>{fmt.rank(npc.rank)}</b>
        </div>
        <div>
          {t('Best')} <b>{fmt.rank(npc.best_rank)}</b>
        </div>
        <div>
          {t('Titles')} <b>{npc.titles}</b>
        </div>
        <div>
          OVR <b>{Math.floor(npc.overall)}</b>
        </div>
        <div>
          {t('PP potential')} <b>{npc.pp_potential == null ? '—' : Math.floor(npc.pp_potential)}</b>
        </div>
        <div>
          {t('Tournament strength')} <b>{npc.tournament_strength == null ? '—' : Math.floor(npc.tournament_strength)}</b>
        </div>
        <div>
          {t('Status')} <b>{STATUS_LABEL[npc.status] ?? npc.status}</b>
        </div>
        <div>
          {t('Form')} <b>{npc.form > 0.5 ? t('hot') : npc.form < -0.5 ? t('cold') : t('normal')}</b>
        </div>
      </div>
      <div className="space-y-1 rounded bg-panel p-2 text-xs">
        <p><span className="text-muted">{t('Best score types')}:</span> {npc.best_score_types?.map((x) => t(x)).join(', ') || '—'}</p>
        <p><span className="text-muted">{t('Peaks')}:</span> {npc.peaks?.map((x) => t(x)).join(', ') || '—'}</p>
        <p><span className="text-muted">{t('Weaknesses')}:</span> {npc.weaknesses?.map((x) => t(x)).join(', ') || '—'}</p>
        <p>
          <span className="text-muted">{t('Matches')}:</span> {npc.match_stats ? t(npc.match_stats.summary ?? '') : '—'}
          {npc.match_stats?.played ? ` (${npc.match_stats.wins}-${npc.match_stats.losses}, ${t('upsets')}: ${npc.match_stats.upset_wins})` : ''}
        </p>
        {Boolean(npc.storyline?.focus) && <p><span className="text-muted">{t('Current focus')}:</span> {t(String(npc.storyline.focus))}</p>}
        {Boolean(npc.storyline?.arc) && <p><span className="text-muted">{t('Career arc')}:</span> {t(String(npc.storyline.arc))} · {t(String(npc.storyline.phase))}</p>}
        {npc.rival && <p><span className="text-muted">{t('Rival')}:</span> {npc.rival.name} ({fmt.rank(npc.rival.rank)})</p>}
      </div>
      <form
        className="flex gap-1"
        onSubmit={async (e) => {
          e.preventDefault()
          if (!message.trim()) return
          try {
            await socialApi.dm(playerId, npc.name, message.trim())
            setMessage('')
            setSent(t('Sent. The reply shows up in the IRC window under DM:{name}.', { name: npc.name }))
          } catch (err) {
            setSent(tx((err as Error).message))
          }
        }}
      >
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          maxLength={500}
          placeholder={t('Message {name}…', { name: npc.name })}
          className="flex-1 rounded bg-panel px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-osu-pink"
        />
        <button className="rounded bg-osu-pink px-2 text-xs font-semibold">{t('DM')}</button>
      </form>
      {sent && <p className="text-xs text-muted">{sent}</p>}
      {npc.status === 'active' && <DuelChallenger playerId={playerId} npcId={npc.id} npcName={npc.name} onPlayed={onChanged} />}
      <div className="grid grid-cols-6 gap-1 text-center text-[10px] text-muted">
        {Object.entries(npc.composites).map(([k, v]) => (
          <div key={k} className="rounded bg-panel p-1">
            <div className="text-sm font-bold text-white">{Math.floor(v)}</div>
            {t(k)}
          </div>
        ))}
      </div>
    </div>
  )
}

interface WorldProps {
  playerId: number
  dateKey: string
  country: string
  onChanged?: () => void
}

export function WorldPanel({ playerId, dateKey, country, onChanged }: WorldProps) {
  const [news, setNews] = useState<NewsItem[]>([])
  const [headlinesOnly, setHeadlinesOnly] = useState(false)
  const [board, setBoard] = useState<Leaderboard | null>(null)
  const [countryOnly, setCountryOnly] = useState(false)
  const [openNpc, setOpenNpc] = useState<number | null>(null)
  const [limit, setLimit] = useState(100)
  const [newsMap, setNewsMap] = useState<number | null>(null)

  useEffect(() => {
    worldApi.news(playerId, headlinesOnly ? 3 : 1).then(setNews)
  }, [playerId, dateKey, headlinesOnly])
  useEffect(() => {
    worldApi.leaderboard(playerId, countryOnly ? country : undefined, limit).then(setBoard)
  }, [playerId, dateKey, countryOnly, country, limit])

  const youInTable = board?.rows.some((r) => r.kind === 'user')

  return (
    <div className="space-y-6">
      <section className="space-y-3 rounded-xl bg-panel p-5">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm uppercase tracking-wider text-muted">{countryOnly ? t('{c} rankings', { c: country }) : t('Global rankings')}</h2>
          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input type="checkbox" checked={countryOnly} onChange={(e) => setCountryOnly(e.target.checked)} className="accent-osu-pink" />
            {t('my country')}
          </label>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted">
          {t('Players shown')}
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} className="rounded bg-bg px-2 py-1">
            {[25, 50, 100, 200, 500, 1000].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          {board && <span>({board.rows.length})</span>}
        </label>
        {openNpc && <NpcCard key={openNpc} playerId={playerId} npcId={openNpc} onClose={() => setOpenNpc(null)} onChanged={onChanged} />}
        <table className="w-full text-sm">
          <tbody>
            {board?.rows.map((r, i) => (
              <tr
                key={`${r.name}-${i}`}
                onClick={() => r.npc_id && setOpenNpc(r.npc_id)}
                className={`${r.kind === 'user' ? 'bg-osu-pink/20' : r.npc_id ? 'cursor-pointer hover:bg-panel-light' : ''}`}
              >
                <td className="w-16 py-1 pl-2 text-muted">{fmt.rank(r.rank)}</td>
                <td className="py-1">
                  <span className={r.kind === 'legend' ? 'text-amber-300' : r.kind === 'user' ? 'font-bold' : ''}>{r.name}</span>{' '}
                  <span className="text-xs text-muted">[{r.country}]</span>
                  {STATUS_LABEL[r.status] && <span className="ml-1 text-xs text-red-400">({STATUS_LABEL[r.status]})</span>}
                </td>
                <td className="py-1 pr-2 text-right">{fmt.pp(r.pp)}</td>
              </tr>
            ))}
            {board?.you && !youInTable && (
              <tr className="bg-osu-pink/20">
                <td className="w-16 py-1 pl-2 text-muted">{fmt.rank(board.you.rank)}</td>
                <td className="py-1 font-bold">
                  {board.you.name} <span className="text-xs font-normal text-muted">[{board.you.country}]</span>
                </td>
                <td className="py-1 pr-2 text-right">{fmt.pp(board.you.pp)}</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="space-y-3 rounded-xl bg-panel p-5">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm uppercase tracking-wider text-muted">{t('News')}</h2>
          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input type="checkbox" checked={headlinesOnly} onChange={(e) => setHeadlinesOnly(e.target.checked)} className="accent-osu-pink" />
            {t('headlines only')}
          </label>
        </div>
        {news.length === 0 && <p className="text-sm text-muted">{t('Nothing yet. The world moves as your calendar does.')}</p>}
        <ul className="space-y-1.5">
          {news.map((n) => (
            <li key={n.id} className={`flex gap-2 text-sm ${n.importance >= 3 ? 'font-semibold' : n.importance === 1 ? 'text-muted' : ''}`}>
              <span className="w-20 shrink-0 text-xs font-normal text-muted">{n.date}</span>
              <span className="w-5 shrink-0 text-center">{NEWS_ICONS[n.type] ?? '•'}</span>
              <span>
                {tx(n.message)}
                {typeof n.data.beatmap_id === 'number' && !n.data.retracted && (
                  <button className="ml-2 text-xs text-osu-pink underline" onClick={() => setNewsMap(Number(n.data.beatmap_id))}>
                    {t('Open map leaderboard')}
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
        {newsMap !== null && <div className="space-y-2 rounded bg-bg p-3">
          <button className="text-xs text-muted" onClick={() => setNewsMap(null)}>{t('Close')}</button>
          <a className="ml-3 text-xs text-osu-pink" href={`https://osu.ppy.sh/beatmaps/${newsMap}`} target="_blank" rel="noreferrer">osu! ↗</a>
          <MapLeaderboard playerId={playerId} beatmapId={newsMap} dateKey={dateKey} />
        </div>}
      </section>
    </div>
  )
}
