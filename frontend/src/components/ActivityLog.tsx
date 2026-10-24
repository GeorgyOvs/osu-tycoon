import type { ActionResult, GameEvent } from '../api'
import { t, tx } from '../i18n'

const EVENT_STYLE: Record<string, { icon: string; color: string }> = {
  BREAKTHROUGH: { icon: '✦', color: 'text-amber-300' },
  MILESTONE: { icon: '▲', color: 'text-green-400' },
  FORM_PEAK: { icon: '🔥', color: 'text-orange-300' },
  FORM_SLUMP: { icon: '☁', color: 'text-slate-400' },
  RUST: { icon: '⚙', color: 'text-amber-600' },
  INJURY_MINOR_STRAIN: { icon: '✚', color: 'text-orange-400' },
  INJURY_SEVERE_RSI: { icon: '✚', color: 'text-red-500' },
  INJURY_RECOVERED: { icon: '✓', color: 'text-green-400' },
  PERMANENT_DAMAGE: { icon: '✖', color: 'text-red-500' },
  TRAINING_INTERRUPTED: { icon: '■', color: 'text-red-400' },
}

function EventRow({ event }: { event: GameEvent }) {
  const style = EVENT_STYLE[event.type] ?? (event.type.startsWith('WORLD_') ? { icon: '🌐', color: 'text-sky-300' } : { icon: '•', color: 'text-muted' })
  return (
    <li className="flex gap-2 text-sm">
      <span className="w-20 shrink-0 text-xs text-muted">{event.date}</span>
      <span className={`w-4 shrink-0 text-center ${style.color}`}>{style.icon}</span>
      <span>{tx(event.message)}</span>
    </li>
  )
}

export function ActivityLog({ log, labels }: { log: ActionResult[]; labels: Record<string, string> }) {
  if (log.length === 0) return null
  const [latest, ...older] = log
  const topDeltas = Object.entries(latest.deltas)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 8)

  return (
    <section className="space-y-3 rounded-xl bg-panel p-5">
      <h2 className="text-sm uppercase tracking-wider text-muted">
        {t('Last action')} · {latest.start_date} → {latest.end_date} ({t('{n}d', { n: latest.days })})
      </h2>
      {latest.scores && latest.scores.length > 0 && (
        <div className="text-xs">
          <span className="text-muted">{t('Scores set while practising')}: </span>
          {latest.scores.length} · {t('best')}{' '}
          <b className="text-osu-pink">{Math.round(Math.max(...latest.scores.map((s) => s.pp)))}pp</b> —{' '}
          {[...latest.scores].sort((a, b) => b.pp - a.pp)[0].title}
        </div>
      )}
      {topDeltas.length > 0 && (
        <div className="flex flex-wrap gap-1.5 text-xs">
          {topDeltas.map(([k, d]) => (
            <span key={k} className={`rounded px-2 py-0.5 ${d > 0 ? 'bg-green-900/40 text-green-300' : 'bg-red-900/40 text-red-300'}`}>
              {labels[k] ?? k} {d > 0 ? '+' : ''}
              {d.toFixed(2)}
            </span>
          ))}
        </div>
      )}
      <ul className="max-h-64 space-y-1 overflow-y-auto">
        {[latest, ...older].flatMap((r) => r.events).length === 0 && (
          <li className="text-sm text-muted">{t('Nothing notable happened.')}</li>
        )}
        {[latest, ...older].flatMap((r, i) =>
          [...r.events].reverse().map((e, j) => <EventRow key={`${i}-${j}`} event={e} />),
        )}
      </ul>
    </section>
  )
}
