import { useEffect, useMemo, useState } from 'react'
import { api, type ActionResult, type Drill, type Player } from '../api'
import { days as daysText, t } from '../i18n'

interface Props {
  player: Player
  onAction: (result: ActionResult) => void
}

const ERA_NAMES: Record<string, string> = {
  old_school: '2007+',
  competitive: '2012+',
  farm: '2016+',
  modern: '2021+',
}

export function TrainingPanel({ player, onAction }: Props) {
  const [drills, setDrills] = useState<Drill[]>([])
  const [drillKey, setDrillKey] = useState('')
  const [hours, setHours] = useState(4)
  const [days, setDays] = useState(7)
  const [restDays, setRestDays] = useState(2)
  const [physio, setPhysio] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const labels = useMemo(
    () => Object.fromEntries(player.attributes.flatMap((g) => g.subs.map((s) => [s.key, t(s.label)]))),
    [player.attributes],
  )

  // Drill availability depends on the era, which changes as the calendar moves.
  useEffect(() => {
    api.listDrills(player.id).then((list) => {
      setDrills(list)
      setDrillKey((cur) => (list.some((d) => d.key === cur && d.available) ? cur : (list.find((d) => d.available)?.key ?? '')))
    })
  }, [player.id, player.era])

  const run = async (fn: () => Promise<ActionResult>) => {
    setBusy(true)
    setError(null)
    try {
      onAction(await fn())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const drill = drills.find((d) => d.key === drillKey)
  const hiatus = player.injury.state === 'severe_rsi'

  return (
    <section className="space-y-4 rounded-xl bg-panel p-5">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Training')}</h2>
        <span className="text-xs text-muted">{t(player.era_label)}</span>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {drills.map((d) => (
          <button
            key={d.key}
            disabled={!d.available}
            onClick={() => setDrillKey(d.key)}
            title={d.available ? t(d.description) : t('Not available yet ({era})', { era: ERA_NAMES[d.available_from] })}
            className={`rounded-lg px-3 py-2 text-left text-sm ${
              d.key === drillKey
                ? 'bg-osu-pink/25 ring-1 ring-osu-pink'
                : d.available
                  ? 'bg-panel-light hover:bg-bg'
                  : 'cursor-not-allowed bg-bg/50 text-muted/50'
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold">{t(d.label)}</span>
              {!d.available && <span className="text-[10px]">🔒 {ERA_NAMES[d.available_from]}</span>}
              {d.available && d.strain >= 1.3 && (
                <span className="text-[10px] text-red-400" title={t('High strain: RSI risk')}>
                  ⚠ {t('strain')}
                </span>
              )}
              {d.available && d.sets_scores && (
                <span className="text-[10px] text-osu-pink" title={t('Plays ranked maps: sets real scores and pp')}>
                  🎯
                </span>
              )}
              {d.available && d.efficiency > 1 && (
                <span className="text-[10px] text-green-400" title={t('Era bonus')}>
                  ×{d.efficiency}
                </span>
              )}
            </div>
          </button>
        ))}
      </div>

      {drill && (
        <div className="rounded-lg bg-bg p-3 text-xs">
          <p className="mb-2 text-muted">{t(drill.description)}</p>
          <div className="flex flex-wrap gap-1">
            {Object.entries(drill.targets)
              .sort((a, b) => b[1] - a[1])
              .map(([k, share]) => (
                <span key={k} className="rounded bg-panel-light px-2 py-0.5" style={{ opacity: 0.5 + share / 2 }}>
                  {labels[k] ?? k}
                </span>
              ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 text-sm">
        <label className="space-y-1">
          <span className="text-xs text-muted">{t('Hours per day: {n}h', { n: hours })}</span>
          <input
            type="range"
            min={1}
            max={14}
            step={0.5}
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            className="w-full accent-osu-pink"
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted">{t('Days')}: {days}</span>
          <input
            type="range"
            min={1}
            max={30}
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="w-full accent-osu-pink"
          />
        </label>
      </div>

      <button
        disabled={busy || !drill || hiatus}
        onClick={() => run(() => api.train(player.id, { drill: drillKey, hours_per_day: hours, days }))}
        className="w-full rounded-full bg-osu-pink py-2 font-semibold hover:bg-osu-pink-dark disabled:opacity-50"
      >
        {hiatus ? t('Forced hiatus: rest only') : t('Train for {days}', { days: daysText(days) })}
      </button>

      <div className="flex items-center gap-3 border-t border-panel-light pt-4 text-sm">
        <input
          type="number"
          min={1}
          max={120}
          value={restDays}
          onChange={(e) => setRestDays(Math.max(1, Number(e.target.value)))}
          className="w-16 rounded bg-bg px-2 py-1.5 text-center outline-none focus:ring-2 focus:ring-osu-pink"
        />
        <span className="text-muted">{t('days off')}</span>
        <label className="flex items-center gap-1.5 text-muted">
          <input type="checkbox" checked={physio} onChange={(e) => setPhysio(e.target.checked)} className="accent-osu-pink" />
          {t('physiotherapy')}
        </label>
        <button
          disabled={busy}
          onClick={() => run(() => api.rest(player.id, { days: restDays, physio }))}
          className="ml-auto rounded-full bg-panel-light px-5 py-1.5 font-semibold hover:bg-bg disabled:opacity-50"
        >
          {t('Rest')}
        </button>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}
    </section>
  )
}
