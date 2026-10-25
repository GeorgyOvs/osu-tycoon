import { useCallback, useEffect, useState } from 'react'
import { storyApi, type EventsOverview, type Goal, type GoalsOverview, type LifeEvent, type StoryArc } from '../api.story'
import { STAT_LABELS } from '../i18n.keys'
import { t, tx } from '../i18n'

const CATEGORY_LABEL: Record<string, string> = {
  family: t('Family'),
  school: t('School'),
  work: t('Work'),
  health: t('Health'),
  gear: t('Gear'),
  community: t('Community'),
  fame: t('Fame'),
}

const CATEGORY_COLOR: Record<string, string> = {
  family: 'bg-sky-900 text-sky-200',
  school: 'bg-indigo-900 text-indigo-200',
  work: 'bg-amber-900 text-amber-200',
  health: 'bg-red-900 text-red-200',
  gear: 'bg-slate-700 text-slate-200',
  community: 'bg-emerald-900 text-emerald-200',
  fame: 'bg-fuchsia-900 text-fuchsia-200',
}

const signed = (n: number, digits = 0) => `${n > 0 ? '+' : ''}${n.toFixed(digits)}`

function Chip({ children, good }: { children: React.ReactNode; good: boolean | null }) {
  const tone = good === null ? 'bg-panel-light text-muted' : good ? 'bg-green-900 text-green-200' : 'bg-red-900 text-red-200'
  return <span className={`rounded px-1.5 py-0.5 text-[11px] ${tone}`}>{children}</span>
}

export function AppliedChips({ applied }: { applied: LifeEvent['applied'] }) {
  const chips: React.ReactNode[] = []
  if (applied.motivation) chips.push(<Chip key="mo" good={applied.motivation > 0}>{t('Motivation')} {signed(applied.motivation)}</Chip>)
  if (applied.morale) chips.push(<Chip key="mr" good={applied.morale > 0}>{t('Morale')} {signed(applied.morale)}</Chip>)
  if (applied.fatigue) chips.push(<Chip key="fa" good={applied.fatigue < 0}>{t('Fatigue')} {signed(applied.fatigue)}</Chip>)
  if (applied.form) chips.push(<Chip key="fo" good={applied.form > 0}>{t('Form')} {signed(applied.form, 1)}</Chip>)
  if (applied.money) chips.push(<Chip key="mn" good={applied.money > 0}>{applied.money > 0 ? '+' : '−'}${Math.abs(applied.money)}</Chip>)
  if (applied.followers) chips.push(<Chip key="fl" good={applied.followers > 0}>{t('Followers')} {signed(applied.followers)}</Chip>)
  for (const [key, gain] of Object.entries(applied.skill ?? {})) {
    chips.push(<Chip key={`sk${key}`} good>{t(STAT_LABELS[key] ?? key)} {signed(gain, 1)}</Chip>)
  }
  if (applied.reputation) chips.push(<Chip key="rp" good={applied.reputation > 0}>{t('Reputation')} {signed(applied.reputation, 1)}</Chip>)
  if (applied.rival_heat) chips.push(<Chip key="rh" good={null}>{t('Rivalry')} {signed(applied.rival_heat)}</Chip>)
  if (applied.injury) chips.push(<Chip key="in" good={false}>{t('Wrist strain')}</Chip>)
  if (applied.mod) chips.push(<Chip key="md" good={null}>{applied.mod.label}</Chip>)
  return chips.length ? <div className="flex flex-wrap gap-1">{chips}</div> : null
}

function daysBetween(from: string, to: string | null) {
  if (!to) return null
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000)
}

function EventCard({ event, today, busy, onChoose }: { event: LifeEvent; today: string; busy: boolean; onChoose: (choice: string) => void }) {
  const left = daysBetween(today, event.expires_on)
  const fallback = event.options.find((o) => o.key === event.default)
  return (
    <article className="space-y-2 rounded-xl bg-panel p-4 ring-1 ring-osu-pink/40">
      <div className="flex items-center gap-2">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${CATEGORY_COLOR[event.category] ?? 'bg-panel-light'}`}>
          {CATEGORY_LABEL[event.category] ?? event.category}
        </span>
        <h3 className="flex-1 font-semibold">{event.title}</h3>
        {left != null && (
          <span className="text-xs text-muted">
            {left > 0 ? t('decide within {n} d', { n: left }) : t('decide today')}
          </span>
        )}
      </div>
      <p className="text-sm text-slate-200">{event.body}</p>
      <div className="flex flex-wrap gap-2">
        {event.options.map((o) => (
          <button
            key={o.key}
            disabled={busy}
            onClick={() => onChoose(o.key)}
            title={o.hint}
            className="rounded-full bg-panel-light px-3 py-1.5 text-sm hover:bg-osu-pink disabled:opacity-50"
          >
            {o.label}
            {o.hint && <span className="ml-1.5 text-xs text-muted">· {o.hint}</span>}
          </button>
        ))}
      </div>
      {fallback && event.options.length > 1 && (
        <p className="text-xs text-muted">{t('If you do nothing: {option}', { option: fallback.label })}</p>
      )}
    </article>
  )
}

function EventHistoryRow({ event }: { event: LifeEvent }) {
  const chosen = event.options.find((o) => o.key === event.choice)
  return (
    <div className="space-y-1 rounded-lg bg-panel px-3 py-2 text-sm">
      <div className="flex items-center gap-2">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${CATEGORY_COLOR[event.category] ?? 'bg-panel-light'}`}>
          {CATEGORY_LABEL[event.category] ?? event.category}
        </span>
        <span className="flex-1 font-medium">{event.title}</span>
        <span className="text-xs text-muted">{event.created_on}</span>
      </div>
      <div className="text-xs text-muted">
        {event.auto ? t('Time ran out: {option}', { option: chosen?.label ?? '' }) : t('You chose: {option}', { option: chosen?.label ?? '' })}
        {event.outcome && ` — ${event.outcome}`}
      </div>
      <AppliedChips applied={event.applied} />
    </div>
  )
}

function GoalRow({ goal, onDrop }: { goal: Goal; onDrop?: () => void }) {
  const done = goal.status === 'done'
  const bar = done ? 'bg-green-500' : goal.status === 'active' ? 'bg-osu-pink' : 'bg-slate-600'
  return (
    <div className="space-y-1.5 rounded-lg bg-panel px-3 py-2.5">
      <div className="flex items-center gap-2">
        <span className="flex-1 font-medium">{goal.title}</span>
        {goal.status === 'active' && goal.days_left != null && (
          <span className="text-xs text-muted">{t('{n} d left', { n: Math.max(0, goal.days_left) })}</span>
        )}
        {done && <span className="text-xs text-green-400">{t('Done')} · {goal.finished_on}</span>}
        {(goal.status === 'failed' || goal.status === 'dropped') && (
          <span className="text-xs text-muted">{goal.status === 'failed' ? t('Missed') : t('Dropped')}</span>
        )}
        {onDrop && (
          <button onClick={onDrop} className="text-xs text-muted hover:text-white" title={t('Drop this goal')}>
            ✕
          </button>
        )}
      </div>
      <p className="text-xs text-muted">{goal.description}</p>
      <div className="h-1.5 rounded-full bg-bg">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${Math.round(goal.progress * 100)}%` }} />
      </div>
      <div className="flex flex-wrap items-center gap-1 text-[11px] text-muted">
        <span>{t('Reward')}:</span>
        {goal.reward.money ? <Chip good>${goal.reward.money}</Chip> : null}
        {goal.reward.motivation ? <Chip good>{t('Motivation')} +{goal.reward.motivation}</Chip> : null}
        {goal.reward.followers ? <Chip good>{t('Followers')} +{goal.reward.followers}</Chip> : null}
        {goal.inspired && <Chip good={null}>{t('Inspiration')}</Chip>}
      </div>
    </div>
  )
}

function ArcCard({ arc }: { arc: StoryArc }) {
  const active = arc.status === 'active'
  return (
    <div className={`space-y-2 rounded-xl bg-panel p-3 ${active ? 'ring-1 ring-osu-pink/40' : ''}`}>
      <div className="flex items-center gap-2">
        <h3 className="flex-1 font-semibold">{arc.title}</h3>
        <span className="text-xs text-muted">
          {active ? t('in progress since {d}', { d: arc.started_on }) : `${arc.started_on} → ${arc.ended_on}`}
        </span>
      </div>
      <ol className="space-y-1 border-l border-panel-light pl-3">
        {arc.chapters.map((c, i) => (
          <li key={i} className="text-sm">
            <span className="mr-2 text-xs text-muted">{c.date}</span>
            {c.text}
          </li>
        ))}
      </ol>
    </div>
  )
}

export function StoryPanel({ playerId, dateKey, onChanged }: { playerId: number; dateKey: string; onChanged: () => void }) {
  const [events, setEvents] = useState<EventsOverview | null>(null)
  const [goals, setGoals] = useState<GoalsOverview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const today = dateKey.split(':')[0]

  const load = useCallback(() => {
    Promise.all([storyApi.events(playerId), storyApi.goals(playerId)])
      .then(([e, g]) => {
        setEvents(e)
        setGoals(g)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [playerId])
  useEffect(load, [load, dateKey])

  const choose = async (event: LifeEvent, choice: string) => {
    setBusy(true)
    try {
      await storyApi.choose(playerId, event.id, choice)
      load()
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const drop = async (goal: Goal) => {
    try {
      setGoals(await storyApi.dropGoal(playerId, goal.id))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (!events || !goals) return <p className="text-sm text-muted">{error ? tx(error) : t('Loading…')}</p>

  return (
    <div className="space-y-6">
      {error && <p className="text-sm text-red-400">{tx(error)}</p>}

      <section className="space-y-2">
        <h2 className="text-sm uppercase tracking-wider text-muted">
          {t('Decisions')} ({events.pending.length})
        </h2>
        {events.pending.length === 0 && <p className="text-sm text-muted">{t('Nothing needs your attention right now.')}</p>}
        {events.pending.map((e) => (
          <EventCard key={e.id} event={e} today={today} busy={busy} onChoose={(c) => void choose(e, c)} />
        ))}
        {events.effects.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 pt-1 text-xs text-muted">
            <span>{t('Active effects')}:</span>
            {events.effects.map((fx, i) => (
              <Chip key={i} good={null}>
                {fx.label} · {t('{n} d left', { n: Math.max(0, fx.days_left) })}
                {fx.free_hours ? ` · ${signed(fx.free_hours, 1)}${t('h')}` : ''}
              </Chip>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Goals')}</h2>
        {goals.active.length === 0 && <p className="text-sm text-muted">{t('No goals right now.')}</p>}
        {goals.active.map((g) => (
          <GoalRow key={g.id} goal={g} onDrop={() => void drop(g)} />
        ))}
        {goals.finished.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-muted hover:text-white">
              {t('Finished goals')} ({goals.finished.length})
            </summary>
            <div className="mt-2 space-y-2">
              {goals.finished.map((g) => (
                <GoalRow key={g.id} goal={g} />
              ))}
            </div>
          </details>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Story arcs')}</h2>
        {goals.arcs.length === 0 && <p className="text-sm text-muted">{t('No storylines yet. Your career is just getting started.')}</p>}
        {goals.arcs.map((a) => (
          <ArcCard key={a.id} arc={a} />
        ))}
      </section>

      <section className="space-y-2">
        <button onClick={() => setShowHistory((v) => !v)} className="text-sm uppercase tracking-wider text-muted hover:text-white">
          {t('Recent events')} ({events.history.length}) {showHistory ? '▾' : '▸'}
        </button>
        {showHistory && events.history.map((e) => <EventHistoryRow key={e.id} event={e} />)}
        {showHistory && events.history.length === 0 && (
          <p className="text-sm text-muted">{t('Nothing has happened yet.')}</p>
        )}
      </section>
    </div>
  )
}
