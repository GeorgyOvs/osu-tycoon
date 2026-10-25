import { useCallback, useEffect, useState } from 'react'
import {
  integrityApi,
  type IntegrityCase,
  type IntegrityOverview,
  type SetupOverview,
  type WearRow,
} from '../api.integrity'
import { t, tx } from '../i18n'

const CATEGORY_LABEL: Record<string, string> = {
  mouse: t('Mouse'),
  tablet: t('Tablet'),
  keyboard: t('Keyboard'),
}

const CONDITION_LABEL: Record<string, string> = {
  'like new': t('like new'),
  used: t('used'),
  worn: t('worn'),
  'worn out': t('worn out'),
}

const TIER_LABEL: Record<string, string> = {
  excellent: t('excellent'),
  good: t('good'),
  noticeable: t('noticeable lag'),
  poor: t('poor'),
}

const REGION_LABEL: Record<string, string> = {
  Europe: t('Europe'),
  'North America': t('North America'),
  'South America': t('South America'),
  Asia: t('Asia'),
  Oceania: t('Oceania'),
}

const CASE_STATUS: Record<string, string> = {
  cleared: t('Cleared'),
  closed: t('Closed'),
  restricted: t('Restricted by mistake'),
}

const SUSPICION_LABEL: Record<string, string> = {
  rank_jump: t('A sudden climb in rank'),
  great_play: t('A play far above your level'),
  routine: t('Top players always get reported'),
}

const signed = (n: number, d = 0) => `${n > 0 ? '+' : ''}${n.toFixed(d)}`

function repColor(rep: number) {
  return rep < 35 ? 'bg-red-500' : rep < 55 ? 'bg-amber-500' : rep < 75 ? 'bg-sky-500' : 'bg-green-500'
}

function CaseCard({ c, busy, onRespond }: { c: IntegrityCase; busy: boolean; onRespond: (choice: string) => void }) {
  return (
    <article className="space-y-2 rounded-xl bg-bg p-4 ring-1 ring-red-500/40">
      <div className="flex items-center gap-2">
        <h3 className="flex-1 font-semibold">{c.title}</h3>
        {c.days_left != null && (
          <span className="text-xs text-muted">{c.days_left > 0 ? t('answer within {n} d', { n: c.days_left }) : t('answer today')}</span>
        )}
      </div>
      <p className="text-sm text-slate-200">{c.body}</p>
      <div className="flex flex-wrap gap-2">
        {c.options.map((o) => (
          <button
            key={o.key}
            disabled={busy}
            onClick={() => onRespond(o.key)}
            title={o.hint}
            className="rounded-full bg-panel-light px-3 py-1.5 text-sm hover:bg-osu-pink disabled:opacity-50"
          >
            {o.label}
            <span className="ml-1.5 text-xs text-muted">· {o.hint}</span>
          </button>
        ))}
      </div>
    </article>
  )
}

export function IntegritySection({ playerId, dateKey, onChanged }: { playerId: number; dateKey: string; onChanged?: () => void }) {
  const [data, setData] = useState<IntegrityOverview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    integrityApi.overview(playerId).then(setData).catch((e: Error) => setError(e.message))
  }, [playerId])
  useEffect(load, [load, dateKey])

  const respond = async (c: IntegrityCase, choice: string) => {
    setBusy(true)
    try {
      setData(await integrityApi.respond(playerId, c.id, choice))
      setError(null)
      onChanged?.()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!data) return <p className="text-sm text-muted">{error ? tx(error) : t('Loading…')}</p>
  return (
    <section className="space-y-3 rounded-xl bg-panel p-5">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Reputation')}</h2>
        <span className="text-sm font-semibold">{data.label} · {Math.round(data.reputation)}</span>
      </div>
      <div className="h-1.5 rounded-full bg-bg">
        <div className={`h-full rounded-full ${repColor(data.reputation)}`} style={{ width: `${data.reputation}%` }} />
      </div>
      <p className="text-xs text-muted">
        {t('Sponsors pay ×{s}, new followers ×{f}', { s: data.effects.sponsor.toFixed(2), f: data.effects.followers.toFixed(2) })}
      </p>
      {data.restricted_until && (
        <p className="rounded-lg bg-red-950 p-3 text-sm ring-1 ring-red-600">
          {t('Your account is restricted until {d}: ranked scores are disabled during the review.', { d: data.restricted_until })}
        </p>
      )}
      {error && <p className="text-sm text-red-400">{tx(error)}</p>}
      {data.open.map((c) => (
        <CaseCard key={c.id} c={c} busy={busy} onRespond={(choice) => void respond(c, choice)} />
      ))}
      {data.suspicion.factors.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
          <span>{t('How you look from outside')}:</span>
          {data.suspicion.factors.map((f) => (
            <span key={f.kind} className="rounded bg-panel-light px-1.5 py-0.5" title={`${Math.round(f.level * 100)}%`}>
              {SUSPICION_LABEL[f.kind] ?? f.kind}
            </span>
          ))}
        </div>
      )}
      {data.history.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted hover:text-white">
            {t('Past cases')} ({data.history.length})
          </summary>
          <div className="mt-2 space-y-2">
            {data.history.map((c) => (
              <div key={c.id} className="rounded-lg bg-bg px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className="flex-1 font-medium">{c.title}</span>
                  <span className="text-xs text-muted">{c.resolved}</span>
                </div>
                <div className="text-xs text-muted">
                  {CASE_STATUS[c.status] ?? c.status}
                  {c.auto && ` · ${t('no answer in time')}`}
                  {c.outcome && ` — ${c.outcome}`}
                  {c.rep_delta !== 0 && ` · ${t('Reputation')} ${signed(c.rep_delta, 1)}`}
                  {c.restricted_days ? ` · ${t('frozen for {n} d', { n: c.restricted_days })}` : ''}
                </div>
              </div>
            ))}
          </div>
        </details>
      )}
    </section>
  )
}

function WearBar({ row, money, busy, onMaintain, onReplace }: { row: WearRow; money: number; busy: boolean; onMaintain: () => void; onReplace: () => void }) {
  const color = row.wear < 0.35 ? 'bg-green-500' : row.wear < 0.65 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className={`space-y-1 rounded-lg bg-bg px-3 py-2 text-sm ${row.active ? '' : 'opacity-60'}`}>
      <div className="flex items-center gap-2">
        <span className="font-medium">{CATEGORY_LABEL[row.category]}</span>
        <span className="min-w-0 flex-1 truncate text-xs text-muted">{row.item ? t(row.item) : t('none')}</span>
        <span className="text-xs">
          {CONDITION_LABEL[row.condition] ?? row.condition}
          {row.penalty > 0.001 && <span className="text-red-300"> · −{(row.penalty * 100).toFixed(1)}%</span>}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-panel-light">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.round(row.wear * 100)}%` }} />
      </div>
      {row.item && (
        <div className="flex gap-2 text-xs">
          <button disabled={busy || money < row.service_cost || row.wear < 0.02} onClick={onMaintain}
            className="rounded-full bg-panel-light px-3 py-1 hover:bg-osu-pink disabled:opacity-40">
            {t('Service')} ${row.service_cost}
          </button>
          <button disabled={busy || row.replace_cost == null || money < (row.replace_cost ?? 0) || row.wear < 0.02} onClick={onReplace}
            className="rounded-full bg-panel-light px-3 py-1 hover:bg-osu-pink disabled:opacity-40">
            {t('Replace')} ${row.replace_cost}
          </button>
        </div>
      )}
    </div>
  )
}

export function SetupCondition({ playerId, dateKey, onChanged }: { playerId: number; dateKey: string; onChanged?: () => void }) {
  const [data, setData] = useState<SetupOverview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    integrityApi.setup(playerId).then(setData).catch((e: Error) => setError(e.message))
  }, [playerId])
  useEffect(load, [load, dateKey])

  const act = async (fn: () => Promise<SetupOverview>) => {
    setBusy(true)
    try {
      setData(await fn())
      setError(null)
      onChanged?.()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!data) return <p className="text-sm text-muted">{error ? tx(error) : t('Loading…')}</p>
  const n = data.network
  return (
    <section className="space-y-3 rounded-xl bg-panel p-5">
      <h2 className="text-sm uppercase tracking-wider text-muted">{t('Setup condition')}</h2>
      {error && <p className="text-sm text-red-400">{tx(error)}</p>}
      {data.wear.map((row) => (
        <WearBar key={row.category} row={row} money={data.money} busy={busy}
          onMaintain={() => void act(() => integrityApi.maintain(playerId, row.category))}
          onReplace={() => void act(() => integrityApi.replace(playerId, row.category))} />
      ))}
      <div className="space-y-1 rounded-lg bg-bg px-3 py-2 text-sm" title={t('Sensitivity, tablet area and key bindings settle with consistent use and partly reset when you change gear')}>
        <div className="flex justify-between">
          <span>{t('Settings comfort')}</span>
          <span className="text-xs text-muted">
            {Math.round(data.comfort * 100)}%{data.comfort_penalty > 0.001 && ` · −${(data.comfort_penalty * 100).toFixed(1)}%`}
          </span>
        </div>
        <div className="h-1.5 rounded-full bg-panel-light">
          <div className="h-full rounded-full bg-sky-500" style={{ width: `${Math.round(data.comfort * 100)}%` }} />
        </div>
      </div>
      <div className="space-y-1 rounded-lg bg-bg px-3 py-2 text-sm">
        <div className="flex items-center gap-2">
          <span className="flex-1">{t('Connection')}: {REGION_LABEL[n.region_name] ?? n.region_name}</span>
          <span className="text-xs text-muted">
            {t('lobbies ~{ms} ms', { ms: n.lobby_ping })} · {TIER_LABEL[n.tier] ?? n.tier}
          </span>
        </div>
        <p className="text-xs text-muted">
          {n.pressure_penalty > 0
            ? t('Far-away opponents make you jumpy: +{p}% choke risk', { p: (n.pressure_penalty * 100).toFixed(0) })
            : t('Your connection is no problem for online matches.')}
          {n.regional_servers && ` ${t('Regional servers help.')}`}
        </p>
        {n.isp_price != null && (
          <button disabled={busy || data.money < n.isp_price} onClick={() => void act(() => integrityApi.upgradeIsp(playerId))}
            className="rounded-full bg-panel-light px-3 py-1 text-xs hover:bg-osu-pink disabled:opacity-40">
            {t('Better connection')} ${n.isp_price} ({n.isp_level}/{n.isp_max})
          </button>
        )}
      </div>
    </section>
  )
}

export function IntegrityPanel({ playerId, dateKey, onChanged }: { playerId: number; dateKey: string; onChanged?: () => void }) {
  return (
    <>
      <IntegritySection playerId={playerId} dateKey={dateKey} onChanged={onChanged} />
      <SetupCondition playerId={playerId} dateKey={dateKey} onChanged={onChanged} />
    </>
  )
}
