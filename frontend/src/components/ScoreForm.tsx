import { useEffect, useState, type FormEvent } from 'react'
import { api, fmt, type PlayInput, type PpResponse, type ScoreSubmitResult } from '../api'
import { t } from '../i18n'
import { PreviewButton } from './PreviewButton'

const MODS = ['EZ', 'NF', 'HT', 'HR', 'SD', 'DT', 'HD', 'FL'] as const
const CONFLICTS: Record<string, string[]> = {
  EZ: ['HR'],
  HR: ['EZ'],
  HT: ['DT'],
  DT: ['HT'],
  NF: ['SD'],
  SD: ['NF'],
}

interface Props {
  playerId: number
  onSubmitted: (result: ScoreSubmitResult) => void
  selectedBeatmapId?: number | null // picked in the beatmap browser
}

export function ScoreForm({ playerId, onSubmitted, selectedBeatmapId }: Props) {
  const [beatmapId, setBeatmapId] = useState('')
  const [mods, setMods] = useState<string[]>([])
  const [accuracy, setAccuracy] = useState('98')
  const [misses, setMisses] = useState('0')
  const [combo, setCombo] = useState('')
  const [preview, setPreview] = useState<PpResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const toggleMod = (m: string) =>
    setMods((cur) =>
      cur.includes(m) ? cur.filter((x) => x !== m) : [...cur.filter((x) => !CONFLICTS[m]?.includes(x)), m],
    )

  const input = (): PlayInput => ({
    beatmap_id: Number(beatmapId),
    mods: mods.join(''),
    accuracy: Number(accuracy),
    misses: Number(misses),
    ...(combo ? { combo: Number(combo) } : {}),
  })

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const calc = () => run(async () => setPreview(await api.calculatePp(input())))

  // Picking a difficulty in the browser fills the form and previews its PP right away.
  useEffect(() => {
    if (!selectedBeatmapId) return
    setBeatmapId(String(selectedBeatmapId))
    void run(async () => setPreview(await api.calculatePp({ ...input(), beatmap_id: selectedBeatmapId })))
    // only react to a new selection, not to every keystroke in the form
  }, [selectedBeatmapId])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      const result = await api.submitScore(playerId, input())
      setPreview(null)
      onSubmitted(result)
    })
  }

  const field = 'w-full rounded bg-bg px-3 py-2 outline-none focus:ring-2 focus:ring-osu-pink'

  return (
    <form onSubmit={submit} className="space-y-4 rounded-xl bg-panel p-5">
      <h2 className="text-sm uppercase tracking-wider text-muted">{t('Play a map')}</h2>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <label className="col-span-2 space-y-1 sm:col-span-1">
          <span className="text-xs text-muted">{t('Beatmap ID')}</span>
          <input
            required
            inputMode="numeric"
            pattern="\d+"
            placeholder="129891"
            value={beatmapId}
            onChange={(e) => setBeatmapId(e.target.value.trim())}
            className={field}
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted">{t('Accuracy %')}</span>
          <input
            required
            type="number"
            min={0}
            max={100}
            step={0.01}
            value={accuracy}
            onChange={(e) => setAccuracy(e.target.value)}
            className={field}
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted">{t('Misses')}</span>
          <input
            type="number"
            min={0}
            value={misses}
            onChange={(e) => setMisses(e.target.value)}
            className={field}
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted">{t('Combo (FC if empty)')}</span>
          <input type="number" min={0} value={combo} onChange={(e) => setCombo(e.target.value)} className={field} />
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        {MODS.map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => toggleMod(m)}
            className={`rounded-md px-3 py-1 text-sm font-bold ${
              mods.includes(m) ? 'bg-osu-pink text-white' : 'bg-panel-light text-muted hover:text-white'
            }`}
          >
            {m}
          </button>
        ))}
      </div>

      {preview && (
        <div className="flex items-center gap-3 rounded-lg bg-bg p-3">
          <PreviewButton beatmapsetId={preview.beatmap.beatmapset_id} artist={preview.beatmap.artist} title={preview.beatmap.title} />
          <div className="min-w-0 flex-1">
            <div className="truncate font-semibold">
              {preview.beatmap.artist} - {preview.beatmap.title}{' '}
              <span className="text-muted">[{preview.beatmap.version}]</span>
            </div>
            <div className="text-xs text-muted">
              {fmt.stars(preview.stars)} · {fmt.mods(preview.mods)} · AR {preview.ar.toFixed(1)} · OD{' '}
              {preview.od.toFixed(1)} · CS {preview.cs.toFixed(1)} · {Math.round(preview.bpm)} BPM · x
              {preview.max_combo}
            </div>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold text-osu-pink">{fmt.pp(preview.pp)}</div>
            <div className="text-xs text-muted">
              aim {Math.round(preview.pp_aim)} · spd {Math.round(preview.pp_speed)} · acc{' '}
              {Math.round(preview.pp_accuracy)}
            </div>
          </div>
        </div>
      )}

      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="flex gap-3">
        <button
          type="button"
          disabled={busy || !beatmapId}
          onClick={calc}
          className="flex-1 rounded-full bg-panel-light py-2 font-semibold hover:bg-bg disabled:opacity-50"
        >
          {t('Calculate PP')}
        </button>
        <button
          disabled={busy || !beatmapId}
          className="flex-1 rounded-full bg-osu-pink py-2 font-semibold hover:bg-osu-pink-dark disabled:opacity-50"
        >
          {t('Submit score')}
        </button>
      </div>
    </form>
  )
}
