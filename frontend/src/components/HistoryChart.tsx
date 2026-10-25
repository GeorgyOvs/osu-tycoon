import { useMemo, useRef, useState } from 'react'
import { t } from '../i18n'

type Point = { date: string; value: number }

const W = 640
const H = 150
const PAD = { l: 8, r: 8, t: 12, b: 20 }

/** A single-series history line (rank or pp) with a hover crosshair. Rank uses a log scale and is drawn upside down. */
export function HistoryChart({
  points,
  kind,
  label,
}: {
  points: Point[]
  kind: 'rank' | 'pp'
  label: string
}) {
  const [hover, setHover] = useState<number | null>(null)
  const svg = useRef<SVGSVGElement>(null)
  const geo = useMemo(() => {
    if (points.length < 2) return null
    const tf = (v: number) => (kind === 'rank' ? Math.log10(Math.max(1, v)) : v)
    const vs = points.map((p) => tf(p.value))
    let lo = Math.min(...vs)
    let hi = Math.max(...vs)
    if (hi - lo < 1e-9) {
      lo -= 1
      hi += 1
    }
    const x = (i: number) => PAD.l + (i / (points.length - 1)) * (W - PAD.l - PAD.r)
    // rank: smaller is better, so it goes up
    const y = (v: number) => {
      const n = (tf(v) - lo) / (hi - lo)
      return PAD.t + (kind === 'rank' ? n : 1 - n) * (H - PAD.t - PAD.b)
    }
    const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join('')
    const area = `${path}L${x(points.length - 1).toFixed(1)},${H - PAD.b}L${x(0).toFixed(1)},${H - PAD.b}Z`
    return { x, y, path, area }
  }, [points, kind])

  const fmtV = (v: number) => (kind === 'rank' ? `#${Math.round(v).toLocaleString('en-US')}` : `${Math.round(v).toLocaleString('en-US')}pp`)

  if (!geo) return <p className="text-xs text-muted">{t('Not enough history yet: play for a few days.')}</p>

  const onMove = (e: React.PointerEvent) => {
    const box = svg.current?.getBoundingClientRect()
    if (!box) return
    const rel = ((e.clientX - box.left) / box.width) * W
    const i = Math.round(((rel - PAD.l) / (W - PAD.l - PAD.r)) * (points.length - 1))
    setHover(Math.max(0, Math.min(points.length - 1, i)))
  }
  const h = hover != null ? points[hover] : null
  const last = points[points.length - 1]
  const gradId = `hist-${kind}`

  return (
    <figure className="space-y-1">
      <figcaption className="flex items-baseline justify-between text-xs">
        <span className="uppercase tracking-wider text-muted">{label}</span>
        <span className="font-semibold">{h ? `${fmtV(h.value)} · ${h.date}` : fmtV(last.value)}</span>
      </figcaption>
      <svg
        ref={svg}
        viewBox={`0 0 ${W} ${H}`}
        className="h-36 w-full touch-none select-none"
        role="img"
        aria-label={`${label}: ${fmtV(points[0].value)} → ${fmtV(last.value)}`}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#ff66aa" stopOpacity="0.25" />
            <stop offset="1" stopColor="#ff66aa" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={PAD.l} x2={W - PAD.r} y1={PAD.t + f * (H - PAD.t - PAD.b)} y2={PAD.t + f * (H - PAD.t - PAD.b)} stroke="#a3949b" strokeOpacity="0.12" />
        ))}
        <path d={geo.area} fill={`url(#${gradId})`} />
        <path d={geo.path} fill="none" stroke="#ff66aa" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {hover != null && h && (
          <>
            <line x1={geo.x(hover)} x2={geo.x(hover)} y1={PAD.t} y2={H - PAD.b} stroke="#a3949b" strokeOpacity="0.5" strokeDasharray="3 3" />
            <circle cx={geo.x(hover)} cy={geo.y(h.value)} r="4.5" fill="#ff66aa" stroke="#2a2226" strokeWidth="2" />
          </>
        )}
        <text x={PAD.l} y={H - 4} fontSize="10" fill="#a3949b">
          {points[0].date}
        </text>
        <text x={W - PAD.r} y={H - 4} fontSize="10" fill="#a3949b" textAnchor="end">
          {last.date}
        </text>
      </svg>
    </figure>
  )
}
