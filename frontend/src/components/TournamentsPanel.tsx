import { useCallback, useEffect, useState } from 'react'
import { t, tx } from '../i18n'
import { DuelHistory } from './DuelPanel'
import { DraftRoom } from './DraftRoom'
import { MapHint } from './MapHint'
import { slotMods } from '../api.hints'
import { LiveMatch, WatchReplay, focusPlayer } from './ReplayViewer'
import {
  starColor,
  worldApi,
  type MatchCommentary,
  type MatchMap,
  type PoolEntry,
  type TournamentDetail,
  type TournamentList,
  type TournamentMatch,
  type TournamentSummary,
} from '../api'

const TIER_LABEL: Record<string, string> = {
  community6: t('6 digit'),
  community: t('5 digit'),
  open: t('Open'),
  major: t('Major'),
  owc: t('World Cup'),
  clan: t('Clan Cup'),
}

function rankRange(tour: TournamentSummary) {
  if (tour.tier === 'owc') return t("country's top players")
  if (tour.tier === 'clan') return t('teams of three')
  if (tour.rank_max >= 10_000_000) return `#${tour.rank_min.toLocaleString('en-US')}+`
  return `#${tour.rank_min.toLocaleString('en-US')}–${tour.rank_max.toLocaleString('en-US')}`
}

/** Map-by-map breakdown of a played match (tournament or 1v1). */
export function MatchMaps({
  maps,
  names,
  commentary,
}: {
  maps: MatchMap[]
  names: [string, string]
  commentary?: MatchCommentary | null
}) {
  const [a, b] = [{ name: names[0] }, { name: names[1] }]
  const [live, setLive] = useState(false)
  const played = maps.filter((m): m is MatchMap & { slot: string } => !!m.slot)
  const bans = maps.find((m) => m.bans)?.bans
  if (played.length === 0) return null
  const watchable = !!commentary && played.some((m) => focusPlayer(m)?.replay)
  return (
    <div className="space-y-1.5">
      {watchable && !live && (
        <button onClick={() => setLive(true)} className="rounded bg-osu-pink px-3 py-1 text-xs font-semibold hover:bg-osu-pink-dark">
          ▶ {t('Watch the match')}
        </button>
      )}
      {watchable && live && commentary && (
        <LiveMatch maps={maps} commentary={commentary} names={names} onClose={() => setLive(false)} />
      )}
      {bans && (
        <div className="text-xs text-muted">
          {t('Bans')}: {a?.name} {bans.a.join(', ') || '—'} · {b?.name} {bans.b.join(', ') || '—'}
        </div>
      )}
      {played.map((m, i) => {
        const aWon = m.winner ? m.winner === 'a' : (m.score_a ?? 0) > (m.score_b ?? 0)
        return (
          <div key={i} className="space-y-1 rounded bg-bg p-2 text-xs">
            <div className="flex items-center gap-2">
              <span className="w-10 font-bold">{m.slot}</span>
              <span className="min-w-0 flex-1 truncate">
                {m.title}{' '}
                {m.stars != null && <span style={{ color: starColor(m.stars) }}>{m.stars.toFixed(2)}★</span>}
              </span>
              {m.tie && (
                <span className="rounded bg-amber-500/20 px-1.5 text-amber-300" title={t('Equal scores: the map is decided by accuracy, then misses, then a sudden-death replay.')}>
                  {t('Tie')}: {m.tie === 'accuracy' ? t('accuracy') : m.tie === 'misses' ? t('misses') : t('sudden death')}
                </span>
              )}
              <span className="text-muted">{m.picked_by === 'tb' ? t('tiebreaker') : t('{name} pick', { name: (m.picked_by === 'a' ? a?.name : b?.name) ?? '?' })}</span>
            </div>
            <div className="flex gap-3">
              {(['a', 'b'] as const).map((side) => (
                <div key={side} className={`flex-1 rounded p-1.5 ${(side === 'a') === aWon ? 'bg-green-900/30' : 'bg-panel'}`}>
                  <div className="font-bold">{(side === 'a' ? m.score_a : m.score_b)?.toLocaleString('en-US')}</div>
                  {m.players
                    ?.filter((p) => p.side === side)
                    .map((p, j) => (
                      <div key={j} className="text-muted">
                        <span className={p.kind === 'user' ? 'text-osu-pink' : ''}>{p.name}</span>: {p.accuracy.toFixed(2)}% · {p.combo}/
                        {p.max_combo}x · {p.misses}❌{p.choked && ` · ${t('choked')}`}
                        {p.kind === 'user' && p.key_moments.map((k, n) => <div key={n}>• {tx(k)}</div>)}
                        <WatchReplay
                          replay={p.replay}
                          commentary={p === focusPlayer(m) ? commentary?.maps[i] : undefined}
                          summary={{ passed: p.passed ?? true, grade: p.grade, accuracy: p.accuracy, misses: p.misses, combo: p.combo, maxCombo: p.max_combo }}
                        />
                      </div>
                    ))}
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function Bracket({ detail }: { detail: TournamentDetail }) {
  const entries = new Map(detail.entries.map((e) => [e.id, e]))
  const [open, setOpen] = useState<number | null>(null)
  const stages: [string, TournamentMatch[]][] = []
  for (const m of detail.matches) {
    const group = stages.find(([s]) => s === m.stage)
    if (group) group[1].push(m)
    else stages.push([m.stage, [m]])
  }
  const name = (id: number | null) => (id ? entries.get(id)?.name ?? '?' : t('TBD'))
  return (
    <div className="space-y-3">
      {stages.map(([stage, matches]) => (
        <div key={stage}>
          <div className="mb-1 text-xs uppercase tracking-wider text-muted">
            {tx(stage)} · BO{matches[0].first_to * 2 - 1} · {matches[0].due}
          </div>
          <div className="grid gap-1 sm:grid-cols-2">
            {matches.map((m) => (
              <div key={m.id} className={`rounded text-xs ${m.is_user_match ? 'ring-1 ring-osu-pink' : ''}`}>
                <button
                  onClick={() => setOpen(open === m.id ? null : m.id)}
                  className="flex w-full items-center gap-2 rounded bg-panel-light/50 px-2 py-1 text-left hover:bg-panel-light"
                >
                  <span className={`flex-1 truncate ${m.winner === m.entry_a && m.winner ? 'font-bold' : 'text-muted'}`}>{name(m.entry_a)}</span>
                  <span className="font-mono">
                    {m.winner ? `${m.score_a}–${m.score_b}` : 'vs'}
                  </span>
                  <span className={`flex-1 truncate text-right ${m.winner === m.entry_b && m.winner ? 'font-bold' : 'text-muted'}`}>{name(m.entry_b)}</span>
                </button>
                {open === m.id && (
                  <div className="p-1">
                    <MatchMaps maps={m.maps} names={[name(m.entry_a), name(m.entry_b)]} commentary={m.commentary} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

interface Props {
  playerId: number
  dateKey: string
  onChanged: () => void
}

export function TournamentsPanel({ playerId, dateKey, onChanged }: Props) {
  const [list, setList] = useState<TournamentList | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [detail, setDetail] = useState<TournamentDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reload = useCallback(() => worldApi.tournaments(playerId).then(setList), [playerId])
  useEffect(() => {
    void reload()
  }, [reload, dateKey])
  useEffect(() => {
    if (selected == null) return
    worldApi.tournament(playerId, selected).then(setDetail)
  }, [playerId, selected, dateKey])

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      await reload()
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const groups: [string, TournamentSummary[]][] = list
    ? [
        [t('Ongoing'), list.tournaments.filter((tour) => tour.status === 'ongoing')],
        [t('Upcoming'), list.tournaments.filter((tour) => tour.status === 'upcoming')],
        [t('Recent results'), list.tournaments.filter((tour) => tour.status === 'finished').reverse()],
      ]
    : []

  return (
    <div className="space-y-6">
      {error && <p className="text-sm text-red-400">{tx(error)}</p>}
      {groups.map(([label, ts]) =>
        ts.length === 0 ? null : (
          <section key={label} className="space-y-2 rounded-xl bg-panel p-5">
            <h2 className="text-sm uppercase tracking-wider text-muted">{label}</h2>
            {ts.map((tour) => (
              <div
                key={tour.id}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${selected === tour.id ? 'bg-panel-light' : 'bg-bg'}`}
              >
                <button onClick={() => setSelected(selected === tour.id ? null : tour.id)} className="min-w-0 flex-1 text-left">
                  <div className="truncate font-semibold">
                    {tour.name}{' '}
                    <span className="rounded bg-panel-light px-1.5 text-[10px] font-normal uppercase text-muted">{TIER_LABEL[tour.tier] ?? tour.tier}</span>
                  </div>
                  <div className="text-xs text-muted">
                    {tour.start_date} · {rankRange(tour)} · {tour.size} {tour.team_size > 1 ? t('teams') : t('players')} · {t('from')}{' '}
                    <span style={{ color: starColor(tour.base_stars) }}>{tour.base_stars.toFixed(1)}★</span>
                    {tour.winner && <> · 🏆 {tour.winner}</>}
                    {tour.user_placement && <span className="text-osu-pink"> · {t('you')}: {tx(tour.user_placement)}</span>}
                  </div>
                </button>
                {tour.user_registered && tour.status !== 'finished' && <span className="text-xs text-green-400">{t('registered')}</span>}
                {tour.can_register && (
                  <button
                    disabled={busy}
                    onClick={() => act(() => worldApi.register(playerId, tour.id))}
                    className="rounded-full bg-osu-pink px-3 py-1 text-xs font-semibold hover:bg-osu-pink-dark disabled:opacity-50"
                  >
                    {t('Register')}
                  </button>
                )}
                {!tour.can_register && tour.status === 'upcoming' && !tour.user_registered && tour.tier !== 'owc' && (
                  <span className="text-xs text-muted">
                    {!tour.eligible ? t('rank not eligible') : t('reg. opens {d}', { d: tour.registration_opens })}
                  </span>
                )}
              </div>
            ))}
          </section>
        ),
      )}

      {detail && selected === detail.id && (
        <section className="space-y-3 rounded-xl bg-panel p-5">
          <div className="flex items-baseline justify-between">
            <h2 className="font-semibold">{detail.name}</h2>
            <button onClick={() => setSelected(null)} className="text-muted hover:text-white">
              ✕
            </button>
          </div>
          <PoolsView playerId={playerId} detail={detail} onPracticed={onChanged} />
          {detail.pools.qualifiers && <QualifierTable rows={detail.pools.qualifiers} />}
          {detail.status === 'upcoming' ? (
            <p className="text-sm text-muted">{t('The bracket is drawn on {d}.', { d: detail.start_date })}</p>
          ) : (
            <>
              <div className="flex flex-wrap gap-1 text-xs">
                {detail.entries
                  .filter((e) => e.placement && ['1st', '2nd', '3rd', '4th'].includes(e.placement))
                  .sort((x, y) => (x.placement ?? '').localeCompare(y.placement ?? ''))
                  .map((e) => (
                    <span key={e.id} className={`rounded px-2 py-0.5 ${e.includes_user ? 'bg-osu-pink/30' : 'bg-bg'}`}>
                      {tx(e.placement)}: {e.name}
                    </span>
                  ))}
              </div>
              <Bracket detail={detail} />
            </>
          )}
        </section>
      )}

      <DuelHistory playerId={playerId} dateKey={dateKey} />
    </div>
  )
}

function PoolsView({ playerId, detail, onPracticed }: { playerId: number; detail: TournamentDetail; onPracticed: () => void }) {
  const [hours, setHours] = useState(2)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const weeks = Object.keys(detail.pools)
    .filter((k) => k !== 'qualifiers' && detail.pools[k].some((s) => s.beatmap_id))
    .sort()
  if (weeks.length === 0) {
    return detail.user_registered ? (
      <p className="text-xs text-muted">{t('Map pools are released a week before each stage.')}</p>
    ) : null
  }
  return (
    <div className="space-y-2">
      {weeks.map((w) => (
        <details key={w} className="rounded bg-bg p-2 text-xs" open={w === weeks[weeks.length - 1]}>
          <summary className="cursor-pointer text-muted">{t('Week {w} pool', { w })}</summary>
          <div className="mt-2 grid gap-0.5">
            {detail.pools[w].map((s) => (
              <div key={s.slot} className="flex gap-2">
                <span className="w-10 font-bold">{s.slot}</span>
                <MapHint playerId={playerId} beatmapId={s.beatmap_id} mods={slotMods(s.slot)} className="min-w-0 flex-1 cursor-help truncate">
                  {s.title}
                </MapHint>
                {s.stars != null && <span style={{ color: starColor(s.stars) }}>{s.stars.toFixed(1)}★</span>}
              </div>
            ))}
          </div>
          {detail.user_registered && detail.status !== 'finished' && (
            <div className="mt-2 flex items-center gap-2">
              <input type="range" min={0.5} max={6} step={0.5} value={hours} onChange={(e) => setHours(Number(e.target.value))} className="accent-osu-pink" />
              <span>{hours}{t('h')}</span>
              <button
                disabled={busy}
                onClick={async () => {
                  setBusy(true)
                  setMsg(null)
                  try {
                    const r = await worldApi.practicePool(playerId, detail.id, Number(w), hours)
                    setMsg(t('Practised {n}h on the pool. Map knowledge carries into the match.', { n: r.hours.toFixed(1) }))
                    onPracticed()
                  } catch (e) {
                    setMsg(tx((e as Error).message))
                  } finally {
                    setBusy(false)
                  }
                }}
                className="rounded-full bg-osu-pink px-3 py-1 font-semibold hover:bg-osu-pink-dark disabled:opacity-50"
              >
                {t('Practise this pool (ends the day)')}
              </button>
            </div>
          )}
          {msg && <p className="mt-1 text-muted">{msg}</p>}
        </details>
      ))}
    </div>
  )
}

function QualifierTable({ rows }: { rows: PoolEntry[] }) {
  const [open, setOpen] = useState(false)
  const shown = open ? rows : rows.filter((r, i) => i < 8 || r.kind === 'user')
  return (
    <div className="rounded bg-bg p-2 text-xs">
      <div className="mb-1 text-muted">{t('Qualifiers')}</div>
      {shown.map((r) => (
        <div key={r.seed} className={`flex gap-2 ${r.kind === 'user' ? 'font-semibold text-osu-pink' : ''}`}>
          <span className="w-8">#{r.seed}</span>
          <span className="flex-1 truncate">
            {r.name} [{r.country}]
          </span>
          <span className="font-mono">{r.score?.toLocaleString('en-US')}</span>
        </div>
      ))}
      <button onClick={() => setOpen((o) => !o)} className="mt-1 text-muted hover:text-white">
        {open ? t('less') : t('all {n}', { n: rows.length })}
      </button>
    </div>
  )
}

interface BannerProps {
  playerId: number
  list: TournamentList | null
  onPlayed: () => void
}

/** Shown on every tab while a tournament match blocks the calendar. */
export function MatchBanner({ playerId, list, onPlayed }: BannerProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [names, setNames] = useState<[string, string] | null>(null)
  const [room, setRoom] = useState(false)
  const pending = list?.pending_match
  const tid = list?.pending_tournament_id

  useEffect(() => {
    if (!pending || !tid) return
    worldApi.tournament(playerId, tid).then((d) => {
      const n = (id: number | null) => d.entries.find((e) => e.id === id)?.name ?? '?'
      setNames([n(pending.entry_a), n(pending.entry_b)])
    })
  }, [playerId, pending, tid])

  if (!pending || !tid || !list) return null
  const today = pending.due <= list.date
  return (
    <div className={`rounded-xl p-4 text-sm ${today ? 'bg-osu-pink/20 ring-1 ring-osu-pink' : 'bg-panel'}`}>
      <div className="flex items-center gap-3">
        <span className="text-2xl">⚔</span>
        <div className="flex-1">
          <b>{tx(pending.stage)}</b> (BO{pending.first_to * 2 - 1}): {names ? `${names[0]} vs ${names[1]}` : '…'}
          <div className="text-xs text-muted">{today ? t('Match day! The calendar waits until you play.') : t('Scheduled for {d}', { d: pending.due })}</div>
        </div>
        {today && (
          <div className="flex flex-wrap gap-2">
            <button
              disabled={busy}
              onClick={() => setRoom((v) => !v)}
              className="rounded-full bg-osu-pink px-5 py-2 font-semibold hover:bg-osu-pink-dark disabled:opacity-50"
            >
              {room ? t('Draft room') + ' ▾' : t('Open the draft room')}
            </button>
            <button
              disabled={busy}
              onClick={async () => {
                setBusy(true)
                setError(null)
                try {
                  await worldApi.playMatch(playerId, tid, pending.id, { bans: [], picks: [] })
                  onPlayed()
                } catch (e) {
                  setError(tx((e as Error).message))
                } finally {
                  setBusy(false)
                }
              }}
              className="rounded-full bg-panel-light px-4 py-2 text-xs font-semibold hover:bg-osu-pink disabled:opacity-50"
            >
              {busy ? t('Playing…') : t('Auto (AI plays my side)')}
            </button>
          </div>
        )}
      </div>
      {today && room && <DraftRoom playerId={playerId} tournamentId={tid} matchId={pending.id} onPlayed={onPlayed} />}
      {error && <p className="mt-2 text-red-400">{error}</p>}
    </div>
  )
}
