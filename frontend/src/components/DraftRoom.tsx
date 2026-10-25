import { useCallback, useEffect, useRef, useState } from 'react'
import { starColor, worldApi, type DraftLogLine, type DraftSlot, type DraftState, type MatchMap } from '../api'
import { t, tx } from '../i18n'
import { MapHint } from './MapHint'
import { WatchReplay } from './ReplayViewer'

const FAMILIES = ['NM', 'HD', 'HR', 'DT', 'TB']
const MOD_BADGE: Record<string, string> = { NM: 'bg-slate-600', HD: 'bg-yellow-700', HR: 'bg-red-700', DT: 'bg-sky-700', TB: 'bg-fuchsia-700' }

const hintMods = (mods: string) => (mods === 'NM' ? '' : mods)

function Tile({
  slot,
  names,
  userSide,
  clickable,
  kind,
  busy,
  playerId,
  onClick,
}: {
  slot: DraftSlot
  names: DraftState['names']
  userSide: 'a' | 'b'
  clickable: boolean
  kind: string
  busy: boolean
  playerId: number
  onClick: () => void
}) {
  const by = slot.by ? names[slot.by] : ''
  const mine = slot.by === userSide
  let style = 'bg-bg ring-1 ring-panel-light'
  if (slot.state === 'banned') style = 'bg-red-950/60 ring-1 ring-red-800 opacity-70'
  else if (slot.state === 'picked') style = `bg-green-950/50 ring-1 ${mine ? 'ring-green-500' : 'ring-green-800'}`
  else if (slot.state === 'played') style = `ring-1 ${slot.winner === userSide ? 'bg-green-900/40 ring-green-600' : 'bg-red-900/30 ring-red-800'}`
  else if (clickable) style = `bg-bg ring-1 ${kind === 'ban' ? 'ring-red-500/60 hover:bg-red-950/40' : 'ring-green-500/60 hover:bg-green-950/40'} cursor-pointer`
  const body = (
    <div className={`h-full rounded-lg p-2 text-left text-xs ${style}`}>
      <div className="flex items-center gap-1.5">
        <span className={`rounded px-1.5 py-0.5 text-[11px] font-bold ${MOD_BADGE[slot.family] ?? 'bg-slate-600'}`}>{slot.slot}</span>
        {slot.beatmap_id != null && (
          <span className="font-semibold" style={{ color: starColor(slot.stars) }}>
            {slot.stars.toFixed(2)}★
          </span>
        )}
        <span className="ml-auto text-[10px] text-muted">{slot.mods}</span>
      </div>
      <div className={`mt-1 truncate ${slot.state === 'banned' ? 'line-through' : ''}`} title={slot.title}>
        {slot.title || '…'}
      </div>
      <div className="mt-0.5 h-4 text-[10px] text-muted">
        {slot.state === 'banned' && `🚫 ${t('banned by {name}', { name: by })}`}
        {slot.state === 'picked' && `✔ ${t('picked by {name}', { name: by })}`}
        {slot.state === 'played' && (
          <>
            {(slot.score_a ?? 0).toLocaleString('en-US')} : {(slot.score_b ?? 0).toLocaleString('en-US')}
          </>
        )}
        {slot.state === 'open' && clickable && (kind === 'ban' ? '🚫' : '✔')}
      </div>
    </div>
  )
  return (
    <MapHint playerId={playerId} beatmapId={slot.beatmap_id} mods={hintMods(slot.mods)}>
      {clickable ? (
        <button type="button" disabled={busy} onClick={onClick} className="block h-full w-full" aria-label={`${kind} ${slot.slot}`}>
          {body}
        </button>
      ) : (
        body
      )}
    </MapHint>
  )
}

function logText(line: DraftLogLine): string {
  if (line.kind === 'ban') return `${line.who} ${t('banned')} ${line.slot}`
  if (line.kind === 'pick') return `${line.who} ${t('picked')} ${line.slot}`
  if (line.kind === 'tb') return `${t('tiebreaker')}: ${line.slot}`
  return `${line.slot}: ${(line.score_a ?? 0).toLocaleString('en-US')} – ${(line.score_b ?? 0).toLocaleString('en-US')}`
}

function ResultCard({ map, userSide, index }: { map: MatchMap; userSide: 'a' | 'b'; index: number }) {
  const won = map.winner === userSide
  const focus = map.players?.find((p) => p.kind === 'user') ?? map.players?.[0]
  return (
    <div className={`space-y-1 rounded-lg p-2 text-xs ${won ? 'bg-green-900/25' : 'bg-red-900/20'}`}>
      <div className="flex items-center gap-2">
        <span className="w-10 font-bold">{map.slot}</span>
        <span className="min-w-0 flex-1 truncate">{map.title}</span>
        {map.tie && <span className="rounded bg-amber-500/20 px-1.5 text-amber-300">{t('Tie')}</span>}
        <span className={won ? 'font-bold text-green-300' : 'font-bold text-red-300'}>
          {(map.score_a ?? 0).toLocaleString('en-US')} : {(map.score_b ?? 0).toLocaleString('en-US')}
        </span>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-muted">
        {map.players?.map((p, i) => (
          <span key={i} className={p.kind === 'user' ? 'text-osu-pink' : ''}>
            {p.name}: {p.accuracy.toFixed(2)}% · {p.combo}/{p.max_combo}x · {p.misses}❌
          </span>
        ))}
      </div>
      {focus && (
        <WatchReplay
          key={index}
          replay={focus.replay}
          summary={{ passed: focus.passed ?? true, grade: focus.grade, accuracy: focus.accuracy, misses: focus.misses, combo: focus.combo, maxCombo: focus.max_combo }}
        />
      )}
    </div>
  )
}

/** The live ban/pick room: the opponent's choices are made at their turn and shown before yours. */
export function DraftRoom({
  playerId,
  tournamentId,
  matchId,
  onPlayed,
}: {
  playerId: number
  tournamentId: number
  matchId: number
  onPlayed: () => void
}) {
  const [d, setD] = useState<DraftState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const loaded = useRef(false)

  const run = useCallback(async (fn: () => Promise<DraftState>) => {
    setBusy(true)
    setError(null)
    try {
      setD(await fn())
    } catch (e) {
      setError(tx((e as Error).message))
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    if (loaded.current) return
    loaded.current = true
    void run(() => worldApi.draft(playerId, tournamentId, matchId))
  }, [run, playerId, tournamentId, matchId])

  if (!d) return <p className="mt-3 text-xs text-muted">{error ?? t('Loading…')}</p>

  const opponent = d.names[d.user_side === 'a' ? 'b' : 'a']
  const me = d.names[d.user_side]
  const myScore = d.score[d.user_side]
  const theirScore = d.score[d.user_side === 'a' ? 'b' : 'a']
  const kind = d.turn.kind
  const mine = d.turn.mine && !d.finished
  const banner = d.finished
    ? myScore > theirScore
      ? t('You win {a}–{b}', { a: myScore, b: theirScore })
      : t('You lose {a}–{b}', { a: myScore, b: theirScore })
    : mine
      ? kind === 'ban'
        ? t('Your turn: ban a map')
        : t('Your turn: pick a map')
      : t('Waiting for {name}…', { name: opponent })
  const bannerStyle = d.finished
    ? myScore > theirScore
      ? 'bg-green-900/40 text-green-200 ring-green-600'
      : 'bg-red-900/40 text-red-200 ring-red-700'
    : mine
      ? kind === 'ban'
        ? 'bg-red-900/40 text-red-100 ring-red-600'
        : 'bg-green-900/40 text-green-100 ring-green-600'
      : 'bg-panel-light text-muted ring-panel-light'

  return (
    <div className="mt-3 space-y-3 rounded-xl bg-bg p-3" aria-label={t('Draft room')}>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <div className="min-w-0 flex-1">
          <span className="font-semibold text-osu-pink">{me}</span> <span className="text-muted">({t('seed {n}', { n: d.seeds[d.user_side] })})</span>
          <span className="mx-2 text-muted">vs</span>
          <span className="font-semibold">{opponent}</span> <span className="text-muted">({t('seed {n}', { n: d.seeds[d.user_side === 'a' ? 'b' : 'a'] })})</span>
        </div>
        <div className="text-2xl font-black tabular-nums" title={t('First to {n}', { n: d.first_to })}>
          {myScore} : {theirScore}
        </div>
        <span className="text-xs text-muted">{t('First to {n}', { n: d.first_to })}</span>
      </div>

      <div className={`rounded-lg px-3 py-2 text-sm font-semibold ring-1 ${bannerStyle}`} role="status">
        {banner}
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        {FAMILIES.flatMap((fam) => d.slots.filter((s) => s.family === fam)).map((s) => (
          <Tile
            key={s.slot}
            slot={s}
            names={d.names}
            userSide={d.user_side}
            clickable={mine && s.legal && s.state === 'open'}
            kind={kind}
            busy={busy}
            playerId={playerId}
            onClick={() => void run(() => worldApi.draftAct(playerId, tournamentId, matchId, s.slot))}
          />
        ))}
      </div>

      {!d.finished && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <button
            disabled={busy || !d.warmup.available}
            onClick={() => void run(() => worldApi.draftWarmup(playerId, tournamentId, matchId))}
            title={d.warmup.used ? t('Warmed up: a bit more form and nerve for this match') : t('Warm-up costs a little stamina')}
            className="rounded-full bg-panel-light px-3 py-1.5 font-semibold hover:bg-osu-pink disabled:opacity-40"
          >
            🔥 {d.warmup.used ? t('Warmed up: a bit more form and nerve for this match') : t('Warm up (30 min)')}
          </button>
          <button
            disabled={busy}
            onClick={() => void run(() => worldApi.draftAuto(playerId, tournamentId, matchId))}
            className="rounded-full bg-panel-light px-3 py-1.5 font-semibold hover:bg-osu-pink disabled:opacity-40"
          >
            ⏩ {t('Auto-finish')}
          </button>
          <span className="text-muted">
            {t('Bans are made first by the better seed, picks start with the other side. Each pick is played at once.')}
          </span>
        </div>
      )}

      {d.maps.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-[11px] uppercase tracking-wider text-muted">{t('Results')}</h4>
          {d.maps.map((m, i) => (
            <ResultCard key={i} map={m} userSide={d.user_side} index={i} />
          ))}
        </div>
      )}

      <div className="space-y-0.5">
        <h4 className="text-[11px] uppercase tracking-wider text-muted">{t('Order of events')}</h4>
        {d.log.length === 0 && <p className="text-xs text-muted">{t('Nothing has been decided yet.')}</p>}
        <ol className="max-h-40 space-y-0.5 overflow-y-auto text-xs">
          {d.log.map((line, i) => (
            <li key={i} className={line.kind === 'result' ? 'font-semibold' : line.mine ? 'text-osu-pink' : 'text-muted'}>
              {i + 1}. {logText(line)}
            </li>
          ))}
        </ol>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}
      {d.finished && (
        <div className="flex justify-end">
          <button onClick={onPlayed} className="rounded-full bg-osu-pink px-5 py-2 text-sm font-semibold hover:bg-osu-pink-dark">
            {t('Continue')}
          </button>
        </div>
      )}
    </div>
  )
}
