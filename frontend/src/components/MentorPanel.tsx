import { useCallback, useEffect, useState } from 'react'
import { mentorApi, type MentorOverview, type Mind } from '../api.mentors'
import { usePersisted } from '../usePersisted'
import { t, tx } from '../i18n'

const FAMILY_LABEL: Record<string, string> = {
  jumps: t('Jumps'),
  streams: t('Streams'),
  tech: t('Tech'),
  reading: t('Low AR'),
  hd: t('Hidden'),
  dt: t('DoubleTime'),
  hr: t('HardRock'),
}

const GROUP_LABEL: Record<string, string> = {
  aim: t('Aim'),
  tapping: t('Tapping'),
  reading: t('Reading'),
  technical: t('Technical'),
  mentality: t('Mentality'),
  physical: t('Physical'),
}

function Bar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div>
      <div className="flex justify-between text-xs">
        <span className="text-muted">{label}</span>
        <span>{Math.round(value)}</span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-bg">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </div>
    </div>
  )
}

export function MindSection({ mind }: { mind: Mind }) {
  return (
    <section className="space-y-3 rounded-xl bg-panel p-5">
      <h2 className="text-sm uppercase tracking-wider text-muted">{t('Mind')}</h2>
      <div className="space-y-1">
        <div className="text-xs text-muted">{t('Confidence by kind of map')}</div>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(FAMILY_LABEL).map(([key, label]) => {
            const v = mind.confidence[key] ?? 0
            const tone =
              v >= 0.25 ? 'bg-green-900 text-green-200' : v <= -0.25 ? 'bg-red-900 text-red-200' : 'bg-panel-light text-muted'
            return (
              <span key={key} className={`rounded px-2 py-0.5 text-xs ${tone}`} title={t('Up to ±4% on this kind of map')}>
                {label} {v > 0 ? '+' : ''}
                {Math.round(v * 100)}
              </span>
            )
          })}
        </div>
      </div>
      {mind.fear.length > 0 && (
        <div className="space-y-1 text-xs">
          {mind.fear.map((f) => (
            <div key={f.npc_id} className="text-amber-300">
              {t('Rattled by {name}', { name: f.name })} · {Math.round(f.value * 100)}%
            </div>
          ))}
        </div>
      )}
      <div className="text-xs text-muted">
        {mind.big_stage == null
          ? t('Big stage: not enough decisive maps yet')
          : t('Big stage: {pct}% of decisive maps won', { pct: Math.round(mind.big_stage * 100) })}
      </div>
    </section>
  )
}

export function MentorPanel({ playerId, dateKey, onChanged }: { playerId: number; dateKey: string; onChanged: () => void }) {
  const [data, setData] = useState<MentorOverview | null>(null)
  const [hours, setHours] = usePersisted('mentor.hours', 2)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    mentorApi
      .get(playerId)
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [playerId])
  useEffect(load, [load, dateKey])

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      load()
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!data) return <p className="text-sm text-muted">{error ? tx(error) : t('Loading…')}</p>
  const m = data.mentor

  return (
    <div className="space-y-4">
      <MindSection mind={data.mind} />
      <section className="space-y-3 rounded-xl bg-panel p-5">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Mentor')}</h2>
        {error && <p className="text-sm text-red-400">{tx(error)}</p>}
        {note && <p className="text-sm text-green-300">{tx(note)}</p>}
        {!data.available && <p className="text-sm text-muted">{tx(data.reason ?? '')}</p>}

        {m && (
          <div className="space-y-3">
            <div className="flex items-baseline gap-2">
              <span className="font-semibold">{m.name}</span>
              <span className="text-xs text-muted">
                [{m.country}] · {m.rank ? `#${m.rank.toLocaleString('en-US')}` : ''} · {t('focus')}: {GROUP_LABEL[m.group] ?? m.group}
              </span>
              {m.boost_active && (
                <span className="ml-auto rounded bg-green-900 px-1.5 py-0.5 text-[11px] text-green-200">
                  {t('Learning ×{n} until {d}', { n: m.boost.toFixed(2), d: m.boost_until })}
                </span>
              )}
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <Bar label={t('Bond')} value={m.bond} color="bg-osu-pink" />
              <Bar label={t('Their interest')} value={m.interest} color="bg-sky-500" />
            </div>
            <div className="text-xs text-muted">
              {t('{n} sessions', { n: m.sessions })} · {t('last: {d}', { d: m.last_session })}
              {m.gap != null && ` · ${t('they are {n} points ahead', { n: Math.max(0, m.gap).toFixed(1) })}`}
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-sm text-muted">
                {t('Hours')}
                <input
                  type="range"
                  min={1}
                  max={4}
                  step={0.5}
                  value={hours}
                  onChange={(e) => setHours(Number(e.target.value))}
                  className="accent-osu-pink"
                />
                <span className="w-8 text-white">{hours}</span>
              </label>
              <button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const r = await mentorApi.session(playerId, hours)
                    setNote(r.advice ? `${t('Advice')}: ${r.advice}` : t('A solid session.'))
                  })
                }
                className="rounded-full bg-osu-pink px-4 py-1.5 text-sm font-semibold hover:bg-osu-pink-dark disabled:opacity-50"
              >
                {t('Train with the mentor (a day)')}
              </button>
              <button
                disabled={busy}
                onClick={() => void run(async () => void (await mentorApi.end(playerId)))}
                className="rounded-full bg-panel-light px-3 py-1.5 text-xs text-muted hover:text-white disabled:opacity-50"
              >
                {t('End mentorship')}
              </button>
            </div>
          </div>
        )}

        {!m && data.available && (
          <div className="space-y-1.5">
            <p className="text-xs text-muted">{t('Stronger players who might coach you. Rivals never will.')}</p>
            {data.candidates.length === 0 && <p className="text-sm text-muted">{t('Nobody suitable right now.')}</p>}
            {data.candidates.map((c) => (
              <div key={c.npc_id} className="flex items-center gap-2 rounded bg-bg px-3 py-1.5 text-sm">
                <span className="min-w-0 flex-1 truncate">
                  {c.name} <span className="text-muted">[{c.country}] · #{c.rank.toLocaleString('en-US')} · {GROUP_LABEL[c.focus] ?? c.focus}</span>
                </span>
                <span className="text-xs text-muted">{c.blocked ? tx(c.blocked) : t('chance ~{n}%', { n: c.chance })}</span>
                <button
                  disabled={busy || c.blocked != null}
                  onClick={() =>
                    void run(async () => {
                      const r = await mentorApi.ask(playerId, c.npc_id)
                      setNote(r.message)
                    })
                  }
                  className="rounded-full bg-panel-light px-3 py-1 text-xs hover:bg-osu-pink disabled:opacity-40"
                >
                  {t('Ask')}
                </button>
              </div>
            ))}
          </div>
        )}

        {data.log.length > 0 && (
          <ul className="space-y-0.5 border-t border-panel-light pt-2 text-xs text-muted">
            {data.log.slice(0, 6).map((e, i) => (
              <li key={i}>
                {e.date} · {tx(e.text)}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
