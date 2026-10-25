import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  fmt,
  playApi,
  presetApi,
  type ActionResult,
  type Beatmap,
  type BeatmapSet,
  type Player,
  type PlayerProfile,
  type QueuedPlay,
  type ScoreSubmitResult,
  type SessionResult,
  type WeekResult,
  type TournamentList,
  worldApi,
} from '../api'
import { getLang, setLang, t, tx } from '../i18n'
import { ActivityLog } from './ActivityLog'
import { AttributePanel } from './AttributePanel'
import { BeatmapBrowser } from './BeatmapBrowser'
import { ForumPanel } from './ForumPanel'
import { PlayerAvatar } from './Avatar'
import { ChatPanel } from './ChatPanel'
import { useChat } from '../useChat'
import { searchApi } from '../api.search'
import { OPEN_DM, OPEN_NPC, type OpenNpc } from '../npcBus'
import { NpcProfile } from './NpcProfile'
import { SearchPalette } from './SearchPalette'
import { LifePanel } from './LifePanel'
import { PlayPanel, SessionQueue } from './PlayPanel'
import { QuickSession } from './QuickSession'
import { usePersisted } from '../usePersisted'
import { ScoreForm } from './ScoreForm'
import { SessionResults } from './SessionResults'
import { MatchBanner, TournamentsPanel } from './TournamentsPanel'
import { storyApi } from '../api.story'
import { LegacyPanel } from './LegacyPanel'
import { StoryPanel } from './StoryPanel'
import { TeamPanel } from './TeamPanel'
import { OsuProfile } from './OsuProfile'
import { TrainingPanel } from './TrainingPanel'
import { WeekPlanner } from './WeekPlanner'
import { WorldPanel } from './WorldPanel'
import { NotificationCenter } from './NotificationCenter'
import { QuickActions } from './QuickActions'

type Tab = 'profile' | 'training' | 'beatmaps' | 'tournaments' | 'world' | 'chat' | 'social' | 'story' | 'team' | 'life' | 'legacy'
const TAB_LABEL: Record<Tab, string> = {
  training: t('Training'),
  beatmaps: t('Play'),
  profile: t('Profile'),
  tournaments: t('Tournaments'),
  world: t('World'),
  chat: t('Chats'),
  social: t('Forum'),
  story: t('Story'),
  team: t('Team'),
  life: t('Life'),
  legacy: t('Legacy'),
}
const GROUPS: { key: string; label: string; icon: string; tabs: Tab[] }[] = [
  { key: 'career', label: t('Career'), icon: '🎯', tabs: ['training', 'beatmaps'] },
  { key: 'compete', label: t('Compete'), icon: '🏆', tabs: ['tournaments', 'world'] },
  { key: 'community', label: t('Chat & forum'), icon: '💬', tabs: ['chat', 'social'] },
  { key: 'me', label: t('Me'), icon: '🧑', tabs: ['profile', 'story', 'team', 'life', 'legacy'] },
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

export function Profile({ playerId, onExit }: { playerId: number; onExit: () => void }) {
  const [profile, setProfile] = useState<PlayerProfile | null>(null)
  const [lastResult, setLastResult] = useState<ScoreSubmitResult | null>(null)
  const [actionLog, setActionLog] = useState<ActionResult[]>([])
  const [tab, setTab] = useState<Tab>('training')
  const [selected, setSelected] = useState<{ beatmap: Beatmap; set: BeatmapSet } | null>(null)
  const [queue, setQueue] = useState<QueuedPlay[]>([])
  const [sessions, setSessions] = useState<
    { mode: 'auto' | 'manual'; result: SessionResult; replay?: { preset: string; hours: number; stream: boolean } }[]
  >([])
  const [sessionBusy, setSessionBusy] = useState(false)
  const [sessionError, setSessionError] = useState<string | null>(null)
  const [tournamentList, setTournamentList] = useState<TournamentList | null>(null)
  const [worldVersion, setWorldVersion] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [pendingEvents, setPendingEvents] = useState(0)
  const chat = useChat(playerId)
  const [searchOpen, setSearchOpen] = useState(false)
  const [npcView, setNpcView] = useState<{ id: number; compare: boolean } | null>(null)
  const [dmTarget, setDmTarget] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    const onNpc = (e: Event) => {
      const d = (e as CustomEvent<OpenNpc>).detail
      if (d.id != null) setNpcView({ id: d.id, compare: !!d.compare })
      else if (d.name)
        searchApi
          .byName(playerId, d.name)
          .then((r) => setNpcView({ id: r.id, compare: !!d.compare }))
          .catch(() => undefined)
    }
    const onDm = (e: Event) => {
      setDmTarget(`DM:${(e as CustomEvent<string>).detail}`)
      setTab('chat')
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener(OPEN_NPC, onNpc)
    window.addEventListener(OPEN_DM, onDm)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener(OPEN_NPC, onNpc)
      window.removeEventListener(OPEN_DM, onDm)
    }
  }, [playerId])
  useEffect(() => {
    playApi
      .history(playerId)
      .then((rows) =>
        setSessions((cur) =>
          cur.length
            ? cur
            : rows.map((r) => ({
                mode: r.mode,
                result: r.result,
                replay: r.preset ? { preset: r.preset, hours: r.hours ?? 2, stream: !!r.stream } : undefined,
              })),
        ),
      )
      .catch(() => undefined)
  }, [playerId])
  const [playMode, setPlayMode] = usePersisted<'auto' | 'manual'>('play.mode', 'auto')
  const resultsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (sessions.length) resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [sessions])

  const currentDate = profile?.in_game_date
  useEffect(() => {
    storyApi.pendingCount(playerId).then((r) => setPendingEvents(r.pending)).catch(() => setPendingEvents(0))
  }, [playerId, currentDate, worldVersion, tab])

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

  const onWeekLived = (week: WeekResult) => {
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
  }

  const pushSession = (
    mode: 'auto' | 'manual',
    result: SessionResult,
    replay?: { preset: string; hours: number; stream: boolean },
  ) => {
    setSessions((cur) => [{ mode, result, replay }, ...cur].slice(0, 12))
    setPlayMode(mode)
    setWorldVersion((v) => v + 1)
    void reload()
  }

  const playAgain = async (r: SessionResult) =>
    pushSession(
      'manual',
      await playApi.session(
        playerId,
        r.plays.map((p) => ({ beatmap_id: p.beatmap.beatmap_id, mods: p.mods === 'NM' ? '' : p.mods, attempts: p.attempts.length })),
      ),
    )

  const presetAgain = async (rp: { preset: string; hours: number; stream: boolean }) =>
    pushSession('auto', await presetApi.auto(playerId, rp.preset, rp.hours, rp.stream), rp)

  const form = formLabel(profile.form)

  const playSession = async () => {
    setSessionBusy(true)
    setSessionError(null)
    try {
      const result = await playApi.session(
        playerId,
        queue.map((q) => ({ beatmap_id: q.beatmap_id, mods: q.mods, attempts: q.attempts })),
      )
      setSessions((cur) => [{ mode: 'manual' as const, result }, ...cur].slice(0, 12))
      setQueue([])
      void reload()
    } catch (e) {
      setSessionError((e as Error).message)
    } finally {
      setSessionBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 pt-6 pb-24">
      {searchOpen && <SearchPalette playerId={playerId} dateKey={`${profile.in_game_date}:${worldVersion}`} onClose={() => setSearchOpen(false)} />}
      {npcView && (
        <NpcProfile
          key={`${npcView.id}:${npcView.compare}`}
          playerId={playerId}
          npcId={npcView.id}
          dateKey={`${profile.in_game_date}:${worldVersion}`}
          initialView={npcView.compare ? 'compare' : 'profile'}
          onClose={() => setNpcView(null)}
        />
      )}
      <header className="flex flex-wrap items-center gap-6 rounded-xl bg-panel p-5">
        <PlayerAvatar playerId={playerId} name={profile.name} size={88} editable />
        <div className="min-w-0 flex-1">
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
          <button
            onClick={() => setSearchOpen(true)}
            className="ml-3 rounded bg-panel-light px-1.5 text-xs text-muted hover:text-white"
            title={t('Search maps and players (Ctrl+K)')}
          >
            🔍 {t('Search')} <kbd className="text-[10px] opacity-70">⌘K</kbd>
          </button>
          <h1 className="text-3xl font-bold">
            {profile.name} <span className="text-lg text-muted">[{profile.country}]</span>
          </h1>
          <div className="text-sm text-muted">
            {profile.in_game_date} · {t(profile.era_label)}
            {profile.life && ` · ${t('{n}y', { n: profile.life.age ?? '?' })} · $${Math.round(profile.life.money).toLocaleString('en-US')}`}
          </div>
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
      <div className="-mt-3 flex flex-wrap items-center justify-between gap-2">
        <QuickActions
          player={profile}
          onAction={onAction}
          onWeek={onWeekLived}
          onSession={(result, replay) => {
            pushSession('auto', result, replay)
            setTab('beatmaps')
          }}
          onTab={(key) => setTab(key as Tab)}
        />
        <NotificationCenter
          playerId={playerId}
          refreshKey={`${profile.in_game_date}:${worldVersion}`}
          chatSummary={chat.summary}
          chatUnread={chat.unread}
          onOpenTab={(key) => setTab(key as Tab)}
          onChanged={() => {
            setWorldVersion((v) => v + 1)
            void reload()
          }}
        />
      </div>

      <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,2.2fr)]">
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

        <main className="min-w-0 space-y-6">
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
          <nav className="space-y-1.5">
            <div className="flex gap-1 rounded-full bg-panel p-1">
              {GROUPS.map((g) => {
                const active = g.tabs.includes(tab)
                const badge = g.key === 'me' ? pendingEvents : g.key === 'community' ? chat.unread.size : 0
                return (
                  <button
                    key={g.key}
                    onClick={() => !active && setTab(g.tabs[0])}
                    className={`flex flex-1 items-center justify-center gap-1.5 rounded-full py-1.5 text-sm font-semibold ${
                      active ? 'bg-osu-pink' : 'text-muted hover:text-white'
                    }`}
                  >
                    <span aria-hidden>{g.icon}</span>
                    {g.label}
                    {badge > 0 && <span className="rounded-full bg-white px-1.5 text-[10px] font-bold text-osu-pink">{badge}</span>}
                  </button>
                )
              })}
            </div>
            <div className="flex flex-wrap gap-1 px-1">
              {(GROUPS.find((g) => g.tabs.includes(tab)) ?? GROUPS[0]).tabs.map((key) => (
                <button
                  key={key}
                  onClick={() => setTab(key)}
                  className={`rounded-full px-3 py-1 text-xs font-semibold ${tab === key ? 'bg-panel-light text-white ring-1 ring-osu-pink' : 'text-muted hover:text-white'}`}
                >
                  {TAB_LABEL[key]}
                  {key === 'story' && pendingEvents > 0 && <span className="ml-1 text-osu-pink">●</span>}
                  {key === 'chat' && chat.unread.size > 0 && <span className="ml-1 text-osu-pink">●</span>}
                </button>
              ))}
            </div>
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
              <div className="flex gap-1 rounded-full bg-panel p-1 text-sm">
                {(
                  [
                    ['auto', t('Auto sessions')],
                    ['manual', t('Pick maps yourself')],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => setPlayMode(key)}
                    className={`flex-1 rounded-full py-1 font-semibold ${playMode === key ? 'bg-panel-light' : 'text-muted hover:text-white'}`}
                  >
                    {label}
                    {key === 'manual' && queue.length > 0 && (
                      <span className="ml-1.5 rounded-full bg-osu-pink px-1.5 text-[10px]">{queue.length}</span>
                    )}
                  </button>
                ))}
              </div>

              {playMode === 'auto' && (
                <QuickSession
                  playerId={playerId}
                  dateKey={profile.in_game_date}
                  disabledReason={profile.injury.state === 'severe_rsi' ? t('Forced hiatus: no playing') : null}
                  onPlayed={(result, replay) => {
                    setSessions((cur) => [{ mode: 'auto' as const, result, replay }, ...cur].slice(0, 12))
                    void reload()
                  }}
                />
              )}

              {playMode === 'manual' && queue.length > 0 && (
                <div className="sticky top-2 z-20 max-h-[60vh] overflow-y-auto rounded-xl shadow-lg shadow-black/40">
                  <SessionQueue
                    queue={queue}
                    busy={sessionBusy}
                    disabledReason={profile.injury.state === 'severe_rsi' ? t('Forced hiatus: no playing') : null}
                    onRemove={(i) => setQueue((cur) => cur.filter((_, j) => j !== i))}
                    onPlay={playSession}
                  />
                </div>
              )}
              {sessionError && <p className="text-sm text-red-400">{sessionError}</p>}

              <div ref={resultsRef} className="scroll-mt-16">
                {sessions
                  .filter((s) => s.mode === playMode)
                  .map((s, i) => (
                    <div key={`${s.result.date}-${i}-${s.result.plays.length}`} className={i ? 'mt-2' : ''}>
                      <SessionResults
                        result={s.result}
                        labels={labels}
                        playerId={playerId}
                        dateKey={profile.in_game_date}
                        defaultOpen={i === 0}
                        onPlayAgain={() => playAgain(s.result)}
                        onPresetAgain={s.replay ? () => presetAgain(s.replay!) : undefined}
                        presetLabel={s.replay ? t('Same preset ({h}h)', { h: s.replay.hours }) : undefined}
                      />
                    </div>
                  ))}
              </div>

              {playMode === 'manual' && (
                <div className="space-y-4">
                  <PlayPanel
                    playerId={playerId}
                    dateKey={profile.in_game_date}
                    selected={selected}
                    onQueue={(q) => setQueue((cur) => [...cur, q])}
                  />
                  <BeatmapBrowser
                    playerId={playerId}
                    before={profile.in_game_date}
                    selectedId={selected?.beatmap.id ?? null}
                    onSelect={(beatmap, set) => setSelected({ beatmap, set })}
                  />
                </div>
              )}
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

          {tab === 'legacy' && (
            <LegacyPanel
              playerId={playerId}
              playerName={profile.name}
              dateKey={`${profile.in_game_date}:${worldVersion}`}
              onChanged={() => void reload()}
            />
          )}

          {tab === 'profile' && <OsuProfile playerId={playerId} profile={profile} dateKey={`${profile.in_game_date}:${worldVersion}`} />}

          {tab === 'story' && (
            <StoryPanel playerId={playerId} dateKey={`${profile.in_game_date}:${worldVersion}`} onChanged={() => void reload()} />
          )}

          {tab === 'team' && (
            <TeamPanel playerId={playerId} dateKey={`${profile.in_game_date}:${worldVersion}`} onChanged={() => void reload()} />
          )}

          {tab === 'chat' && (
            <ChatPanel
              playerId={playerId}
              playerName={profile.name}
              summary={chat.summary}
              unread={chat.unread}
              markSeen={chat.markSeen}
              refresh={chat.refresh}
              initialChannel={dmTarget}
            />
          )}

          {tab === 'social' && <ForumPanel playerId={playerId} dateKey={`${profile.in_game_date}:${worldVersion}`} />}

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
