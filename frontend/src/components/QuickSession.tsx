import { useEffect, useState } from 'react'
import { usePersisted } from '../usePersisted'
import { presetApi, type SessionPreset, type SessionResult } from '../api'
import { t } from '../i18n'

interface Props {
  playerId: number
  dateKey: string
  disabledReason: string | null
  onPlayed: (result: SessionResult, replay: { preset: string; hours: number; stream: boolean }) => void
}

/** A day of playing without hand-picking maps: the engine chooses around your level. */
export function QuickSession({ playerId, dateKey, disabledReason, onPlayed }: Props) {
  const [presets, setPresets] = useState<SessionPreset[]>([])
  const [selected, setSelected] = usePersisted('session.preset', 'farm')
  const [hours, setHours] = usePersisted('session.hours', 2)
  const [stream, setStream] = usePersisted('session.stream', false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    presetApi.list(playerId).then(setPresets)
  }, [playerId, dateKey])

  const preset = presets.find((p) => p.key === selected)

  const play = async () => {
    setBusy(true)
    setError(null)
    try {
      onPlayed(await presetApi.auto(playerId, selected, hours, stream), { preset: selected, hours, stream })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="space-y-4 rounded-xl bg-panel p-5">
      <h2 className="text-sm uppercase tracking-wider text-muted">{t('Play session')}</h2>
      <div className="grid gap-2 sm:grid-cols-3">
        {presets.map((p) => (
          <button
            key={p.key}
            disabled={!p.available}
            onClick={() => setSelected(p.key)}
            title={t(p.description)}
            className={`rounded-lg px-3 py-2 text-left text-sm ${
              p.key === selected
                ? 'bg-osu-pink/25 ring-1 ring-osu-pink'
                : p.available
                  ? 'bg-panel-light hover:bg-bg'
                  : 'cursor-not-allowed bg-bg/50 text-muted/50'
            }`}
          >
            <div className="flex items-center justify-between gap-1">
              <span className="font-semibold">{t(p.label)}</span>
              {p.mods !== 'NM' && <span className="rounded bg-bg px-1 text-[10px] font-bold">{p.mods}</span>}
            </div>
          </button>
        ))}
      </div>
      {preset && <p className="text-xs text-muted">{t(preset.description)}</p>}
      <label className="block space-y-1 text-sm">
        <span className="text-xs text-muted">{t('Hours of playing: {n}h', { n: hours })}</span>
        <input
          type="range"
          min={0.5}
          max={10}
          step={0.5}
          value={hours}
          onChange={(e) => setHours(Number(e.target.value))}
          className="w-full accent-osu-pink"
        />
      </label>
      <label className="flex items-center gap-2 text-sm text-muted">
        <input type="checkbox" checked={stream} onChange={(e) => setStream(e.target.checked)} className="accent-osu-pink" />
        {t('Stream it live (followers and money, but more pressure; Twitch exists from mid-2011)')}
      </label>
      {error && <p className="text-sm text-red-400">{error}</p>}
      <button
        disabled={busy || disabledReason != null || !preset?.available}
        onClick={play}
        className="w-full rounded-full bg-osu-pink py-2 font-semibold hover:bg-osu-pink-dark disabled:opacity-50"
      >
        {disabledReason ?? (busy ? t('Playing… (first sessions download maps)') : t('Play (ends the day)'))}
      </button>
    </section>
  )
}
