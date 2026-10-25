import { useCallback, useEffect, useState } from 'react'
import { spendingApi, type Spending, type SpendingItem } from '../api.spending'
import { getLang, t, tx } from '../i18n'
import { AppliedChips } from './StoryPanel'

const KIND_LABEL: Record<SpendingItem['kind'], string> = {
  one_off: t('one-off'),
  timed: t('temporary'),
  sub: t('monthly'),
  owned: t('yours for good'),
}

const STATUS_STYLE: Record<string, string> = {
  owned: 'text-green-300',
  subscribed: 'text-green-300',
  active: 'text-sky-300',
  cooldown: 'text-amber-300',
  locked: 'text-muted',
}

function Card({ item, busy, onBuy }: { item: SpendingItem; busy: boolean; onBuy: (choice?: string) => void }) {
  const [choice, setChoice] = useState(item.choices[0]?.key ?? '')
  const blocked = item.status !== 'available'
  const disabled = busy || blocked || !item.affordable || (item.choices.length > 0 && !choice)
  const why = blocked ? item.reason : !item.affordable ? t('Not enough money') : ''
  const label =
    item.status === 'owned' ? t('Owned') : item.status === 'subscribed' ? t('Subscribed') : item.status === 'active' ? t('Active')
    : item.status === 'cooldown' ? t('In {n} d', { n: item.cooldown_left }) : item.status === 'locked' ? t('Locked')
    : item.kind === 'sub' ? t('Subscribe') : t('Buy')
  return (
    <article className={`flex min-w-0 flex-col gap-1.5 rounded-lg bg-bg p-3 ${item.status === 'locked' ? 'opacity-60' : ''}`}>
      <div className="flex items-start gap-2">
        <span className="text-xl leading-none" aria-hidden>
          {item.icon}
        </span>
        <div className="min-w-0 flex-1">
          <h4 className="truncate text-sm font-semibold" title={item.name}>
            {item.name}
          </h4>
          <div className="text-[10px] uppercase tracking-wider text-muted">{KIND_LABEL[item.kind]}</div>
        </div>
        <div className="text-right text-sm font-bold text-osu-pink">
          {item.price > 0 ? `$${item.price.toLocaleString('en-US')}` : '—'}
          {item.kind === 'sub' && <span className="text-[10px] font-normal text-muted">/{t('mo')}</span>}
        </div>
      </div>
      <p className="text-xs text-muted">{item.description}</p>
      <p className="text-xs text-green-300/90">{item.perk}</p>
      <div className="mt-auto flex items-center gap-2 pt-1">
        {item.choices.length > 0 && !blocked && (
          <select
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
            aria-label={t('Skill group')}
            className="min-w-0 flex-1 rounded bg-panel px-1.5 py-1 text-xs"
          >
            {item.choices.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        )}
        <button
          disabled={disabled}
          title={why}
          onClick={() => onBuy(item.choices.length ? choice : undefined)}
          className={`ml-auto rounded-full px-3 py-1 text-xs font-semibold ${
            blocked ? `bg-panel-light ${STATUS_STYLE[item.status] ?? ''}` : 'bg-osu-pink hover:bg-osu-pink-dark'
          } disabled:opacity-50`}
        >
          {label}
        </button>
      </div>
      {why && blocked && item.status !== 'owned' && item.status !== 'subscribed' && <p className="text-[11px] text-muted">{why}</p>}
    </article>
  )
}

export function SpendingPanel({ playerId, dateKey, onChanged }: { playerId: number; dateKey: string; onChanged: () => void }) {
  const [data, setData] = useState<Spending | null>(null)
  const [cat, setCat] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<{ text: string; applied: Record<string, unknown> } | null>(null)

  const load = useCallback(() => {
    spendingApi.get(playerId).then(setData).catch((e: Error) => setError(e.message))
  }, [playerId])
  useEffect(load, [load, dateKey])

  if (!data) return <p className="text-sm text-muted">{error ? tx(error) : t('Loading…')}</p>
  const active = data.categories.find((c) => c.key === cat) ?? data.categories[0]

  const act = async (fn: () => Promise<{ message: string; message_ru: string; applied?: Record<string, unknown> }>) => {
    setBusy(true)
    setError(null)
    try {
      const r = await fn()
      setDone({ text: getLang() === 'ru' ? r.message_ru : r.message, applied: r.applied ?? {} })
      load()
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span className="text-muted">
          {t('Your money')}: <b className="text-white">${data.money.toLocaleString('en-US')}</b>
        </span>
        {data.monthly_total > 0 && (
          <span className="text-muted">
            {t('Subscriptions per month')}: <b className="text-white">${data.monthly_total}</b>
          </span>
        )}
      </div>

      {(done || error) && (
        <div className={`rounded-lg px-3 py-2 text-sm ${error ? 'bg-red-950 text-red-300' : 'bg-green-950/60 text-green-200'}`}>
          {error ? tx(error) : done?.text}
          {!error && done && <AppliedChips applied={done.applied as never} />}
        </div>
      )}

      {data.subscriptions.length > 0 && (
        <ul className="space-y-1">
          {data.subscriptions.map((s) => (
            <li key={s.key} className="flex items-center gap-2 rounded-lg bg-bg px-3 py-1.5 text-sm">
              <span className="min-w-0 flex-1 truncate">{s.name}</span>
              <span className="text-xs text-muted">{t('{n} mo', { n: s.months })}</span>
              <span className="w-16 text-right font-semibold">${s.price}/{t('mo')}</span>
              <button
                disabled={busy}
                onClick={() => void act(() => spendingApi.cancel(playerId, s.key))}
                className="rounded-full bg-panel-light px-2 py-0.5 text-xs text-muted hover:text-white"
              >
                {t('Cancel')}
              </button>
            </li>
          ))}
        </ul>
      )}

      {data.effects.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
          <span>{t('Active effects')}:</span>
          {data.effects.map((e, i) => (
            <span key={i} className="rounded bg-panel-light px-1.5 py-0.5">
              {e.label} · {t('{n} d left', { n: Math.max(0, e.days_left) })}
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-1">
        {data.categories.map((c) => (
          <button
            key={c.key}
            onClick={() => setCat(c.key)}
            className={`rounded-full px-3 py-1 text-xs font-semibold ${active.key === c.key ? 'bg-osu-pink' : 'bg-panel-light text-muted hover:text-white'}`}
          >
            {c.icon} {c.name}
          </button>
        ))}
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {active.items.map((item) => (
          <Card key={item.key} item={item} busy={busy} onBuy={(choice) => void act(() => spendingApi.buy(playerId, item.key, choice))} />
        ))}
      </div>
    </div>
  )
}
