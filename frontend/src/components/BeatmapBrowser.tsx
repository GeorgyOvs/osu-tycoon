import { useCallback, useEffect, useRef, useState } from 'react'
import {
  formatLength,
  searchBeatmaps,
  starColor,
  type Beatmap,
  type BeatmapSearch,
  type BeatmapSet,
  type BeatmapSort,
} from '../api'
import { t } from '../i18n'
import { PreviewButton } from './PreviewButton'

const PAGE = 30
const SORTS: [BeatmapSort, string][] = [
  ['ranked_desc', t('Newest ranked')],
  ['plays', t('Most played')],
  ['favourites', t('Most favourited')],
  ['stars_desc', t('Hardest')],
  ['stars_asc', t('Easiest')],
  ['ranked_asc', t('Oldest ranked')],
]

interface Props {
  before: string // the player's in-game date
  onSelect: (beatmap: Beatmap, set: BeatmapSet) => void
  selectedId: number | null
}

function DiffChip({ b, selected, onClick }: { b: Beatmap; selected: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      title={`${b.version}\n${b.stars.toFixed(2)}★ · AR${b.ar} OD${b.od} CS${b.cs} HP${b.hp} · ${Math.round(b.bpm)} BPM · ${formatLength(b.hit_length)}${b.max_combo ? ` · x${b.max_combo}` : ''}`}
      className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${
        selected ? 'bg-white text-bg' : 'bg-bg hover:bg-panel-light'
      }`}
    >
      <span className="font-bold" style={{ color: selected ? undefined : starColor(b.stars) }}>
        {b.stars.toFixed(1)}★
      </span>
      <span className="max-w-32 truncate">{b.version}</span>
    </button>
  )
}

export function BeatmapBrowser({ before, onSelect, selectedId }: Props) {
  const [q, setQ] = useState('')
  const [minStars, setMinStars] = useState('')
  const [maxStars, setMaxStars] = useState('')
  const [sort, setSort] = useState<BeatmapSort>('ranked_desc')
  const [data, setData] = useState<BeatmapSearch | null>(null)
  const [sets, setSets] = useState<BeatmapSet[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestId = useRef(0)

  const load = useCallback(
    async (offset: number) => {
      const id = ++requestId.current
      setLoading(true)
      setError(null)
      try {
        const res = await searchBeatmaps({
          before,
          q: q.trim(),
          min_stars: minStars ? Number(minStars) : undefined,
          max_stars: maxStars ? Number(maxStars) : undefined,
          sort,
          limit: PAGE,
          offset,
        })
        if (id !== requestId.current) return // a newer search superseded this one
        setData(res)
        setSets((cur) => (offset === 0 ? res.results : [...cur, ...res.results]))
      } catch (e) {
        if (id === requestId.current) setError((e as Error).message)
      } finally {
        if (id === requestId.current) setLoading(false)
      }
    },
    [before, q, minStars, maxStars, sort],
  )

  // Debounced search whenever filters change.
  useEffect(() => {
    const timer = setTimeout(() => void load(0), 300)
    return () => clearTimeout(timer)
  }, [load])

  // While the index is still catching up to the in-game date, refresh the first page.
  const incomplete = data != null && !data.complete
  useEffect(() => {
    if (!incomplete) return
    const timer = setInterval(() => void load(0), 4000)
    return () => clearInterval(timer)
  }, [incomplete, load])

  const field = 'rounded bg-bg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-osu-pink'

  return (
    <section className="space-y-3 rounded-xl bg-panel p-5">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Beatmaps ranked by {d}', { d: before })}</h2>
        {data && <span className="text-xs text-muted">{t('{n} sets', { n: data.total.toLocaleString('en-US') })}</span>}
      </div>

      <div className="flex flex-wrap gap-2">
        <input
          placeholder={t('Search artist, title, mapper, tags…')}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className={`${field} min-w-48 flex-1`}
        />
        <input
          type="number"
          min={0}
          step={0.5}
          placeholder={t('min ★')}
          value={minStars}
          onChange={(e) => setMinStars(e.target.value)}
          className={`${field} w-20`}
        />
        <input
          type="number"
          min={0}
          step={0.5}
          placeholder={t('max ★')}
          value={maxStars}
          onChange={(e) => setMaxStars(e.target.value)}
          className={`${field} w-20`}
        />
        <select value={sort} onChange={(e) => setSort(e.target.value as BeatmapSort)} className={field}>
          {SORTS.map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
      </div>

      {data && !data.complete && (
        <div className="rounded-lg bg-bg p-3 text-xs text-muted">
          {data.index.error ? (
            <span className="text-red-400">{t('Indexing failed')}: {data.index.error}</span>
          ) : (
            <>
              ⏳ {t('Indexing the ranked list from the mirror: reached')}{' '}
              <b className="text-white">{data.index.synced_until ?? t('the start')}</b>, {t('need')} {before} (
              {t('{n} sets so far', { n: data.index.indexed_sets.toLocaleString('en-US') })}). {t('Results fill in as it goes.')}
            </>
          )}
        </div>
      )}
      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="space-y-2">
        {sets.map((s) => (
          <div key={s.id} className="flex gap-3 rounded-lg bg-panel-light/60 p-2">
            <img src={s.cover_url} alt="" loading="lazy" className="h-16 w-16 shrink-0 rounded object-cover" />
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex items-center gap-2">
                <PreviewButton beatmapsetId={s.id} artist={s.artist} title={s.title} />
                <div className="min-w-0">
                  <div className="truncate font-semibold">{s.title}</div>
                  <div className="truncate text-xs text-muted">
                    {s.artist} · {t('mapped by')} {s.creator} · {s.ranked_date}
                    {s.status === 'approved' && <span className="text-sky-300"> · {t('approved')}</span>}
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap gap-1">
                {s.beatmaps.map((b) => (
                  <DiffChip key={b.id} b={b} selected={b.id === selectedId} onClick={() => onSelect(b, s)} />
                ))}
              </div>
            </div>
          </div>
        ))}
        {!loading && sets.length === 0 && data?.complete && (
          <p className="text-sm text-muted">{t('No maps match these filters.')}</p>
        )}
      </div>

      {data && sets.length < data.total && (
        <button
          disabled={loading}
          onClick={() => void load(sets.length)}
          className="w-full rounded-full bg-panel-light py-2 text-sm hover:bg-bg disabled:opacity-50"
        >
          {loading ? t('Loading…') : t('Load more')}
        </button>
      )}
      <p className="text-[11px] text-muted">
        {t("Star ratings come from the mirror and reflect today's difficulty algorithm. PP is calculated with osu!stable rules when you pick a difficulty.")}
      </p>
    </section>
  )
}
