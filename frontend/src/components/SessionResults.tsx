import { useState } from 'react'
import { fmt, starColor, type Attempt, type PlayResult, type SessionResult } from '../api'
import { t, tx } from '../i18n'
import { BoardButton } from './LeaderboardModal'
import { MapHint } from './MapHint'
import { PreviewButton } from './PreviewButton'
import { WatchReplay } from './ReplayViewer'

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
      <WatchReplay
        replay={attempt.replay}
        commentary={attempt.commentary}
        summary={{
          passed: attempt.passed,
          grade: attempt.grade,
          accuracy: attempt.accuracy,
          misses: attempt.misses,
          combo: attempt.max_combo,
          maxCombo: attempt.replay?.max_combo ?? attempt.max_combo,
        }}
      />
    </div>
  )
}

function PlayRow({ play, playerId, dateKey }: { play: PlayResult; playerId: number; dateKey: string }) {
  const [open, setOpen] = useState(false)
  const passes = play.attempts.filter((a) => a.passed).length
  const shown = play.best_index != null ? play.attempts[play.best_index] : play.attempts[play.attempts.length - 1]
  return (
    <div className={`rounded-lg bg-bg/60 ${open ? 'ring-1 ring-panel-light' : ''}`}>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setOpen((o) => !o)}
        className="flex cursor-pointer items-center gap-2 px-2 py-1 text-xs hover:bg-panel-light/40"
      >
        <PreviewButton beatmapsetId={play.beatmap.beatmapset_id} artist={play.beatmap.artist} title={play.beatmap.title} />
        <span className="w-12 shrink-0 font-bold" style={{ color: starColor(play.stars) }}>
          {play.stars.toFixed(2)}★
        </span>
        <MapHint playerId={playerId} beatmapId={play.beatmap.beatmap_id} mods={play.mods === 'NM' ? '' : play.mods} day={dateKey} className="min-w-0 flex-1 truncate text-sm">
          {play.beatmap.artist} - {play.beatmap.title} <span className="text-muted">[{play.beatmap.version}]</span>
        </MapHint>
        {play.mods && play.mods !== 'NM' && <span className="rounded bg-panel-light px-1.5 font-bold">{play.mods}</span>}
        <span className={`w-5 text-center text-base font-black ${shown.passed ? (GRADE_COLORS[shown.grade] ?? '') : 'text-red-500'}`}>
          {shown.passed ? shown.grade : 'F'}
        </span>
        <span className="hidden w-32 shrink-0 text-right text-muted sm:block">
          {shown.passed ? `${fmt.acc(shown.accuracy)} · ${shown.max_combo}x${shown.misses ? ` · ${shown.misses}❌` : ''}` : t('Failed at {n}%', { n: Math.round((shown.fail_progress ?? 0) * 100) })}
        </span>
        <span className="w-14 shrink-0 text-right font-bold text-osu-pink">{shown.pp != null ? fmt.pp(shown.pp) : '—'}</span>
        <span className="w-10 shrink-0 text-right text-muted" title={t('{a}/{b} passed', { a: passes, b: play.attempts.length })}>
          {passes}/{play.attempts.length}
        </span>
        <span className="w-28 shrink-0 text-right">
          {play.board_rank ? (
            <span
              className={`rounded-full px-1.5 py-0.5 font-bold ${play.board_rank <= 3 ? 'bg-amber-500/20 text-amber-300' : 'bg-panel-light text-white/80'}`}
              title={t('Place on the map leaderboard with this play')}
            >
              🏆 #{play.board_rank}
              {play.board_size ? <span className="font-normal text-muted"> / {play.board_size}</span> : null}
            </span>
          ) : (
            <span className="text-muted">{play.score ? '—' : ''}</span>
          )}
          {play.is_new_top_play && (
            <span className="ml-1 text-osu-pink" title={t('Top play')}>
              +{play.pp_gained.toFixed(0)}pp
            </span>
          )}
        </span>
        <BoardButton
          playerId={playerId}
          beatmapId={play.beatmap.beatmap_id}
          title={`${play.beatmap.artist} - ${play.beatmap.title} [${play.beatmap.version}]`}
          dateKey={dateKey}
        />
        <span className="w-3 text-muted">{open ? '▾' : '▸'}</span>
      </div>
      {open && (
        <div className="space-y-1.5 border-t border-panel-light/60 p-2">
          {play.attempts.map((a, i) => (
            <AttemptRow key={i} attempt={a} index={i} best={i === play.best_index} />
          ))}
          {play.score && (
            <div className="space-y-1.5 pt-1">
              <div className="flex items-center gap-3 text-xs text-muted">
                {play.previous_best_pp != null && !play.is_new_top_play && (
                  <span title={t('Replays never lower your total: only your best play on each map counts.')}>
                    {t('Not a new best · best {pp}', { pp: fmt.pp(play.previous_best_pp) })}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function SessionResults({
  result,
  labels,
  playerId,
  dateKey,
  defaultOpen = true,
  onPlayAgain,
  onPresetAgain,
  presetLabel,
}: {
  result: SessionResult
  labels: Record<string, string>
  playerId: number
  dateKey: string
  defaultOpen?: boolean
  onPlayAgain?: () => Promise<void>
  onPresetAgain?: () => Promise<void>
  presetLabel?: string
}) {
  const [open, setOpen] = useState(defaultOpen)
  const [again, setAgain] = useState<string | null>(null)
  const [againError, setAgainError] = useState<string | null>(null)
  const replay = async (key: string, fn: () => Promise<void>) => {
    setAgain(key)
    setAgainError(null)
    try {
      await fn()
    } catch (e) {
      setAgainError(tx((e as Error).message))
    } finally {
      setAgain(null)
    }
  }
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
    <section className="space-y-2 rounded-xl bg-panel p-4">
      <div className="flex flex-wrap items-center gap-2">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm uppercase tracking-wider text-muted hover:text-white"
      >
        <span className="flex-1">
          {t('Session')} · {result.date} · {result.hours.toFixed(1)}{t('h')} · {t('{n} maps', { n: result.plays.length })} ·{' '}
          {t('{a}/{b} passed', { a: passes, b: attempts })}
          {best > 0 && ` · ${t('best')} ${Math.round(best)}pp`}
        </span>
        <span>{open ? '▾' : '▸'}</span>
      </button>
      {onPlayAgain && (
        <button
          disabled={again !== null}
          onClick={() => void replay('maps', onPlayAgain)}
          title={t('Play the same maps with the same mods and attempts')}
          className="rounded-full bg-panel-light px-3 py-1 text-xs font-semibold hover:bg-osu-pink disabled:opacity-50"
        >
          {again === 'maps' ? '…' : `↻ ${t('Play again')}`}
        </button>
      )}
      {onPresetAgain && (
        <button
          disabled={again !== null}
          onClick={() => void replay('preset', onPresetAgain)}
          title={t('A new session from the same preset and hours')}
          className="rounded-full bg-panel-light px-3 py-1 text-xs font-semibold hover:bg-osu-pink disabled:opacity-50"
        >
          {again === 'preset' ? '…' : `↻ ${presetLabel ?? t('Same preset')}`}
        </button>
      )}
      </div>
      {againError && <p className="text-xs text-red-400">{againError}</p>}
      {open && deltas.length > 0 && (
        <div className="flex flex-wrap gap-1.5 text-xs">
          {deltas.map(([k, d]) => (
            <span key={k} className={`rounded px-2 py-0.5 ${d > 0 ? 'bg-green-900/40 text-green-300' : 'bg-red-900/40 text-red-300'}`}>
              {labels[k] ?? k} {d > 0 ? '+' : ''}
              {d.toFixed(2)}
            </span>
          ))}
        </div>
      )}
      {open && (
        <div className="space-y-1">
          {result.plays.map((p, i) => (
            <PlayRow key={i} play={p} playerId={playerId} dateKey={dateKey} />
          ))}
        </div>
      )}
      {open && (
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
      )}
      {open && result.events.length > 0 && (
        <ul className="space-y-0.5 text-sm">
          {result.events.map((e, i) => (
            <li key={i}>• {tx(e.message)}</li>
          ))}
        </ul>
      )}
    </section>
  )
}
