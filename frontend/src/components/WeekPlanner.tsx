import { useEffect, useMemo, useRef, useState } from 'react'
import { api, presetApi, weekApi, type Drill, type Player, type SessionPreset, type WeekDay, type WeekResult } from '../api'
import { locale, statLabel, t, tx } from '../i18n'

const STORAGE_KEY = 'tycoon.weekPlan'

function defaultPlan(occupation: string): WeekDay[] {
  const weekday: WeekDay = occupation === 'pro'
    ? { type: 'train', drill: 'ranked_pack_grind', hours: 5 }
    : { type: 'train', drill: 'ranked_pack_grind', hours: 2 }
  return [
    weekday,
    { ...weekday, drill: 'tech_maps' },
    { type: 'session', preset: 'farm', hours: occupation === 'pro' ? 5 : 2 },
    { ...weekday, drill: 'watch_replays' },
    { type: 'rest' },
    { type: 'session', preset: 'push', hours: occupation === 'pro' ? 6 : 4 },
    { type: 'rest' },
  ]
}

interface Props {
  player: Player
  onLived: (result: WeekResult) => void
}

export function WeekPlanner({ player, onLived }: Props) {
  const [drills, setDrills] = useState<Drill[]>([])
  const [presets, setPresets] = useState<SessionPreset[]>([])
  const [plan, setPlan] = useState<WeekDay[]>(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? JSON.parse(saved) : defaultPlan(player.life?.occupation ?? 'school')
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<WeekResult | null>(null)
  const summaryRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (result) summaryRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' })
  }, [result])

  useEffect(() => {
    api.listDrills(player.id).then(setDrills)
    presetApi.list(player.id).then(setPresets)
  }, [player.id, player.era])

  useEffect(() => localStorage.setItem(STORAGE_KEY, JSON.stringify(plan)), [plan])

  const dates = useMemo(() => {
    const start = new Date(player.in_game_date + 'T00:00:00')
    return plan.map((_, i) => {
      const d = new Date(start)
      d.setDate(d.getDate() + i)
      // Local date parts: toISOString() would shift the day for anyone east of UTC.
      const mm = String(d.getMonth() + 1).padStart(2, '0')
      const dd = String(d.getDate()).padStart(2, '0')
      return `${d.toLocaleDateString(locale(), { weekday: 'short' })} ${mm}-${dd}`
    })
  }, [player.in_game_date, plan])

  const update = (i: number, patch: Partial<WeekDay>) => setPlan((p) => p.map((d, j) => (j === i ? { ...d, ...patch } : d)))
  const setType = (i: number, type: WeekDay['type']) =>
    update(i, type === 'train' ? { type, drill: drills.find((d) => d.available)?.key, hours: 2 }
      : type === 'session' ? { type, preset: 'farm', hours: 2 } : { type, hours: 0 })

  const live = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await weekApi.live(player.id, plan)
      setResult(r)
      onLived(r)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const field = 'rounded bg-bg px-2 py-1 text-sm outline-none focus:ring-2 focus:ring-osu-pink'
  const totalHours = plan.reduce((s, d) => s + (d.type === 'rest' ? 0 : d.hours ?? 0), 0)

  return (
    <section className="space-y-3 rounded-xl bg-panel p-5">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Plan the week')}</h2>
        <span className="text-xs text-muted">
          {t('{n}h planned', { n: totalHours })} · {t('free time today {n}h', { n: player.life?.free_hours_today ?? '?' })}
        </span>
      </div>
      <div className="space-y-1">
        {plan.map((d, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <span className="w-20 text-xs text-muted">{dates[i]}</span>
            <select value={d.type} onChange={(e) => setType(i, e.target.value as WeekDay['type'])} className={field}>
              <option value="train">{t('Train')}</option>
              <option value="session">{t('Play')}</option>
              <option value="rest">{t('Rest')}</option>
            </select>
            {d.type === 'train' && (
              <select value={d.drill} onChange={(e) => update(i, { drill: e.target.value })} className={`${field} flex-1`}>
                {drills.filter((x) => x.available).map((x) => (
                  <option key={x.key} value={x.key}>
                    {t(x.label)}
                    {x.sets_scores ? ' 🎯' : ''}
                  </option>
                ))}
              </select>
            )}
            {d.type === 'session' && (
              <>
                <select value={d.preset} onChange={(e) => update(i, { preset: e.target.value })} className={`${field} flex-1`}>
                  {presets.filter((x) => x.available).map((x) => (
                    <option key={x.key} value={x.key}>
                      {t(x.label)}
                    </option>
                  ))}
                </select>
                <label className="flex items-center gap-1 text-xs text-muted">
                  <input type="checkbox" checked={!!d.stream} onChange={(e) => update(i, { stream: e.target.checked })} className="accent-osu-pink" />
                  {t('stream')}
                </label>
              </>
            )}
            {d.type === 'rest' ? (
              <label className="flex items-center gap-1 text-xs text-muted">
                <input type="checkbox" checked={!!d.physio} onChange={(e) => update(i, { physio: e.target.checked })} className="accent-osu-pink" />
                {t('physio ($30)')}
              </label>
            ) : (
              <input
                type="number"
                min={0.5}
                max={14}
                step={0.5}
                value={d.hours ?? 2}
                onChange={(e) => update(i, { hours: Number(e.target.value) })}
                className={`${field} w-16`}
                title={t('Hours')}
              />
            )}
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <button
          disabled={busy}
          onClick={live}
          className="flex-1 rounded-full bg-osu-pink py-2 font-semibold hover:bg-osu-pink-dark disabled:opacity-50"
        >
          {busy ? t('Living the week…') : t('Live this week')}
        </button>
        <button
          onClick={() => setPlan(defaultPlan(player.life?.occupation ?? 'school'))}
          className="rounded-full bg-panel-light px-4 text-sm hover:bg-bg"
        >
          {t('Reset')}
        </button>
      </div>
      {busy && (
        <p className="text-xs text-muted">
          {t('Simulating every day, session and match… a week with play sessions takes a few seconds (longer the first time new maps are downloaded).')}
        </p>
      )}
      {error && <p className="text-sm text-red-400">{error}</p>}
      <div ref={summaryRef}>{result && <WeekSummary result={result} />}</div>
    </section>
  )
}

function WeekSummary({ result }: { result: WeekResult }) {
  const top = Object.entries(result.deltas).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 6)
  const best = result.scores.reduce((m, s) => Math.max(m, s.pp), 0)
  return (
    <div className="space-y-2 rounded-lg bg-bg p-3 text-sm">
      <div className="text-xs text-muted">
        {result.start_date} → {result.end_date} · {t('{n} scores', { n: result.scores.length })}
        {best ? `, ${t('best')} ${Math.round(best)}pp` : ''} · {result.money_change >= 0 ? '+' : ''}${Math.round(result.money_change)} ·{' '}
        {result.followers_change >= 0 ? '+' : ''}
        {result.followers_change} {t('followers')}
      </div>
      {result.stopped_early && <div className="text-amber-300">{t('Stopped early')}: {tx(result.stopped_early)}</div>}
      <ul className="space-y-0.5 text-xs">
        {result.days.map((d, i) => (
          <li key={i} className={d.ok ? '' : 'text-amber-300'}>
            <span className="text-muted">{d.date}</span> {tx(d.summary)}
            {d.events
              .filter((e) => !e.type.startsWith('WORLD_'))
              .slice(0, 2)
              .map((e, j) => (
                <span key={j} className="text-muted"> · {tx(e.message)}</span>
              ))}
          </li>
        ))}
      </ul>
      {top.length > 0 && (
        <div className="flex flex-wrap gap-1 text-xs">
          {top.map(([k, v]) => (
            <span key={k} className={`rounded px-1.5 ${v > 0 ? 'bg-green-900/40 text-green-300' : 'bg-red-900/40 text-red-300'}`}>
              {statLabel(k)} {v > 0 ? '+' : ''}
              {v.toFixed(2)}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
