import { useEffect, useState } from 'react'
import { api, type AssistSettings } from '../api'
import { t } from '../i18n'

const signed = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(2)}`

/** How the character's stats bend real gameplay in the tycoon client, and the knobs for it. */
export function AssistPanel({ playerId, dateKey }: { playerId: number; dateKey: string }) {
  const [data, setData] = useState<AssistSettings | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getAssist(playerId).then(setData).catch((e) => setError((e as Error).message))
  }, [playerId, dateKey])

  const save = (scale: number, magnet: boolean) =>
    api
      .setAssist(playerId, { scale, magnet })
      .then(setData)
      .catch((e) => setError((e as Error).message))

  if (!data) return error ? <p className="text-sm text-red-400">{error}</p> : null
  const a = data.assist
  const rows: [string, string, number, string][] = [
    [t('Hit windows'), 'OD', a.od_delta, `${t('timing')} ${a.timing.toFixed(0)}`],
    [t('Circle size'), 'CS', a.cs_delta, `${t('aim')} ${a.aim.toFixed(0)}`],
    [t('Approach rate'), 'AR', a.ar_delta, `${t('reading')} ${a.reading.toFixed(0)}`],
    [t('HP drain'), 'HP', a.hp_delta, `${t('stamina')} ${a.physical.toFixed(0)}`],
  ]

  return (
    <section className="space-y-4 rounded-xl bg-panel p-5">
      <div>
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Character in the client')}</h2>
        <p className="mt-1 text-xs text-muted">
          {t('Applied to every solo osu! map in the tycoon client. Negative means easier than the map as written.')}
        </p>
      </div>

      <table className="w-full text-sm">
        <tbody>
          {rows.map(([label, stat, value, source]) => (
            <tr key={stat}>
              <td className="py-0.5">{label}</td>
              <td className={`py-0.5 text-right font-mono ${value < 0 ? 'text-green-400' : value > 0 ? 'text-red-400' : ''}`}>
                {stat} {signed(value)}
              </td>
              <td className="py-0.5 pl-4 text-right text-xs text-muted">{source}</td>
            </tr>
          ))}
          <tr>
            <td className="py-0.5">{t('Cursor magnet')}</td>
            <td className="py-0.5 text-right font-mono">{a.magnet > 0 ? a.magnet.toFixed(2) : t('off')}</td>
            <td className="py-0.5 pl-4 text-right text-xs text-muted">
              {t('condition')} {Math.round(a.condition * 100)}%
            </td>
          </tr>
        </tbody>
      </table>

      <label className="block space-y-1">
        <span className="flex justify-between text-xs text-muted">
          <span>{t('Strength of stats')}</span>
          <span>{data.scale === 0 ? t('off') : `${data.scale.toFixed(2)}×`}</span>
        </span>
        <input
          type="range"
          min={0}
          max={2}
          step={0.25}
          value={data.scale}
          onChange={(e) => setData({ ...data, scale: Number(e.target.value) })}
          onPointerUp={() => save(data.scale, data.magnet)}
          onKeyUp={() => save(data.scale, data.magnet)}
          className="w-full accent-osu-pink"
        />
      </label>

      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" checked={data.magnet} onChange={(e) => save(data.scale, e.target.checked)} className="mt-1" />
        <span>
          {t('Cursor magnet')}
          <span className="block text-xs text-muted">
            {t('Nearby circles drift toward the cursor. Only works when aim is above average; stronger aim pulls harder.')}
          </span>
        </span>
      </label>
      {error && <p className="text-sm text-red-400">{error}</p>}
    </section>
  )
}
