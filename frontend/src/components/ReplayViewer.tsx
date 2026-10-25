import { useEffect, useMemo, useRef, useState } from 'react'
import { t, tx } from '../i18n'
import type { CommentaryLine, MatchCommentary, MatchMap, MatchPlayer, Replay } from '../api'

const W = 600
const H = 150
const TICK_MS = 100
const SPEEDS = [1, 2, 4, 8]

const MOMENT_COLORS: Record<string, string> = {
  stream: '#38bdf8',
  jump: '#a78bfa',
  rhythm: '#fbbf24',
  slider: '#34d399',
  miss: '#f87171',
  miss_streak: '#ef4444',
  choke: '#dc2626',
  hp_scare: '#fb923c',
  fail: '#b91c1c',
  fc: '#4ade80',
}

const MOMENT_LABELS: Record<string, string> = {
  stream: t('Stream'),
  jump: t('Jumps'),
  rhythm: t('Rhythm'),
  slider: t('Sliders'),
  miss: t('Miss'),
  miss_streak: t('Miss streak'),
  choke: t('Choke'),
  hp_scare: t('Close call'),
  fail: t('Fail'),
  fc: t('Full combo'),
}

const TONE_CLASS: Record<string, string> = {
  hype: 'text-green-300',
  tense: 'text-orange-300',
  sad: 'text-red-300',
  neutral: 'text-slate-200',
}

export interface ReplaySummary {
  passed: boolean
  grade?: string
  accuracy: number
  misses: number
  combo: number
  maxCombo: number
}

function fmtTime(sec: number) {
  const s = Math.max(0, Math.floor(sec))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function Chart({ replay, time }: { replay: Replay; time: number }) {
  const total = Math.max(1, replay.duration)
  const x = (sec: number) => (Math.min(sec, total) / total) * W
  const n = replay.t.length
  const strain = [`M0,${H}`, ...replay.t.map((sec, i) => `L${x(sec).toFixed(1)},${(H - replay.strain[i] * H * 0.55).toFixed(1)}`), `L${x(replay.end).toFixed(1)},${H}`, 'Z'].join(' ')
  const hp = replay.t.map((sec, i) => `${x(sec).toFixed(1)},${(H - replay.hp[i] * (H - 8) - 2).toFixed(1)}`).join(' ')
  const combo = replay.t
    .map((sec, i) => `${x(sec).toFixed(1)},${(H - (replay.combo[i] / Math.max(1, replay.max_combo)) * (H - 8) - 2).toFixed(1)}`)
    .join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded bg-bg" role="img" aria-label={t('Replay chart')}>
      <path d={strain} fill="rgba(148,163,184,0.22)" />
      <polyline points={hp} fill="none" stroke="#4ade80" strokeWidth="1.5" opacity="0.8" />
      <polyline points={combo} fill="none" stroke="#38bdf8" strokeWidth="1.5" />
      {replay.misses.map((m, i) => {
        const delta = m - (i ? replay.misses[i - 1] : 0)
        return delta > 0 ? (
          <line key={i} x1={x(replay.t[i])} x2={x(replay.t[i])} y1={H} y2={H - Math.min(40, 10 + delta * 6)} stroke="#f87171" strokeWidth="2" />
        ) : null
      })}
      {replay.moments.map((m, i) => (
        <circle key={i} cx={x(m.t)} cy={8} r={4} fill={MOMENT_COLORS[m.type] ?? '#94a3b8'}>
          <title>{`${fmtTime(m.t)} ${MOMENT_LABELS[m.type] ?? m.type}: ${tx(m.text)}`}</title>
        </circle>
      ))}
      <line x1={x(time)} x2={x(time)} y1={0} y2={H} stroke="#ff66aa" strokeWidth="1.5" />
      {n === 0 && <text x={10} y={20} fill="#94a3b8">…</text>}
    </svg>
  )
}

/** Plays one attempt back: chart, live stats, a caster feed that reveals as the clock advances. */
export function ReplayViewer({
  replay,
  commentary = [],
  summary,
  autoPlay = true,
  startSpeed = 4,
  onEnded,
}: {
  replay: Replay
  commentary?: CommentaryLine[]
  summary?: ReplaySummary
  autoPlay?: boolean
  startSpeed?: number
  onEnded?: () => void
}) {
  const lastLine = commentary.reduce((m, l) => Math.max(m, l.t), 0)
  const total = Math.max(replay.duration, replay.end, lastLine)
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(autoPlay)
  const [speed, setSpeed] = useState(startSpeed)
  const endedRef = useRef(false)
  const feedRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!playing) return
    const id = setInterval(() => {
      setTime((cur) => {
        const next = Math.min(total, cur + (TICK_MS / 1000) * speed)
        if (next >= total) setPlaying(false)
        return next
      })
    }, TICK_MS)
    return () => clearInterval(id)
  }, [playing, speed, total])

  const finished = time >= total
  useEffect(() => {
    if (finished && !endedRef.current) {
      endedRef.current = true
      onEnded?.()
    }
    if (!finished) endedRef.current = false
  }, [finished, onEnded])

  const visible = useMemo(() => commentary.filter((l) => l.t <= time), [commentary, time])
  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight
  }, [visible.length])

  let idx = -1
  for (let i = 0; i < replay.t.length; i++) if (replay.t[i] <= time) idx = i
  const stat = idx >= 0 ? { combo: replay.combo[idx], hp: replay.hp[idx], acc: replay.acc[idx], misses: replay.misses[idx] } : { combo: 0, hp: 1, acc: 100, misses: 0 }

  return (
    <div className="space-y-2 rounded-lg bg-panel p-3 text-xs">
      <Chart replay={replay} time={time} />
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => {
            if (finished) setTime(0)
            setPlaying((p) => !p || finished)
          }}
          className="rounded bg-osu-pink px-3 py-1 font-semibold hover:bg-osu-pink-dark"
        >
          {playing ? t('Pause') : finished ? t('Restart') : t('Resume')}
        </button>
        <input
          type="range"
          min={0}
          max={Math.round(total * 10)}
          value={Math.round(time * 10)}
          onChange={(e) => setTime(Number(e.target.value) / 10)}
          aria-label={t('Replay position')}
          className="min-w-24 flex-1"
        />
        <span className="font-mono text-muted">
          {fmtTime(time)} / {fmtTime(total)}
        </span>
        <span className="flex gap-1" aria-label={t('Replay speed')}>
          {SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              className={`rounded px-1.5 py-0.5 ${speed === s ? 'bg-osu-pink' : 'bg-panel-light text-muted hover:text-white'}`}
            >
              {s}x
            </button>
          ))}
        </span>
      </div>
      <div className="grid grid-cols-4 gap-2 text-center">
        <Cell label={t('Combo')} value={`${stat.combo}x`} color="#38bdf8" />
        <Cell label={t('Health')} value={`${Math.round(stat.hp * 100)}%`} color="#4ade80" />
        <Cell label={t('Accuracy')} value={`${stat.acc.toFixed(2)}%`} />
        <Cell label={t('Misses')} value={String(stat.misses)} color="#f87171" />
      </div>
      {commentary.length > 0 && (
        <div ref={feedRef} className="max-h-36 space-y-0.5 overflow-y-auto rounded bg-bg p-2" aria-live="polite">
          {visible.length === 0 && <div className="text-muted">…</div>}
          {visible.map((l, i) => (
            <div key={i} className={TONE_CLASS[l.tone] ?? ''}>
              <span className="font-mono text-muted">{fmtTime(l.t)}</span> <b>{l.who}:</b> {tx(l.text)}
            </div>
          ))}
        </div>
      )}
      {finished && summary && (
        <div className="flex flex-wrap items-center gap-3 rounded bg-bg px-3 py-2" data-testid="replay-summary">
          <span className="text-lg font-black">{summary.passed ? summary.grade : t('Failed')}</span>
          <span>{summary.accuracy.toFixed(2)}%</span>
          <span className="text-muted">
            {summary.combo}/{summary.maxCombo}x
          </span>
          <span className="text-red-400">{summary.misses}❌</span>
        </div>
      )}
    </div>
  )
}

function Cell({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded bg-bg py-1">
      <div className="text-[10px] uppercase tracking-wider text-muted">{label}</div>
      <div className="text-sm font-bold" style={color ? { color } : undefined}>
        {value}
      </div>
    </div>
  )
}

export function focusPlayer(map: MatchMap): MatchPlayer | undefined {
  const players = map.players ?? []
  return players.find((p) => p.kind === 'user') ?? players.find((p) => p.side === 'a') ?? players[0]
}

/** Steps through a match map by map with a running scoreboard; Skip jumps to the final result. */
export function LiveMatch({
  maps,
  commentary,
  names,
  onClose,
}: {
  maps: MatchMap[]
  commentary: MatchCommentary
  names: [string, string]
  onClose: () => void
}) {
  const played = maps.filter((m) => !!m.slot)
  const bans = maps.find((m) => m.bans)?.bans
  const [step, setStep] = useState(0)
  const [mapDone, setMapDone] = useState(false)
  const [skipped, setSkipped] = useState(false)

  const upTo = skipped ? played.length : step + (mapDone ? 1 : 0)
  let sa = 0
  let sb = 0
  played.slice(0, upTo).forEach((m) => ((m.score_a ?? 0) >= (m.score_b ?? 0) ? sa++ : sb++))

  const done = skipped || step >= played.length
  const current = played[step]
  const focus = current ? focusPlayer(current) : undefined
  const lines = useMemo(() => {
    if (!current) return []
    const own = commentary.maps[step] ?? []
    const end = own.reduce((m, l) => Math.max(m, l.t), 0)
    const after = (commentary.between[step] ?? []).map((l, i) => ({ ...l, t: end + 1 + i * 1.2 }))
    return [...own, ...after]
  }, [commentary, current, step])

  const next = () => {
    setMapDone(false)
    setStep((s) => s + 1)
  }

  return (
    <div className="space-y-2 rounded-xl bg-panel-light/40 p-3 text-xs" data-testid="live-match">
      <div className="flex items-center gap-3">
        <span className="font-bold">{t('Live match')}</span>
        <span className="flex-1 text-center text-base font-black">
          {names[0]} {sa} – {sb} {names[1]}
        </span>
        <button onClick={onClose} className="rounded bg-panel px-2 py-0.5 text-muted hover:text-white">
          {t('Close')}
        </button>
      </div>
      {bans && (
        <div className="text-muted">
          {t('Bans')}: {names[0]} {bans.a.join(', ') || '—'} · {names[1]} {bans.b.join(', ') || '—'}
        </div>
      )}
      {step === 0 && !skipped && commentary.pre.length > 0 && (
        <div className="space-y-0.5 rounded bg-bg p-2">
          {commentary.pre.map((l, i) => (
            <div key={i}>
              <b>{l.who}:</b> {tx(l.text)}
            </div>
          ))}
        </div>
      )}
      {!done && current && (
        <>
          <div className="flex items-center gap-2">
            <span className="font-bold">{current.slot}</span>
            <span className="min-w-0 flex-1 truncate">{current.title}</span>
            <span className="text-muted">
              {current.picked_by === 'tb' ? t('tiebreaker') : t('{name} pick', { name: current.picked_by === 'a' ? names[0] : names[1] })}
            </span>
          </div>
          {focus?.replay ? (
            <ReplayViewer
              key={step}
              replay={focus.replay}
              commentary={lines}
              onEnded={() => setMapDone(true)}
              summary={{
                passed: focus.passed ?? true,
                grade: focus.grade,
                accuracy: focus.accuracy,
                misses: focus.misses,
                combo: focus.combo,
                maxCombo: focus.max_combo,
              }}
            />
          ) : (
            <div className="rounded bg-bg p-2 text-muted">{t('No replay was recorded for this map.')}</div>
          )}
        </>
      )}
      {done && (
        <div className="space-y-1 rounded bg-bg p-2">
          {commentary.post.map((l, i) => (
            <div key={i}>
              <b>{l.who}:</b> {tx(l.text)}
            </div>
          ))}
        </div>
      )}
      {!done && (
        <div className="flex gap-2">
          <button onClick={next} className="rounded bg-osu-pink px-3 py-1 font-semibold hover:bg-osu-pink-dark">
            {mapDone ? t('Next map') : t('Skip map')}
          </button>
          <button onClick={() => setSkipped(true)} className="rounded bg-panel px-3 py-1 text-muted hover:text-white">
            {t('Skip to result')}
          </button>
        </div>
      )}
    </div>
  )
}

/** Toggle button + inline viewer for a single replay. */
export function WatchReplay({
  replay,
  commentary,
  summary,
  label,
}: {
  replay?: Replay
  commentary?: CommentaryLine[]
  summary?: ReplaySummary
  label?: string
}) {
  const [open, setOpen] = useState(false)
  if (!replay || replay.t.length === 0) return null
  return (
    <div className="space-y-1">
      <button onClick={() => setOpen((o) => !o)} className="rounded bg-panel px-2 py-0.5 text-xs text-muted hover:text-white">
        {open ? t('Hide replay') : (label ?? t('Watch replay'))}
      </button>
      {open && <ReplayViewer replay={replay} commentary={commentary} summary={summary} />}
    </div>
  )
}
