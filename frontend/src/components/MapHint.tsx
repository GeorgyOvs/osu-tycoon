import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { hintsApi, type MapHintData } from '../api.hints'
import { t, tx } from '../i18n'

const VERDICT_COLOR: Record<string, string> = {
  comfortable: 'text-green-300',
  passable: 'text-amber-300',
  over: 'text-red-400',
}
const BAR_COLOR: Record<string, string> = { comfortable: 'bg-green-400', passable: 'bg-amber-400', over: 'bg-red-400' }
const DELAY_MS = 250
const SCALE = 120

function Card({ data }: { data: MapHintData }) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-3 text-[11px] text-muted">
        <span>
          {data.stars.toFixed(2)}★ · {Math.round(data.bpm)} BPM · {Math.floor(data.length / 60)}:{String(data.length % 60).padStart(2, '0')}
          {data.mods !== 'NM' && ` · +${data.mods}`}
        </span>
        <span title={t('How precisely you can read maps: grows with plays, matches and skill')}>
          {t('Read')}: <b className="text-white">{data.precision_label}</b>
        </span>
      </div>
      {data.main_skills.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted">{t('Mainly tests')}</div>
          <ul className="text-sm">
            {data.main_skills.map((s, i) => (
              <li key={i}>• {s.detail}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="space-y-1">
        <div className="grid grid-cols-[4.5rem_1fr_auto] gap-x-2 text-[10px] uppercase tracking-wider text-muted">
          <span />
          <span>{t('needed: pass / comfortable · you')}</span>
          <span />
        </div>
        {data.dims.map((d) => (
          <div key={d.key} className="grid grid-cols-[4.5rem_1fr_auto] items-center gap-x-2 text-xs">
            <span className="text-muted">{d.label}</span>
            <div className="relative h-2.5 rounded-full bg-bg" aria-hidden>
              <div
                className="absolute inset-y-0 rounded-full bg-amber-400/30"
                style={{ left: `${(d.need_pass[0] / SCALE) * 100}%`, width: `${(Math.max(1, d.need_pass[1] - d.need_pass[0]) / SCALE) * 100}%` }}
              />
              <div
                className="absolute inset-y-0 rounded-full bg-green-400/30"
                style={{ left: `${(d.need_comfort[0] / SCALE) * 100}%`, width: `${(Math.max(1, d.need_comfort[1] - d.need_comfort[0]) / SCALE) * 100}%` }}
              />
              <div
                className={`absolute -top-0.5 h-3.5 w-1 rounded ${BAR_COLOR[d.verdict]}`}
                style={{ left: `calc(${(Math.min(SCALE, d.yours) / SCALE) * 100}% - 2px)` }}
              />
            </div>
            <span className={`w-28 text-right ${VERDICT_COLOR[d.verdict]}`}>
              {d.need_pass[0]}–{d.need_pass[1]} / {d.need_comfort[0]}–{d.need_comfort[1]} · {d.yours}
            </span>
          </div>
        ))}
        <div className="flex flex-wrap gap-x-3 text-[11px]">
          {data.dims
            .filter((d) => d.verdict !== 'comfortable')
            .map((d) => (
              <span key={d.key} className={VERDICT_COLOR[d.verdict]}>
                {d.label}: {d.verdict_label}
              </span>
            ))}
        </div>
      </div>
      {data.notes.length > 0 && (
        <ul className="space-y-0.5 text-[11px] text-muted">
          {data.notes.map((n, i) => (
            <li key={i}>※ {n}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Wrap any map label: hovering (or focusing / long-pressing) it shows what the map tests and what it needs from you. */
export function MapHint({
  playerId,
  beatmapId,
  mods = '',
  day = '',
  children,
  className = '',
}: {
  playerId: number
  beatmapId: number | null | undefined
  mods?: string
  day?: string
  children: React.ReactNode
  className?: string
}) {
  const anchor = useRef<HTMLSpanElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const timer = useRef<number | undefined>(undefined)
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<MapHintData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pos, setPos] = useState<{ left: number; top: number }>({ left: -9999, top: -9999 })

  useEffect(() => () => window.clearTimeout(timer.current), [])

  useEffect(() => {
    if (!open || !beatmapId) return
    let alive = true
    hintsApi
      .get(playerId, beatmapId, mods, day)
      .then((d) => alive && setData(d))
      .catch((e: Error) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [open, playerId, beatmapId, mods, day])

  useLayoutEffect(() => {
    if (!open || !anchor.current) return
    const a = anchor.current.getBoundingClientRect()
    const w = box.current?.offsetWidth ?? 340
    const h = box.current?.offsetHeight ?? 220
    const margin = 8
    let left = Math.min(Math.max(margin, a.left), window.innerWidth - w - margin)
    let top = a.bottom + 6
    if (top + h > window.innerHeight - margin) top = Math.max(margin, a.top - h - 6)
    left = Math.max(margin, left)
    setPos({ left, top })
  }, [open, data, error])

  if (!beatmapId) return <>{children}</>

  const show = () => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setOpen(true), DELAY_MS)
  }
  const hide = () => {
    window.clearTimeout(timer.current)
    setOpen(false)
  }

  return (
    <span
      ref={anchor}
      className={className}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onTouchStart={() => (open ? hide() : setOpen(true))}
    >
      {children}
      {open &&
        createPortal(
          <div
            ref={box}
            role="tooltip"
            className="pointer-events-none fixed z-[60] w-[22rem] max-w-[calc(100vw-1rem)] rounded-xl bg-panel/95 p-3 text-white shadow-2xl ring-1 ring-panel-light backdrop-blur"
            style={{ left: pos.left, top: pos.top }}
          >
            {data ? <Card data={data} /> : <p className="text-xs text-muted">{error ? tx(error) : t('Reading the map…')}</p>}
          </div>,
          document.body,
        )}
    </span>
  )
}
