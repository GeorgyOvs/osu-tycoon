import { useMemo, useRef, useState } from 'react'
import { t } from '../i18n'

export interface Series {
  name: string
  color: string
  points: { date: string; value: number }[]
}

// Validated with the dataviz palette checker against the dark panel (#2a2226): both in band, CVD ΔE 10.8.
export const COMPARE_COLORS = ['#e8579e', '#3a94dc'] as const

const W = 640
const H = 180
const PAD = { l: 8, r: 72, t: 12, b: 20 }
const day = (d: string) => Date.parse(d) / 86_400_000

/** Two or more rank histories on one time axis (log scale, better rank = higher). Legend + direct end labels. */
export function CompareChart({ series, label }: { series: Series[]; label: string }) {
  const svg = useRef<SVGSVGElement>(null)
  const [hoverX, setHoverX] = useState<number | null>(null)
  const geo = useMemo(() => {
    const all = series.flatMap((s) => s.points)
    if (all.length < 2) return null
    const xs = all.map((p) => day(p.date))
    const x0 = Math.min(...xs)
    const x1 = Math.max(...xs)
    const vs = all.map((p) => Math.log10(Math.max(1, p.value)))
    let lo = Math.min(...vs)
    let hi = Math.max(...vs)
    if (hi - lo < 1e-9) {
      lo -= 0.5
      hi += 0.5
    }
    const x = (d: string) => PAD.l + ((day(d) - x0) / Math.max(1, x1 - x0)) * (W - PAD.l - PAD.r)
    const y = (v: number) => PAD.t + ((Math.log10(Math.max(1, v)) - lo) / (hi - lo)) * (H - PAD.t - PAD.b)
    const toDate = (px: number) => x0 + ((px - PAD.l) / (W - PAD.l - PAD.r)) * (x1 - x0)
    return { x, y, toDate, x0, x1 }
  }, [series])

  if (!geo) return <p className="text-xs text-muted">{t('Not enough history yet: play for a few days.')}</p>

  const nearest = (s: Series, d: number) =>
    s.points.reduce<Series['points'][number] | null>((best, p) => (best === null || Math.abs(day(p.date) - d) < Math.abs(day(best.date) - d) ? p : best), null)
  const hoverDay = hoverX != null ? geo.toDate(hoverX) : null
  const fmt = (v: number) => `#${Math.round(v).toLocaleString('en-US')}`

  return (
    <figure className="space-y-1">
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="uppercase tracking-wider text-muted">{label}</span>
        <span className="flex flex-wrap gap-3">
          {series.map((s) => (
            <span key={s.name} className="flex items-center gap-1.5">
              <span className="inline-block h-0.5 w-4 rounded" style={{ background: s.color }} />
              <span>{s.name}</span>
              {hoverDay != null && (() => {
                const p = nearest(s, hoverDay)
                return p ? <b className="tabular-nums">{fmt(p.value)}</b> : null
              })()}
            </span>
          ))}
        </span>
      </figcaption>
      <svg
        ref={svg}
        viewBox={`0 0 ${W} ${H}`}
        className="h-44 w-full touch-none select-none"
        role="img"
        aria-label={series.map((s) => `${s.name}: ${s.points.length ? fmt(s.points[s.points.length - 1].value) : '—'}`).join(', ')}
        onPointerMove={(e) => {
          const box = svg.current?.getBoundingClientRect()
          if (box) setHoverX(Math.max(PAD.l, Math.min(W - PAD.r, ((e.clientX - box.left) / box.width) * W)))
        }}
        onPointerLeave={() => setHoverX(null)}
      >
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={PAD.l} x2={W - PAD.r} y1={PAD.t + f * (H - PAD.t - PAD.b)} y2={PAD.t + f * (H - PAD.t - PAD.b)} stroke="#a3949b" strokeOpacity="0.12" />
        ))}
        {series.map((s) => {
          if (s.points.length < 1) return null
          const d = s.points.map((p, i) => `${i ? 'L' : 'M'}${geo.x(p.date).toFixed(1)},${geo.y(p.value).toFixed(1)}`).join('')
          const last = s.points[s.points.length - 1]
          return (
            <g key={s.name}>
              <path d={d} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
              <text x={geo.x(last.date) + 6} y={geo.y(last.value) + 3} fontSize="10" fill="#e5dfe2">
                {s.name.length > 10 ? `${s.name.slice(0, 9)}…` : s.name}
              </text>
            </g>
          )
        })}
        {hoverX != null && hoverDay != null && (
          <>
            <line x1={hoverX} x2={hoverX} y1={PAD.t} y2={H - PAD.b} stroke="#a3949b" strokeOpacity="0.5" strokeDasharray="3 3" />
            {series.map((s) => {
              const p = nearest(s, hoverDay)
              return p ? <circle key={s.name} cx={geo.x(p.date)} cy={geo.y(p.value)} r="4.5" fill={s.color} stroke="#2a2226" strokeWidth="2" /> : null
            })}
          </>
        )}
        <text x={PAD.l} y={H - 4} fontSize="10" fill="#a3949b">
          {new Date(geo.x0 * 86_400_000).toISOString().slice(0, 10)}
        </text>
        <text x={W - PAD.r} y={H - 4} fontSize="10" fill="#a3949b" textAnchor="end">
          {new Date(geo.x1 * 86_400_000).toISOString().slice(0, 10)}
        </text>
      </svg>
    </figure>
  )
}
