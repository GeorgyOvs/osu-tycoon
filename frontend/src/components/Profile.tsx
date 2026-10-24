import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  api,
  fmt,
  playApi,
  type ActionResult,
  type Beatmap,
  type BeatmapSet,
  type Player,
  type PlayerProfile,
  type QueuedPlay,
  type Score,
  type ScoreSubmitResult,
  type SessionResult,
  type TournamentList,
  worldApi,
} from '../api'
import { getLang, setLang, t, tx } from '../i18n'
import { ActivityLog } from './ActivityLog'
import { AttributePanel } from './AttributePanel'
import { BeatmapBrowser } from './BeatmapBrowser'
import { ForumPanel } from './ForumPanel'
import { IrcOverlay } from './IrcOverlay'
import { LifePanel } from './LifePanel'
import { PlayPanel, SessionQueue } from './PlayPanel'
import { QuickSession } from './QuickSession'
import { PreviewButton } from './PreviewButton'
import { ScoreForm } from './ScoreForm'
import { SessionResults } from './SessionResults'
import { MatchBanner, TournamentsPanel } from './TournamentsPanel'
import { TrainingPanel } from './TrainingPanel'
import { WeekPlanner } from './WeekPlanner'
import { WorldPanel } from './WorldPanel'

type Tab = 'training' | 'beatmaps' | 'tournaments' | 'world' | 'social' | 'life' | 'scores'
const TABS: [Tab, string][] = [
  ['training', t('Training')],
  ['beatmaps', t('Play')],
  ['tournaments', t('Tournaments')],
  ['world', t('World')],
  ['social', t('Social')],
  ['life', t('Life')],
  ['scores', t('Scores')],
]

const INJURY_LABELS = {
  healthy: t('Healthy'),
  minor_strain: t('Minor wrist strain'),
  severe_rsi: t('Severe tendonitis'),
}

function formLabel(form: number) {
  if (form >= 1) return { text: t('In the zone'), color: 'text-orange-300' }
  if (form >= 0.35) return { text: t('Good'), color: 'text-green-300' }
  if (form > -0.35) return { text: t('Normal'), color: 'text-muted' }
  if (form > -1) return { text: t('Off'), color: 'text-slate-400' }
  return { text: t('Slump'), color: 'text-slate-500' }
}

function InjuryBanner({ player }: { player: Player }) {
  const { injury } = player
  if (injury.state === 'healthy') return null
  const severe = injury.state === 'severe_rsi'
  return (
    <div className={`rounded-xl p-4 text-sm ${severe ? 'bg-red-950 ring-1 ring-red-600' : 'bg-orange-950 ring-1 ring-orange-600'}`}>
      <b>{INJURY_LABELS[injury.state]}.</b>{' '}
      {severe ? (
        <>
          {t('Forced hiatus until')} <b>{injury.until}</b>. {t('Physiotherapy days')}: {injury.physio_days}/14.{' '}
          {t('Without enough of it the stamina ceiling will drop permanently.')}
        </>
      ) : (
        <>{t('-15% stamina, -10% speed. Rest it off ({n}/5 recovery days); training through it risks severe RSI.', { n: injury.strain_recovery_days })}</>
      )}
    </div>
  )
}

function Bar({ label, value, color = 'bg-osu-pink' }: { label: string; value: number; color?: string }) {
  return (
    <div>
      <div className="flex justify-between text-xs">
        <span className="text-muted">{label}</span>
        <span>{value.toFixed(1)}</span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-bg">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(100, value)}%` }} />
      </div>
    </div>
  )
}

function ScoreRow({ score, extra }: { score: Score; extra?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 rounded-lg bg-panel px-3 py-2">
      <PreviewButton beatmapsetId={score.beatmapset_id} artist={score.artist} title={score.title} />
      <div className="min-w-0 flex-1">
        <a
          href={`https://osu.ppy.sh/b/${score.beatmap_id}`}
          target="_blank"
          rel="noreferrer"
          className="block truncate hover:text-osu-pink"
        >
          {score.artist} - {score.title} <span className="text-muted">[{score.difficulty_name}]</span>
        </a>
        <div className="text-xs text-muted">
          {fmt.stars(score.stars)} · {fmt.acc(score.accuracy)} · x{score.max_combo}
          {score.misses > 0 && <span className="text-red-400"> · {score.misses}❌</span>} · {score.played_on}
        </div>
      </div>
      <span className="rounded bg-panel-light px-2 py-0.5 text-xs font-bold">{fmt.mods(score.mods)}</span>
      <div className="w-24 text-right">
        <div className="font-bold text-osu-pink">{fmt.pp(score.pp)}</div>
        {extra}
      </div>
    </div>
  )
}

export function Profile({ playerId, onExit }: { playerId: number; onExit: () => void }) {
  const [profile, setProfile] = useState<PlayerProfile | null>(null)
  const [lastResult, setLastResult] = useState<ScoreSubmitResult | null>(null)
  const [actionLog, setActionLog] = useState<ActionResult[]>([])
  const [tab, setTab] = useState<Tab>('training')
  const [selected, setSelected] = useState<{ beatmap: Beatmap; set: BeatmapSet } | null>(null)
  const [queue, setQueue] = useState<QueuedPlay[]>([])
  const [session, setSession] = useState<SessionResult | null>(null)
  const [sessionBusy, setSessionBusy] = useState(false)
  const [sessionError, setSessionError] = useState<string | null>(null)
  const [tournamentList, setTournamentList] = useState<TournamentList | null>(null)
  const [worldVersion, setWorldVersion] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(
    () =>
      api
        .getPlayer(playerId)
        .then(setProfile)
        .catch((e) => setError(e.message)),
    [playerId],
  )
  useEffect(() => {
    void reload()
  }, [reload])

  // The pending-match banner needs the tournament list whenever the calendar or a match changes.
  useEffect(() => {
    if (!profile) return
    worldApi.tournaments(playerId).then(setTournamentList).catch(() => setTournamentList(null))
  }, [playerId, profile?.in_game_date, worldVersion])

  const labels = useMemo(
    () => Object.fromEntries((profile?.attributes ?? []).flatMap((g) => g.subs.map((s) => [s.key, t(s.label)]))),
    [profile?.attributes],
  )

  if (error)
    return (
      <div className="space-y-2 p-8">
        <p className="text-red-400">{error}</p>
        <button onClick={onExit} className="text-sm text-muted hover:text-white">
          ← {t('back to careers')}
        </button>
      </div>
    )
  if (!profile) return <p className="p-8 text-muted">{t('Loading…')}</p>

  const rankDelta =
    profile.global_rank != null && profile.previous_rank != null ? profile.previous_rank - profile.global_rank : 0

  const onSubmitted = (r: ScoreSubmitResult) => {
    setLastResult(r)
    void reload()
  }

  const onAction = (r: ActionResult) => {
    setActionLog((log) => [r, ...log].slice(0, 10))
    void reload()
  }

  const form = formLabel(profile.form)

  const playSession = async () => {
    setSessionBusy(true)
    setSessionError(null)
    try {
      const result = await playApi.session(
        playerId,
        queue.map((q) => ({ beatmap_id: q.beatmap_id, mods: q.mods, attempts: q.attempts })),
      )
      setSession(result)
      setQueue([])
      void reload()
    } catch (e) {
      setSessionError((e as Error).message)
    } finally {
      setSessionBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 pt-6 pb-24">
      <IrcOverlay playerId={playerId} />
      <header className="flex flex-wrap items-center gap-6 rounded-xl bg-panel p-5">
        <div className="flex-1">
          <button onClick={onExit} className="text-xs text-muted hover:text-white">
            ← {t('careers')}
          </button>
          <button
            onClick={() => setLang(getLang() === 'ru' ? 'en' : 'ru')}
            className="ml-3 rounded bg-panel-light px-1.5 text-xs text-muted hover:text-white"
            title={t('Interface language')}
          >
            {getLang() === 'ru' ? 'RU → EN' : 'EN → RU'}
          </button>
          <h1 className="text-3xl font-bold">
            {profile.name} <span className="text-lg text-muted">[{profile.country}]</span>
          </h1>
          <div className="text-sm text-muted">
            {profile.in_game_date} · {t(profile.era_label)}
            {profile.life && ` · ${t('{n}y', { n: profile.life.age ?? '?' })} · $${Math.round(profile.life.money).toLocaleString('en-US')}`}
          </div>
          {profile.badges.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {profile.badges.map((b) => (
                <span key={b.tournament_id} title={b.date} className="rounded bg-amber-500/20 px-2 py-0.5 text-xs text-amber-300">
                  🏅 {b.name}
                </span>
              ))}
            </div>
          )}
          {profile.pp_system && (
            <div className="text-xs text-muted" title={t(profile.pp_system.summary)}>
              {t('Ranking')}: {t(profile.pp_system.name)}
            </div>
          )}
          {profile.traits.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {profile.traits.map((t) => (
                <span key={t} className="rounded bg-panel-light px-2 py-0.5 text-xs">
                  {tx(t)}
                </span>
              ))}
            </div>
          )}
        </div>
        <Stat label={t('Global rank')} value={fmt.rank(profile.global_rank)}>
          {rankDelta !== 0 && (
            <span className={rankDelta > 0 ? 'text-green-400' : 'text-red-400'}>
              {rankDelta > 0 ? '▲' : '▼'}
              {Math.abs(rankDelta).toLocaleString('en-US')}
            </span>
          )}
        </Stat>
        <Stat label={t('Performance')} value={fmt.pp(profile.total_pp)} />
        <Stat label={t('Accuracy')} value={fmt.acc(profile.accuracy)} />
        <Stat label={t('Play count')} value={profile.play_count.toLocaleString('en-US')} />
      </header>

      <div className="grid gap-6 md:grid-cols-[1fr_2fr]">
        <aside className="space-y-6">
          <AttributePanel
            groups={profile.attributes}
            overall={profile.overall}
            ppPotential={profile.pp_potential}
            tournamentStrength={profile.tournament_strength}
          />
          <section className="space-y-3 rounded-xl bg-panel p-5">
            <h2 className="text-sm uppercase tracking-wider text-muted">{t('Condition')}</h2>
            <div className="flex justify-between text-xs">
              <span className="text-muted">{t('Form')}</span>
              <span className={form.color}>{form.text}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-muted">{t('Health')}</span>
              <span className={profile.injury.state === 'healthy' ? 'text-green-300' : 'text-red-400'}>
                {INJURY_LABELS[profile.injury.state]}
              </span>
            </div>
            <Bar label={t('Fatigue')} value={profile.conditions.fatigue} color="bg-red-500" />
            <Bar label={t('Motivation')} value={profile.conditions.motivation} color="bg-sky-400" />
            <Bar label={t('Tournament morale')} value={profile.conditions.morale} color="bg-amber-400" />
            <div className="text-xs text-muted">
              {t('Training streak')}: {profile.conditions.consecutive_training_days}
            </div>
          </section>
        </aside>

        <main className="space-y-6">
          <InjuryBanner player={profile} />
          <MatchBanner
            playerId={playerId}
            list={tournamentList}
            onPlayed={() => {
              setWorldVersion((v) => v + 1)
              setTab('tournaments')
              void reload()
            }}
          />
          <nav className="flex gap-1 rounded-full bg-panel p-1">
            {TABS.map(([key, label]) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`flex-1 rounded-full py-1.5 text-sm font-semibold ${
                  tab === key ? 'bg-osu-pink' : 'text-muted hover:text-white'
                }`}
              >
                {label}
              </button>
            ))}
          </nav>

          {tab === 'training' && (
            <>
              <WeekPlanner
                player={profile}
                onLived={(week) => {
                  onAction({
                    start_date: week.start_date,
                    end_date: week.end_date,
                    days: week.days.length,
                    events: week.days.flatMap((d) => d.events),
                    deltas: week.deltas,
                    scores: week.scores,
                    player: week.player,
                  })
                  setWorldVersion((v) => v + 1)
                }}
              />
              <TrainingPanel player={profile} onAction={onAction} />
              <ActivityLog log={actionLog} labels={labels} />
            </>
          )}

          {tab === 'beatmaps' && (
            <>
              <QuickSession
                playerId={playerId}
                dateKey={profile.in_game_date}
                disabledReason={profile.injury.state === 'severe_rsi' ? t('Forced hiatus: no playing') : null}
                onPlayed={(result) => {
                  setSession(result)
                  void reload()
                }}
              />
              {session && <SessionResults result={session} labels={labels} />}
              <details className="rounded-xl bg-panel p-5 text-sm">
                <summary className="cursor-pointer text-muted">{t('Pick maps yourself (beatmap browser, leaderboards)')}</summary>
                <div className="mt-4 space-y-6">
                  <PlayPanel
                    playerId={playerId}
                    dateKey={profile.in_game_date}
                    selected={selected}
                    onQueue={(q) => setQueue((cur) => [...cur, q])}
                  />
                  <SessionQueue
                    queue={queue}
                    busy={sessionBusy}
                    disabledReason={profile.injury.state === 'severe_rsi' ? t('Forced hiatus: no playing') : null}
                    onRemove={(i) => setQueue((cur) => cur.filter((_, j) => j !== i))}
                    onPlay={playSession}
                  />
                  {sessionError && <p className="text-sm text-red-400">{sessionError}</p>}
                  <BeatmapBrowser
                    before={profile.in_game_date}
                    selectedId={selected?.beatmap.id ?? null}
                    onSelect={(beatmap, set) => setSelected({ beatmap, set })}
                  />
                </div>
              </details>
              <details className="rounded-xl bg-panel p-5 text-sm">
                <summary className="cursor-pointer text-muted">{t('Manual score entry (debug)')}</summary>
                <div className="mt-4 space-y-4">
                  <ScoreForm playerId={playerId} onSubmitted={onSubmitted} selectedBeatmapId={selected?.beatmap.id ?? null} />
                  {lastResult && (
                    <div className={`rounded-xl p-4 ${lastResult.is_new_top_play ? 'bg-osu-pink/20 ring-1 ring-osu-pink' : 'bg-bg'}`}>
                      {lastResult.is_new_top_play ? (
                        <>
                          {t('New top play')} <b>#{lastResult.top_play_position}</b>: {fmt.pp(lastResult.score.pp)} —{' '}
                          {lastResult.score.title}! {t('Total')} +{lastResult.pp_gained.toFixed(1)}pp.
                        </>
                      ) : (
                        <>{t("Score submitted ({pp}), but it didn't beat your top plays.", { pp: fmt.pp(lastResult.score.pp) })}</>
                      )}
                    </div>
                  )}
                </div>
              </details>
            </>
          )}

          {tab === 'tournaments' && (
            <TournamentsPanel
              playerId={playerId}
              dateKey={`${profile.in_game_date}:${worldVersion}`}
              onChanged={() => setWorldVersion((v) => v + 1)}
            />
          )}

          {tab === 'world' && (
            <WorldPanel
              playerId={playerId}
              dateKey={`${profile.in_game_date}:${worldVersion}`}
              country={profile.country}
              onChanged={() => void reload()}
            />
          )}

          {tab === 'life' && (
            <LifePanel player={profile} dateKey={`${profile.in_game_date}:${worldVersion}`} onChanged={() => void reload()} />
          )}

          {tab === 'social' && <ForumPanel playerId={playerId} dateKey={`${profile.in_game_date}:${worldVersion}`} />}

          {tab === 'scores' && (
            <>
              <section className="space-y-2">
                <h2 className="text-sm uppercase tracking-wider text-muted">
                  {t('Best performance')} ({profile.top_plays.length})
                </h2>
                {profile.top_plays.length === 0 && <p className="text-sm text-muted">{t('No scores yet.')}</p>}
                {profile.top_plays.map((s) => (
                  <ScoreRow
                    key={s.id}
                    score={s}
                    extra={
                      <div className="text-xs text-muted">
                        {Math.round(s.weighted_pp)}pp ({Math.round(s.weight * 100)}%)
                      </div>
                    }
                  />
                ))}
              </section>
              {profile.recent_scores.length > 0 && (
                <section className="space-y-2">
                  <h2 className="text-sm uppercase tracking-wider text-muted">{t('Recent plays')}</h2>
                  {profile.recent_scores.map((s) => (
                    <ScoreRow key={s.id} score={s} />
                  ))}
                </section>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  )
}

function Stat({ label, value, children }: { label: string; value: string; children?: React.ReactNode }) {
  return (
    <div className="text-right">
      <div className="text-xs uppercase tracking-wider text-muted">{label}</div>
      <div className="text-2xl font-bold">{value}</div>
      {children && <div className="text-xs">{children}</div>}
    </div>
  )
}
