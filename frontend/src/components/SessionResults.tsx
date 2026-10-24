import { useState } from 'react'
import { fmt, starColor, type Attempt, type PlayResult, type SessionResult } from '../api'
import { t, tx } from '../i18n'
import { PreviewButton } from './PreviewButton'

const GRADE_COLORS: Record<string, string> = {
  SS: 'text-yellow-200',
  S: 'text-yellow-300',
  A: 'text-green-400',
  B: 'text-sky-400',
  C: 'text-purple-400',
  D: 'text-red-400',
  F: 'text-red-600',
}

/** The map as 40 slices: grey = never reached, red intensity = misses, dark bar = HP low point. */
function Timeline({ attempt }: { attempt: Attempt }) {
  const maxMiss = Math.max(1, ...attempt.timeline.map((b) => b.misses))
  return (
    <div className="flex h-5 gap-px" title={t('Misses across the map; the lower bar shows the lowest HP in each part')}>
      {attempt.timeline.map((b, i) => (
        <div key={i} className="flex flex-1 flex-col justify-end gap-px">
          <div
            className="flex-1 rounded-sm"
            style={{
              background: !b.reached
                ? '#2a2226'
                : b.misses
                  ? `rgba(239, 68, 68, ${0.35 + (0.65 * b.misses) / maxMiss})`
                  : 'rgba(74, 222, 128, 0.55)',
            }}
          />
          <div
            className="h-1 rounded-sm"
            style={{ background: b.reached ? `hsl(${Math.round(b.hp_min * 120)}, 70%, 45%)` : 'transparent' }}
          />
        </div>
      ))}
    </div>
  )
}

function AttemptRow({ attempt, index, best }: { attempt: Attempt; index: number; best: boolean }) {
  return (
    <div className={`space-y-1 rounded-lg p-2 ${best ? 'bg-osu-pink/10 ring-1 ring-osu-pink/50' : 'bg-bg'}`}>
      <div className="flex items-center gap-3 text-sm">
        <span className="w-6 text-xs text-muted">#{index + 1}</span>
        <span className={`w-6 text-lg font-black ${GRADE_COLORS[attempt.grade] ?? ''}`}>{attempt.grade}</span>
        {attempt.passed ? (
          <>
            <span>{fmt.acc(attempt.accuracy)}</span>
            <span className="text-muted">{attempt.max_combo}x</span>
            <span className="text-xs text-muted">
              {attempt.n300}/{attempt.n100}/{attempt.n50}/<span className="text-red-400">{attempt.misses}</span>
            </span>
            <span className="ml-auto font-bold text-osu-pink">{attempt.pp != null ? fmt.pp(attempt.pp) : ''}</span>
          </>
        ) : (
          <span className="text-red-400">
            {t('Failed at {n}%', { n: Math.round((attempt.fail_progress ?? 0) * 100) })}
          </span>
        )}
      </div>
      <Timeline attempt={attempt} />
      {attempt.key_moments.length > 0 && (
        <ul className="text-xs text-muted">
          {attempt.key_moments.map((m, i) => (
            <li key={i}>• {tx(m)}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function PlayCard({ play }: { play: PlayResult }) {
  const [open, setOpen] = useState(play.attempts.length <= 3)
  const shown = open ? play.attempts : play.best_index != null ? [play.attempts[play.best_index]] : play.attempts.slice(-1)
  const passes = play.attempts.filter((a) => a.passed).length
  return (
    <div className="space-y-2 rounded-xl bg-panel-light/50 p-3">
      <div className="flex items-center gap-2">
        <PreviewButton beatmapsetId={play.beatmap.beatmapset_id} artist={play.beatmap.artist} title={play.beatmap.title} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">
            {play.beatmap.artist} - {play.beatmap.title}
          </div>
          <div className="truncate text-xs text-muted">
            <span style={{ color: starColor(play.stars) }}>{play.stars.toFixed(2)}★</span> [{play.beatmap.version}] +
            {play.mods} · {t('{a}/{b} passed', { a: passes, b: play.attempts.length })}
          </div>
        </div>
        {play.is_new_top_play && (
          <span className="rounded-full bg-osu-pink px-2 py-0.5 text-xs font-bold">
            {t('Top play')} #{play.top_play_position} · +{play.pp_gained.toFixed(1)}pp
          </span>
        )}
      </div>
      {shown.map((a) => {
        const i = play.attempts.indexOf(a)
        return <AttemptRow key={i} attempt={a} index={i} best={i === play.best_index} />
      })}
      {play.attempts.length > 3 && (
        <button onClick={() => setOpen((o) => !o)} className="text-xs text-muted hover:text-white">
          {open ? t('Show best only') : t('Show all {n} attempts', { n: play.attempts.length })}
        </button>
      )}
    </div>
  )
}

export function SessionResults({ result, labels }: { result: SessionResult; labels: Record<string, string> }) {
  const trained = Object.entries(result.training)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
  const deltas = Object.entries(result.deltas)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 8)
  const passes = result.plays.reduce((n, p) => n + p.attempts.filter((a) => a.passed).length, 0)
  const attempts = result.plays.reduce((n, p) => n + p.attempts.length, 0)
  const best = Math.max(0, ...result.plays.map((p) => p.score?.pp ?? 0))
  return (
    <section className="space-y-3 rounded-xl bg-panel p-5">
      <h2 className="text-sm uppercase tracking-wider text-muted">
        {t('Session')} · {result.date} · {result.hours.toFixed(1)}{t('h')} · {t('{n} maps', { n: result.plays.length })} ·{' '}
        {t('{a}/{b} passed', { a: passes, b: attempts })}
        {best > 0 && ` · ${t('best')} ${Math.round(best)}pp`}
      </h2>
      {deltas.length > 0 && (
        <div className="flex flex-wrap gap-1.5 text-xs">
          {deltas.map(([k, d]) => (
            <span key={k} className={`rounded px-2 py-0.5 ${d > 0 ? 'bg-green-900/40 text-green-300' : 'bg-red-900/40 text-red-300'}`}>
              {labels[k] ?? k} {d > 0 ? '+' : ''}
              {d.toFixed(2)}
            </span>
          ))}
        </div>
      )}
      {result.plays.map((p, i) => (
        <PlayCard key={i} play={p} />
      ))}
      <div className="space-y-1 text-xs">
        <div className="text-muted">{t('Trained mostly')}:</div>
        <div className="flex flex-wrap gap-1">
          {trained.map(([k]) => (
            <span key={k} className="rounded bg-bg px-2 py-0.5">
              {labels[k] ?? k}
            </span>
          ))}
        </div>
      </div>
      {result.events.length > 0 && (
        <ul className="space-y-0.5 text-sm">
          {result.events.map((e, i) => (
            <li key={i}>• {tx(e.message)}</li>
          ))}
        </ul>
      )}
    </section>
  )
}
