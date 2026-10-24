import { useState } from 'react'
import type { AttributeGroup, SubStat } from '../api'
import { t } from '../i18n'

// Matches PLATEAU_SCALE in the engine: at this plateau training gains are halved.
const PLATEAU_SCALE = 60

function ratingColor(v: number) {
  if (v >= 90) return 'text-amber-300'
  if (v >= 75) return 'text-osu-pink'
  if (v >= 55) return 'text-sky-300'
  if (v >= 35) return 'text-green-300'
  return 'text-muted'
}

function SubRow({ sub }: { sub: SubStat }) {
  const gainEfficiency = 1 / (1 + sub.plateau / PLATEAU_SCALE)
  return (
    <div className="flex items-center gap-2 py-0.5 text-xs">
      <span className="flex-1 truncate text-muted">{t(sub.label)}</span>
      {gainEfficiency < 0.7 && (
        <span title={t('Plateau: training gains at {n}%', { n: Math.round(gainEfficiency * 100) })} className="text-orange-400">
          ▬
        </span>
      )}
      {sub.rust > 0 && (
        <span title={t('Rust from inactivity')} className="text-amber-600">
          -{sub.rust.toFixed(0)}
        </span>
      )}
      {sub.value < sub.base - sub.rust - 0.05 && (
        <span title={t('Reduced by injury or a lowered ceiling')} className="text-red-400">
          ✚
        </span>
      )}
      <span className={`w-7 text-right font-semibold ${ratingColor(sub.value)}`}>{Math.floor(sub.value)}</span>
      <span className="w-8 text-right text-[10px] text-muted" title={t('Ceiling')}>
        /{Math.floor(sub.cap)}
      </span>
    </div>
  )
}

export function AttributePanel({ groups, overall, ppPotential, tournamentStrength }: {
  groups: AttributeGroup[]
  overall: number
  ppPotential?: number
  tournamentStrength?: number
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({})

  return (
    <section className="rounded-xl bg-panel p-5">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Attributes')}</h2>
        <span className="text-sm text-muted">
          OVR <span className={`text-2xl font-bold ${ratingColor(overall)}`}>{Math.floor(overall)}</span>
        </span>
      </div>
      {ppPotential != null && tournamentStrength != null && (
        <div className="mb-3 grid grid-cols-2 gap-2 text-center text-xs">
          <div className="rounded bg-bg p-2 text-muted">
            {t('PP potential')} <b className={`ml-1 text-base ${ratingColor(ppPotential)}`}>{Math.floor(ppPotential)}</b>
          </div>
          <div className="rounded bg-bg p-2 text-muted">
            {t('Tournament strength')} <b className={`ml-1 text-base ${ratingColor(tournamentStrength)}`}>{Math.floor(tournamentStrength)}</b>
          </div>
        </div>
      )}
      <div className="space-y-1">
        {groups.map((g) => (
          <div key={g.key}>
            <button
              onClick={() => setOpen((o) => ({ ...o, [g.key]: !o[g.key] }))}
              className="flex w-full items-center gap-2 rounded px-1 py-1 text-left hover:bg-panel-light"
            >
              <span className="w-3 text-xs text-muted">{open[g.key] ? '▾' : '▸'}</span>
              <span className="flex-1 text-sm font-semibold">{t(g.label)}</span>
              <div className="h-1.5 w-20 rounded-full bg-bg">
                <div className="h-full rounded-full bg-osu-pink" style={{ width: `${Math.min(100, g.value)}%` }} />
              </div>
              <span className={`w-7 text-right font-bold ${ratingColor(g.value)}`}>{Math.floor(g.value)}</span>
            </button>
            {open[g.key] && (
              <div className="ml-5 border-l border-panel-light pl-2">
                {g.subs.map((s) => (
                  <SubRow key={s.key} sub={s} />
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
