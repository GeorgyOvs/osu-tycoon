import { useEffect, useState } from 'react'
import { formatLength, playApi, starColor, type Assessment, type Beatmap, type BeatmapSet, type QueuedPlay } from '../api'
import { t, tx } from '../i18n'
import { MapLeaderboard } from './MapLeaderboard'

const MODS = ['NF', 'EZ', 'HT', 'HD', 'HR', 'DT', 'FL'] as const
const CONFLICTS: Record<string, string[]> = { EZ: ['HR'], HR: ['EZ'], HT: ['DT'], DT: ['HT'] }
const DIMENSIONS: [string, string][] = [
  ['aim', t('Aim')],
  ['tapping', t('Tapping')],
  ['reading', t('Reading')],
  ['stamina', t('Stamina')],
]

function ratioColor(r: number) {
  if (r < 0.85) return 'bg-green-500'
  if (r < 1.0) return 'bg-lime-400'
  if (r < 1.15) return 'bg-amber-400'
  if (r < 1.3) return 'bg-orange-500'
  return 'bg-red-600'
}

interface Props {
  playerId: number
  dateKey: string // re-assess when the in-game day (and so the player's form) changes
  selected: { beatmap: Beatmap; set: BeatmapSet } | null
  onQueue: (play: QueuedPlay) => void
}

export function PlayPanel({ playerId, dateKey, selected, onQueue }: Props) {
  const [mods, setMods] = useState<string[]>([])
  const [attempts, setAttempts] = useState(1)
  const [assessment, setAssessment] = useState<Assessment | null>(null)
  const [error, setError] = useState<string | null>(null)

  const modString = mods.join('')
  const beatmapId = selected?.beatmap.id

  useEffect(() => {
    if (!beatmapId) return
    let cancelled = false
    setAssessment(null)
    setError(null)
    playApi
      .assess(playerId, beatmapId, modString)
      .then((a) => !cancelled && setAssessment(a))
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [playerId, beatmapId, modString, dateKey])

  if (!selected) {
    return (
      <section className="rounded-xl bg-panel p-5 text-sm text-muted">
        {t("Pick a difficulty below to see how your player would fare on it, then add it to today's session.")}
      </section>
    )
  }

  const { beatmap: b, set } = selected
  const toggle = (m: string) =>
    setMods((cur) => (cur.includes(m) ? cur.filter((x) => x !== m) : [...cur.filter((x) => !CONFLICTS[m]?.includes(x)), m]))

  const a = assessment
  const speedMult = mods.includes('DT') ? 1.5 : mods.includes('HT') ? 0.75 : 1

  return (
    <section className="space-y-4 rounded-xl bg-panel p-5">
      <div className="flex gap-3">
        <img src={set.cover_url} alt="" className="h-14 w-14 rounded object-cover" />
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold">
            {set.artist} - {set.title}
          </div>
          <div className="truncate text-sm">
            <span style={{ color: starColor(a?.map.stars ?? b.stars) }}>{(a?.map.stars ?? b.stars).toFixed(2)}★</span>{' '}
            <span className="text-muted">[{b.version}]</span>
          </div>
          {a && (
            <div className="text-xs text-muted">
              AR {a.map.ar.toFixed(1)} · OD {a.map.od.toFixed(1)} · CS {a.map.cs.toFixed(1)} · HP {a.map.hp.toFixed(1)} ·{' '}
              {Math.round(a.map.bpm)} BPM · {formatLength(Math.round(a.map.drain_seconds))}
              {a.map.longest_stream >= 3 && (
                <>
                  {' '}
                  · {t('streams up to {n} notes @ {bpm} BPM', { n: a.map.longest_stream, bpm: Math.round(a.map.fastest_stream_bpm) })}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {MODS.map((m) => (
          <button
            key={m}
            onClick={() => toggle(m)}
            className={`rounded-md px-3 py-1 text-sm font-bold ${
              mods.includes(m) ? 'bg-osu-pink' : 'bg-panel-light text-muted hover:text-white'
            }`}
          >
            {m}
          </button>
        ))}
      </div>

      {error && <p className="text-sm text-red-400">{tx(error)}</p>}
      {!a && !error && <p className="text-sm text-muted">{t('Simulating a few attempts…')}</p>}
      {a && (
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1 text-sm">
            <div className="flex justify-between">
              <span className="text-muted">{t('Pass chance today')}</span>
              <b className={a.pass_rate >= 0.7 ? 'text-green-300' : a.pass_rate >= 0.3 ? 'text-amber-300' : 'text-red-400'}>
                {Math.round(a.pass_rate * 100)}%
              </b>
            </div>
            <div className="flex justify-between">
              <span className="text-muted">{t('Full combo chance')}</span>
              <span>{Math.round(a.fc_rate * 100)}%</span>
            </div>
            <div className="flex justify-between" title={t('Familiarity fades in weeks; mastery needs hundreds of attempts and lasts for a year or more.')}>
              <span className="text-muted">{t('Map knowledge')}</span>
              <span>
                {Math.round((a.familiarity ?? 0) * 100)}% · {t('mastery')} {Math.round((a.mastery ?? 0) * 100)}%
              </span>
            </div>
            {a.block && (
              <div className="rounded bg-amber-500/15 px-2 py-1 text-xs text-amber-200" title={t('A break from the map, a calm clean pass or a bit of luck dissolves it. Mastery weakens it.')}>
                🔒 {t('Mindlock around {t}: you tense up there', { t: `${Math.floor(a.block.at_seconds / 60)}:${String(a.block.at_seconds % 60).padStart(2, '0')}` })}
                {a.block.severity >= 0.6 ? ` · ${t('severe')}` : ''}
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-muted">{t('Typical pass')}</span>
              <span>
                {a.median_accuracy != null ? `${a.median_accuracy.toFixed(2)}%, ${a.median_misses}❌` : t('none')}
              </span>
            </div>
          </div>
          <div className="space-y-1.5">
            {DIMENSIONS.map(([key, label]) => {
              const r = a.peak_ratios[key] ?? 0
              if (key === 'reading' && r === 0) return null
              return (
                <div key={key} className="flex items-center gap-2 text-xs" title={t('Peak demand vs. what you handle reliably (100% = your limit)')}>
                  <span className={`w-14 ${key === a.weakest ? 'font-bold text-white' : 'text-muted'}`}>{label}</span>
                  <div className="relative h-2 flex-1 rounded-full bg-bg">
                    <div className={`h-full rounded-full ${ratioColor(r)}`} style={{ width: `${Math.min(100, (r / 1.6) * 100)}%` }} />
                    <div className="absolute top-[-2px] h-3 w-px bg-white/60" style={{ left: `${100 / 1.6}%` }} />
                  </div>
                  <span className="w-10 text-right">{Math.round(r * 100)}%</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <MapLeaderboard playerId={playerId} beatmapId={b.id} dateKey={dateKey} />

      <div className="flex items-center gap-3">
        <span className="text-sm text-muted">{t('Attempts')}</span>
        <input
          type="number"
          min={1}
          max={10}
          value={attempts}
          onChange={(e) => setAttempts(Math.max(1, Math.min(10, Number(e.target.value))))}
          className="w-16 rounded bg-bg px-2 py-1.5 text-center outline-none focus:ring-2 focus:ring-osu-pink"
        />
        <button
          onClick={() =>
            onQueue({
              beatmap_id: b.id,
              beatmapset_id: set.id,
              title: `${set.artist} - ${set.title}`,
              version: b.version,
              stars: a?.map.stars ?? b.stars,
              length: Math.round(b.hit_length / speedMult),
              mods: modString,
              attempts,
            })
          }
          className="ml-auto rounded-full bg-osu-pink px-5 py-2 text-sm font-semibold hover:bg-osu-pink-dark"
        >
          + {t('Add to session')}
        </button>
      </div>
    </section>
  )
}

interface QueueProps {
  queue: QueuedPlay[]
  busy: boolean
  disabledReason: string | null
  onRemove: (index: number) => void
  onPlay: () => void
}

export function SessionQueue({ queue, busy, disabledReason, onRemove, onPlay }: QueueProps) {
  if (queue.length === 0) return null
  const seconds = queue.reduce((sum, q) => sum + q.attempts * (q.length + 25), 0)
  return (
    <section className="space-y-3 rounded-xl bg-panel p-5">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t("Today's session")}</h2>
        <span className="text-xs text-muted">{t('up to ~{n}h of playing', { n: (seconds / 3600).toFixed(1) })}</span>
      </div>
      <ul className="space-y-1">
        {queue.map((q, i) => (
          <li key={i} className="flex items-center gap-2 rounded bg-bg px-3 py-1.5 text-sm">
            <span className="font-bold" style={{ color: starColor(q.stars) }}>
              {q.stars.toFixed(1)}★
            </span>
            <span className="min-w-0 flex-1 truncate">
              {q.title} <span className="text-muted">[{q.version}]</span>
            </span>
            {q.mods && <span className="rounded bg-panel-light px-1.5 text-xs font-bold">{q.mods}</span>}
            <span className="text-xs text-muted">×{q.attempts}</span>
            <button onClick={() => onRemove(i)} className="text-muted hover:text-white">
              ✕
            </button>
          </li>
        ))}
      </ul>
      <button
        disabled={busy || disabledReason != null}
        onClick={onPlay}
        className="w-full rounded-full bg-osu-pink py-2 font-semibold hover:bg-osu-pink-dark disabled:opacity-50"
      >
        {disabledReason ?? (busy ? t('Playing…') : t('Play session (ends the day)'))}
      </button>
    </section>
  )
}
