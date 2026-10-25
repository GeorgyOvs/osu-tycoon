import { useCallback, useEffect, useState } from 'react'
import { legacyApi, type AchievementInfo, type Budget, type HallEntry, type Legacy } from '../api.legacy'
import { t, tx } from '../i18n'

const RARITY_STYLE: Record<string, string> = {
  common: 'bg-slate-700 text-slate-200',
  uncommon: 'bg-green-900 text-green-200',
  rare: 'bg-sky-900 text-sky-200',
  epic: 'bg-fuchsia-900 text-fuchsia-200',
  legendary: 'bg-amber-600/40 text-amber-200 ring-1 ring-amber-400',
}

const RARITY_LABEL: Record<string, string> = {
  common: t('Common'),
  uncommon: t('Uncommon'),
  rare: t('Rare'),
  epic: t('Epic'),
  legendary: t('Legendary'),
}

const CATEGORY_LABEL: Record<string, string> = {
  salary: t('Salary & allowance'),
  prize: t('Prizes'),
  sponsor: t('Sponsors'),
  stream: t('Streaming'),
  event: t('Life events'),
  loan: t('Loan'),
  other: t('Other'),
  tax: t('Taxes'),
  living: t('Living costs'),
  tuition: t('Tuition'),
  gear: t('Gear'),
  physio: t('Physiotherapy'),
  interest: t('Interest'),
  repay: t('Loan repayment'),
  event_cost: t('Life event costs'),
  services: t('Services & perks'),
  subscription: t('Subscriptions'),
}

const money = (n: number) => `${n < 0 ? '−' : ''}$${Math.abs(Math.round(n)).toLocaleString('en-US')}`
const weeks = (n: number | null) => (n == null ? t('sustainable') : t('{n} weeks', { n: Math.round(n) }))

function AchievementChip({ a, progress }: { a: AchievementInfo; progress?: boolean }) {
  return (
    <div className={`rounded-lg px-2.5 py-1.5 text-xs ${RARITY_STYLE[a.rarity]} ${progress ? 'opacity-90' : ''}`} title={a.description}>
      <div className="flex items-center gap-2">
        <b className="flex-1">{a.name}</b>
        <span className="text-[10px] uppercase opacity-70">{RARITY_LABEL[a.rarity]}</span>
      </div>
      <div className="opacity-80">{a.description}</div>
      {progress && (
        <div className="mt-1 h-1 rounded-full bg-black/30">
          <div className="h-full rounded-full bg-white/70" style={{ width: `${Math.round((a.progress ?? 0) * 100)}%` }} />
        </div>
      )}
      {a.unlocked_on && <div className="mt-0.5 text-[10px] opacity-60">{a.unlocked_on}</div>}
    </div>
  )
}

function BudgetCard({ budget, playerId, onChange }: { budget: Budget; playerId: number; onChange: (b: Budget) => void }) {
  const [amount, setAmount] = useState(200)
  const [error, setError] = useState<string | null>(null)
  const run = async (fn: () => Promise<Budget>) => {
    try {
      onChange(await fn())
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }
  const cats = Array.from(new Set(budget.months.flatMap((m) => Object.keys(m.categories))))
  return (
    <section className="space-y-3 rounded-xl bg-panel p-4">
      <h2 className="text-sm uppercase tracking-wider text-muted">{t('Budget')}</h2>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span>
          {t('Money')}: <b className={budget.money < 0 ? 'text-red-400' : ''}>{money(budget.money)}</b>
        </span>
        {budget.loan > 0 && (
          <span>
            {t('Loan')}: <b className="text-amber-300">{money(budget.loan)}</b>
          </span>
        )}
        <span title={t('Fixed weekly costs minus pay in your current occupation')}>
          {t('Weekly burn')}: <b>{money(budget.runway.weekly_burn)}</b>
        </span>
        <span>
          {t('Runway now')}: <b>{weeks(budget.runway.weeks_left_now)}</b>
        </span>
        <span title={t('If you went full-time pro with your recent winnings')}>
          {t('Runway as a pro')}: <b>{weeks(budget.runway.weeks_left_pro)}</b>
        </span>
      </div>
      {budget.months.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-muted">
                <th className="py-1 pr-3 font-normal">{t('Month')}</th>
                {cats.map((c) => (
                  <th key={c} className="px-1 py-1 text-right font-normal">
                    {CATEGORY_LABEL[c] ?? c}
                  </th>
                ))}
                <th className="px-1 py-1 text-right font-normal">{t('Net')}</th>
              </tr>
            </thead>
            <tbody>
              {budget.months.map((m) => (
                <tr key={m.month} className="border-t border-panel-light">
                  <td className="py-1 pr-3 text-muted">{m.month}</td>
                  {cats.map((c) => (
                    <td key={c} className={`px-1 py-1 text-right ${(m.categories[c] ?? 0) < 0 ? 'text-red-300' : ''}`}>
                      {m.categories[c] ? money(m.categories[c]) : '—'}
                    </td>
                  ))}
                  <td className={`px-1 py-1 text-right font-semibold ${m.net < 0 ? 'text-red-400' : 'text-green-300'}`}>{money(m.net)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {budget.realistic ? (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <input
            type="number"
            min={10}
            value={amount}
            onChange={(e) => setAmount(Math.max(10, Number(e.target.value)))}
            className="w-24 rounded bg-bg px-2 py-1 outline-none focus:ring-2 focus:ring-osu-pink"
          />
          <button
            onClick={() => void run(() => legacyApi.loan(playerId, amount))}
            className="rounded-full bg-panel-light px-3 py-1 hover:bg-osu-pink"
          >
            {t('Borrow')}
          </button>
          <button
            disabled={budget.loan <= 0}
            onClick={() => void run(() => legacyApi.repay(playerId, Math.min(amount, budget.loan)))}
            className="rounded-full bg-panel-light px-3 py-1 hover:bg-osu-pink disabled:opacity-40"
          >
            {t('Repay')}
          </button>
          <span className="text-xs text-muted">
            {t('Up to ${n}; 2% interest a month', { n: Math.round(budget.loan_limit) })}
          </span>
        </div>
      ) : (
        <p className="text-xs text-muted">{t('Simple economy: living costs are already folded into your weekly income.')}</p>
      )}
      {error && <p className="text-xs text-red-400">{tx(error)}</p>}
    </section>
  )
}

function Hall({ entries }: { entries: HallEntry[] }) {
  if (entries.length === 0) return <p className="text-sm text-muted">{t('Nobody has retired yet.')}</p>
  return (
    <ol className="space-y-1">
      {entries.map((h, i) => (
        <li key={h.id} className="flex items-center gap-3 rounded bg-bg px-3 py-1.5 text-sm">
          <span className="w-5 text-muted">{i + 1}</span>
          <span className="flex-1">
            {h.name} <span className="text-muted">[{h.country}]</span>
            {h.hardcore && <span className="ml-2 rounded bg-red-900 px-1 text-[10px] text-red-200">{t('Hardcore')}</span>}
          </span>
          <span className="text-xs text-muted">
            {h.best_rank ? `#${h.best_rank.toLocaleString('en-US')}` : '—'} · {Math.round(h.peak_pp)}pp · {t('{n} medals', { n: h.achievements })}
          </span>
          <b className="w-12 text-right text-amber-300">{h.score}</b>
        </li>
      ))}
    </ol>
  )
}

export function LegacyPanel({ playerId, playerName, dateKey, onChanged }: { playerId: number; playerName: string; dateKey: string; onChanged: () => void }) {
  const [data, setData] = useState<Legacy | null>(null)
  const [hall, setHall] = useState<HallEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [typed, setTyped] = useState('')
  const [showAll, setShowAll] = useState(false)

  const load = useCallback(() => {
    legacyApi
      .get(playerId)
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
    legacyApi.hall().then(setHall).catch(() => setHall(null))
  }, [playerId])
  useEffect(load, [load, dateKey])

  if (!data) return <p className="text-sm text-muted">{error ? tx(error) : t('Loading…')}</p>
  const { status, achievements: ach } = data
  const mustType = status.hardcore

  const retire = async () => {
    try {
      setData(await legacyApi.retire(playerId))
      setConfirming(false)
      onChanged()
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="space-y-6">
      {error && <p className="text-sm text-red-400">{tx(error)}</p>}

      <section className="flex flex-wrap items-center gap-3 rounded-xl bg-panel p-4">
        <div>
          <div className="text-xs uppercase tracking-wider text-muted">{t('Legacy score')}</div>
          <div className="text-3xl font-bold text-amber-300">{data.score}</div>
        </div>
        <div className="flex flex-1 flex-wrap justify-end gap-1.5 text-xs">
          {status.hardcore && <span className="rounded bg-red-900 px-2 py-0.5 text-red-200">{t('Hardcore')}</span>}
          <span className="rounded bg-panel-light px-2 py-0.5">
            {status.economy === 'realistic' ? t('Realistic economy') : t('Simple economy')}
          </span>
          <span className="rounded bg-panel-light px-2 py-0.5">
            {t('Medals')}: {ach.unlocked_count}/{ach.total}
          </span>
          {status.retired && <span className="rounded bg-slate-600 px-2 py-0.5">{t('Retired')} · {status.retired_on}</span>}
        </div>
      </section>

      {data.epilogue && (
        <section className="space-y-2 rounded-xl bg-panel p-4 ring-1 ring-amber-400/40">
          <h2 className="text-sm uppercase tracking-wider text-muted">{t('Epilogue')}</h2>
          {data.epilogue.lines.map((line, i) => (
            <p key={i} className={i === 0 ? 'font-semibold' : 'text-sm text-slate-200'}>
              {line}
            </p>
          ))}
        </section>
      )}

      {data.records.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm uppercase tracking-wider text-muted">{t('Career records')}</h2>
          <div className="grid gap-2 sm:grid-cols-3">
            {data.records.map((r) => (
              <div key={r.key} className="rounded-lg bg-panel px-3 py-2">
                <div className="text-xs text-muted">{r.label}</div>
                <div className="text-lg font-bold">
                  {r.key === 'best_rank' ? `#${r.value.toLocaleString('en-US')}` : r.key === 'peak_money' ? money(r.value) : Math.round(r.value * 100) / 100}
                </div>
                {r.date && <div className="text-[10px] text-muted">{r.date}</div>}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Next medals')}</h2>
        <div className="grid gap-2 sm:grid-cols-2">
          {ach.next.map((a) => (
            <AchievementChip key={a.key} a={a} progress />
          ))}
        </div>
      </section>

      <section className="space-y-2">
        <button onClick={() => setShowAll((v) => !v)} className="text-sm uppercase tracking-wider text-muted hover:text-white">
          {t('Medals')} ({ach.unlocked_count}) {showAll ? '▾' : '▸'}
        </button>
        {showAll && (
          <div className="grid gap-2 sm:grid-cols-2">
            {ach.unlocked.map((a) => (
              <AchievementChip key={a.key} a={a} />
            ))}
            {ach.unlocked.length === 0 && <p className="text-sm text-muted">{t('No medals yet.')}</p>}
          </div>
        )}
      </section>

      <BudgetCard budget={data.budget} playerId={playerId} onChange={(b) => setData({ ...data, budget: b })} />

      <section className="space-y-2">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Hall of fame')}</h2>
        <Hall entries={hall ?? []} />
      </section>

      {!status.retired && (
        <section className="space-y-2 rounded-xl bg-panel p-4">
          <h2 className="text-sm uppercase tracking-wider text-muted">{t('End the career')}</h2>
          <p className="text-xs text-muted">
            {t('Retiring writes your epilogue and freezes training. The calendar keeps turning, but the career is over.')}
          </p>
          {!confirming ? (
            <button onClick={() => setConfirming(true)} className="rounded-full bg-red-900 px-4 py-1.5 text-sm hover:bg-red-700">
              {t('Retire')}
            </button>
          ) : (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              {mustType && (
                <input
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  placeholder={t('Type "{name}" to confirm', { name: playerName })}
                  className="rounded bg-bg px-2 py-1 outline-none focus:ring-2 focus:ring-red-500"
                />
              )}
              <button
                disabled={mustType && typed !== playerName}
                onClick={() => void retire()}
                className="rounded-full bg-red-700 px-4 py-1.5 hover:bg-red-600 disabled:opacity-40"
              >
                {t('Yes, retire')}
              </button>
              <button onClick={() => setConfirming(false)} className="text-muted hover:text-white">
                {t('Cancel')}
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
