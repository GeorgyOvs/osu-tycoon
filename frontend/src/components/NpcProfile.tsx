import { useEffect, useState } from 'react'
import { fmt, starColor } from '../api'
import { searchApi, type Comparison, type NpcOsuProfile, type NpcTopPlay } from '../api.search'
import { GROUP_LABELS } from '../i18n.keys'
import { t, tx } from '../i18n'
import { openDm } from '../npcBus'
import { GeneratedAvatar } from './Avatar'
import { COMPARE_COLORS, CompareChart } from './CompareChart'
import { DuelChallenger } from './DuelPanel'
import { HistoryChart } from './HistoryChart'
import { LeaderboardModal } from './LeaderboardModal'
import { PreviewButton } from './PreviewButton'

export const flag = (cc: string) =>
  /^[A-Z]{2}$/.test(cc) ? String.fromCodePoint(...[...cc].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65)) : '🏳'

const STATUS_STYLE: Record<string, string> = {
  active: 'bg-green-500/20 text-green-300',
  hiatus: 'bg-amber-500/20 text-amber-300',
  injured: 'bg-red-500/20 text-red-300',
  retired: 'bg-slate-500/30 text-slate-300',
}
const STATUS_LABEL: Record<string, string> = {
  active: t('active'),
  hiatus: t('on hiatus'),
  injured: t('injured'),
  retired: t('retired'),
  inactive: t('inactive'),
  restricted: t('restricted'),
}
const KIND_LABEL: Record<string, string> = { legend: t('legend'), procedural: t('player'), real: t('real player') }
const GROUPS = ['aim', 'tapping', 'reading', 'technical', 'mentality', 'physical']

function Big({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="text-2xl font-bold leading-tight">{value}</div>
      {sub && <div className="text-[11px] text-muted">{sub}</div>}
    </div>
  )
}

function PlayRow({ play, playerId, dateKey }: { play: NpcTopPlay; playerId: number; dateKey: string }) {
  const [open, setOpen] = useState(false)
  const title = `${play.artist} - ${play.title} [${play.version}]`
  return (
    <>
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen(true)}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setOpen(true)}
        title={t('Show the leaderboard of this map')}
        className="flex cursor-pointer items-center gap-3 rounded-lg bg-bg px-3 py-1.5 text-sm hover:bg-panel-light/50"
      >
        <PreviewButton beatmapsetId={play.beatmapset_id} artist={play.artist} title={play.title} />
        <div className="min-w-0 flex-1">
          <div className="truncate">
            {play.artist} - {play.title} <span className="text-muted">[{play.version}]</span>
          </div>
          <div className="text-xs text-muted">
            <span style={{ color: starColor(play.stars) }}>{play.stars.toFixed(2)}★</span> · {play.accuracy.toFixed(2)}% · {play.max_combo}x
            {play.misses > 0 && <span className="text-red-400"> · {play.misses}❌</span>} · {play.set_on}
          </div>
        </div>
        <span className="rounded bg-panel-light px-2 py-0.5 text-xs font-bold">{play.mods || 'NM'}</span>
        <span className="w-16 text-right font-bold text-osu-pink">{play.pp ? `${Math.round(play.pp)}pp` : '—'}</span>
      </div>
      {open && <LeaderboardModal playerId={playerId} beatmapId={play.beatmap_id} title={title} dateKey={dateKey} onClose={() => setOpen(false)} />}
    </>
  )
}

function SkillBars({ a, b }: { a: Record<string, number>; b?: Record<string, number> }) {
  return (
    <div className="space-y-1.5">
      {GROUPS.map((g) => (
        <div key={g} className="text-xs">
          <div className="flex justify-between">
            <span className="text-muted">{t(GROUP_LABELS[g] ?? g)}</span>
            <span className="tabular-nums">
              {b ? (
                <>
                  <b style={{ color: COMPARE_COLORS[0] }}>{Math.round(a[g])}</b> · <b style={{ color: COMPARE_COLORS[1] }}>{Math.round(b[g])}</b>
                </>
              ) : (
                Math.round(a[g])
              )}
            </span>
          </div>
          <div className="mt-0.5 space-y-0.5">
            <div className="h-1.5 rounded-full bg-bg">
              <div className="h-full rounded-full" style={{ width: `${Math.min(100, a[g])}%`, background: COMPARE_COLORS[0] }} />
            </div>
            {b && (
              <div className="h-1.5 rounded-full bg-bg">
                <div className="h-full rounded-full" style={{ width: `${Math.min(100, b[g])}%`, background: COMPARE_COLORS[1] }} />
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function CompareView({ playerId, npcId }: { playerId: number; npcId: number }) {
  const [data, setData] = useState<Comparison | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    searchApi.compare(playerId, npcId).then(setData).catch((e: Error) => setError(e.message))
  }, [playerId, npcId])
  if (!data) return <p className="text-sm text-muted">{error ? tx(error) : t('Loading…')}</p>
  const toPoints = (h: Comparison['you']['history']) => h.filter((p) => p.rank != null).map((p) => ({ date: p.date, value: p.rank as number }))
  const h2h = data.head_to_head
  const rows: [string, string, string][] = [
    [t('Global rank'), fmt.rank(data.you.rank), fmt.rank(data.them.rank)],
    [t('Peak rank'), fmt.rank(data.you.peak_rank), fmt.rank(data.them.peak_rank)],
    [t('Performance'), fmt.pp(data.you.pp), fmt.pp(data.them.pp)],
    [t('Accuracy'), fmt.acc(data.you.accuracy ?? 0), data.them.accuracy != null ? fmt.acc(data.them.accuracy) : '—'],
  ]
  return (
    <div className="space-y-4">
      <CompareChart
        label={t('Rank history')}
        series={[
          { name: data.you.name, color: COMPARE_COLORS[0], points: toPoints(data.you.history) },
          { name: data.them.name, color: COMPARE_COLORS[1], points: toPoints(data.them.history) },
        ]}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-muted">
              <th className="text-left font-normal" />
              <th className="text-right font-semibold" style={{ color: COMPARE_COLORS[0] }}>
                {data.you.name}
              </th>
              <th className="text-right font-semibold" style={{ color: COMPARE_COLORS[1] }}>
                {data.them.name}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, a, b]) => (
              <tr key={label}>
                <td className="py-0.5 text-muted">{label}</td>
                <td className="py-0.5 text-right tabular-nums">{a}</td>
                <td className="py-0.5 text-right tabular-nums">{b}</td>
              </tr>
            ))}
            {Object.keys(h2h).length > 0 && (
              <tr>
                <td className="py-0.5 text-muted">{t('Head to head')}</td>
                <td colSpan={2} className="py-0.5 text-right tabular-nums">
                  {t('matches')} {h2h.matches_won ?? 0}–{h2h.matches_lost ?? 0} · {t('snipes')} {h2h.snipes_for ?? 0}–{h2h.snipes_against ?? 0}
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <SkillBars a={data.you.composites} b={data.them.composites} />
      </div>
    </div>
  )
}

/** Another player's page in the osu!-website style, as a full-width overlay. */
export function NpcProfile({
  playerId,
  npcId,
  dateKey,
  initialView = 'profile',
  onClose,
}: {
  playerId: number
  npcId: number
  dateKey: string
  initialView?: 'profile' | 'compare'
  onClose: () => void
}) {
  const [page, setPage] = useState<NpcOsuProfile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState(initialView)
  const [chart, setChart] = useState<'rank' | 'pp'>('rank')

  useEffect(() => {
    setPage(null)
    searchApi.npc(playerId, npcId).then(setPage).catch((e: Error) => setError(e.message))
  }, [playerId, npcId, dateKey])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/70 p-4" onClick={onClose}>
      <div className="mx-auto max-w-5xl space-y-4 pb-10" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={page?.name ?? t('Player')}>
        <div className="flex justify-end">
          <button onClick={onClose} className="rounded-full bg-panel px-3 py-1 text-sm text-muted hover:text-white" aria-label={t('Close')}>
            ✕
          </button>
        </div>
        {!page ? (
          <p className="rounded-xl bg-panel p-5 text-sm text-muted">{error ? tx(error) : t('Loading…')}</p>
        ) : (
          <>
            <section className="overflow-hidden rounded-xl bg-panel">
              <div className={`h-20 bg-gradient-to-r ${page.kind === 'legend' ? 'from-amber-500/60 via-orange-700/50 to-rose-800/60' : 'from-sky-600/60 via-indigo-700/50 to-fuchsia-800/60'}`} />
              <div className="-mt-10 flex flex-wrap items-end gap-4 px-5 pb-4">
                <div className="rounded-full ring-4 ring-panel">
                  <GeneratedAvatar seed={page.name} size={88} />
                </div>
                <div className="min-w-0 flex-1 pb-1">
                  <h2 className="truncate text-2xl font-bold">{page.name}</h2>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
                    <span>
                      {flag(page.country)} {page.country}
                    </span>
                    <span className="rounded bg-panel-light px-1.5 text-xs">{KIND_LABEL[page.kind] ?? page.kind}</span>
                    <span className={`rounded px-1.5 text-xs ${STATUS_STYLE[page.status] ?? 'bg-panel-light'}`}>
                      {STATUS_LABEL[page.status] ?? page.status}
                      {page.away_until ? ` · ${page.away_until}` : ''}
                    </span>
                    <span>{t('Joined {d}', { d: page.joined })}</span>
                    <span>{tx(page.archetype)}</span>
                    {page.titles > 0 && <span>🏆 × {page.titles}</span>}
                  </div>
                  {page.aliases.length > 0 && <div className="text-xs text-muted">{t('also known as')} {page.aliases.join(', ')}</div>}
                </div>
                <div className="flex flex-wrap gap-2 pb-1">
                  <button onClick={() => { openDm(page.name); onClose() }} className="rounded-full bg-panel-light px-3 py-1.5 text-sm hover:bg-osu-pink">
                    ✉ {t('Message')}
                  </button>
                  <button
                    onClick={() => setView(view === 'compare' ? 'profile' : 'compare')}
                    className={`rounded-full px-3 py-1.5 text-sm ${view === 'compare' ? 'bg-osu-pink' : 'bg-panel-light hover:bg-osu-pink'}`}
                  >
                    ⇄ {t('Compare')}
                  </button>
                </div>
              </div>
              {page.note && <p className="border-t border-panel-light px-5 py-2 text-sm text-muted">{page.note}</p>}
              {(page.relationship.rival || page.relationship.teammate || page.relationship.mentor) && (
                <div className="flex flex-wrap gap-2 border-t border-panel-light px-5 py-2 text-xs">
                  {page.relationship.rival && (
                    <span className="rounded bg-red-500/20 px-2 py-0.5 text-red-300">
                      {t('Your rival')} · {t('heat {n}', { n: Math.round(page.relationship.rival.heat) })} · {t('matches')}{' '}
                      {page.relationship.rival.record.matches_won ?? 0}–{page.relationship.rival.record.matches_lost ?? 0}
                    </span>
                  )}
                  {page.relationship.teammate && <span className="rounded bg-purple-500/20 px-2 py-0.5 text-purple-300">{t('Teammate')} · {page.relationship.team}</span>}
                  {page.relationship.mentor && <span className="rounded bg-sky-500/20 px-2 py-0.5 text-sky-300">{t('Your mentor')}</span>}
                </div>
              )}
            </section>

            {view === 'compare' ? (
              <section className="rounded-xl bg-panel p-5">
                <CompareView playerId={playerId} npcId={page.id} />
              </section>
            ) : (
              <>
                <section className="space-y-4 rounded-xl bg-panel p-5">
                  <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                    <Big
                      label={t('Global ranking')}
                      value={fmt.rank(page.global_rank)}
                      sub={page.peak_rank ? t('peak #{n} · {d}', { n: page.peak_rank.toLocaleString('en-US'), d: page.peak_date ?? '' }) : undefined}
                    />
                    <Big label={t('Country ranking')} value={fmt.rank(page.country_rank)} sub={`${flag(page.country)} ${page.country}`} />
                    <Big label={t('Performance')} value={fmt.pp(page.pp)} />
                    <Big label={t('Overall')} value={Math.round(page.overall).toString()} />
                  </div>
                  <div>
                    <div className="mb-1 flex gap-1 text-xs">
                      {(['rank', 'pp'] as const).map((k) => (
                        <button
                          key={k}
                          onClick={() => setChart(k)}
                          className={`rounded-full px-3 py-0.5 ${chart === k ? 'bg-panel-light text-white ring-1 ring-osu-pink' : 'text-muted hover:text-white'}`}
                        >
                          {k === 'rank' ? t('Rank history') : t('pp history')}
                        </button>
                      ))}
                    </div>
                    {chart === 'rank' ? (
                      <HistoryChart
                        points={page.history.filter((h) => h.rank != null).map((h) => ({ date: h.date, value: h.rank as number }))}
                        kind="rank"
                        label={t('Global rank')}
                      />
                    ) : (
                      <HistoryChart points={page.history.filter((h) => h.pp > 0).map((h) => ({ date: h.date, value: h.pp }))} kind="pp" label={t('Performance')} />
                    )}
                  </div>
                </section>

                <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                  <section className="space-y-3 rounded-xl bg-panel p-5">
                    <h3 className="text-sm uppercase tracking-wider text-muted">{t('Skills')}</h3>
                    <SkillBars a={page.composites} />
                    <div className="text-xs text-muted">
                      {t('Strong at')}: {page.strengths.map((g) => t(GROUP_LABELS[g] ?? g)).join(', ')} · {t('Weak at')}:{' '}
                      {page.weaknesses.map((g) => t(GROUP_LABELS[g] ?? g)).join(', ')}
                    </div>
                    {page.status === 'active' && (
                      <DuelChallenger playerId={playerId} npcId={page.id} npcName={page.name} rival={!!page.relationship.rival} />
                    )}
                  </section>
                  <section className="space-y-2 rounded-xl bg-panel p-5">
                    <h3 className="text-sm uppercase tracking-wider text-muted">{t('Recent activity')}</h3>
                    {page.news.length === 0 && <p className="text-sm text-muted">{t('Nothing notable lately.')}</p>}
                    <ul className="space-y-1 text-sm">
                      {page.news.map((n, i) => (
                        <li key={i}>
                          <span className="text-xs text-muted">{n.date}</span> {tx(n.message)}
                        </li>
                      ))}
                    </ul>
                  </section>
                </div>

                <section className="space-y-2">
                  <h3 className="text-sm uppercase tracking-wider text-muted">{t('Best performance')}</h3>
                  {page.top_plays.length === 0 && <p className="text-sm text-muted">{t('No scores on the boards you have seen yet.')}</p>}
                  {page.top_plays.map((p) => (
                    <PlayRow key={p.beatmap_id} play={p} playerId={playerId} dateKey={dateKey} />
                  ))}
                </section>
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
