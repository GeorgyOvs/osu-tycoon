import { useCallback, useEffect, useState } from 'react'
import { worldApi } from '../api'
import { teamApi, type Team, type TeamCandidate, type TeamMember, type TeamState } from '../api.team'
import { STAT_LABELS } from '../i18n.keys'
import { t, tx } from '../i18n'

const ROLE_LABEL: Record<string, string> = {
  leader: t('Leader'),
  anchor: t('Anchor'),
  speed: t('Speed'),
  accuracy: t('Accuracy'),
  member: t('Member'),
}

const GROUP_NAME: Record<string, string> = {
  aim: t('Aim'),
  tapping: t('Tapping'),
  reading: t('Reading'),
  technical: t('Technical'),
  mentality: t('Mentality'),
  physical: t('Physical'),
}

function Meter({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div>
      <div className="flex justify-between text-xs">
        <span className="text-muted">{label}</span>
        <span>{Math.round(value)}</span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-bg">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(100, value)}%` }} />
      </div>
    </div>
  )
}

function MemberRow({ m, onKick }: { m: TeamMember; onKick?: () => void }) {
  return (
    <div className="flex items-center gap-3 rounded bg-bg px-3 py-2 text-sm">
      <div className="min-w-0 flex-1">
        <b>{m.name}</b> <span className="text-muted">[{m.country}]</span>{' '}
        <span className="rounded bg-panel-light px-1.5 text-[10px] uppercase text-muted">{ROLE_LABEL[m.role] ?? m.role}</span>
        <div className="text-xs text-muted">
          {m.rank ? `#${m.rank.toLocaleString('en-US')}` : '—'} · {Math.round(m.pp).toLocaleString('en-US')}pp
          {m.status !== 'active' && <span className="text-amber-400"> · {tx(m.status === 'injured' ? 'injured' : 'on hiatus')}</span>}
        </div>
      </div>
      <div className="w-24" title={t('How much they like you')}>
        <Meter label={t('Bond')} value={m.bond} color="bg-pink-400" />
      </div>
      {onKick && (
        <button onClick={onKick} className="rounded-full bg-panel-light px-2 py-0.5 text-xs text-muted hover:bg-red-700 hover:text-white">
          {t('Remove')}
        </button>
      )}
    </div>
  )
}

function InviteBanner({ invite, onAccept, onDecline }: { invite: Team; onAccept: () => void; onDecline: () => void }) {
  return (
    <section className="space-y-3 rounded-xl bg-panel p-5 ring-1 ring-osu-pink">
      <h2 className="text-sm uppercase tracking-wider text-muted">{t('Team invitation')}</h2>
      <p className="text-sm">
        <b>{invite.invited_by ?? invite.members[0]?.name}</b> {t('invites you to join')} <b>{invite.name}</b> [{invite.tag}].
        {invite.expires_on && <span className="text-muted"> {t('Open until {d}', { d: invite.expires_on })}</span>}
      </p>
      <div className="space-y-1.5">
        {invite.members.map((m) => (
          <MemberRow key={m.npc_id} m={m} />
        ))}
      </div>
      <div className="flex gap-2">
        <button onClick={onAccept} className="rounded-full bg-osu-pink px-4 py-1.5 text-sm font-semibold hover:bg-osu-pink-dark">
          {t('Accept')}
        </button>
        <button onClick={onDecline} className="rounded-full bg-panel-light px-4 py-1.5 text-sm text-muted hover:text-white">
          {t('Decline')}
        </button>
      </div>
    </section>
  )
}

function FoundForm({ state, onFound }: { state: TeamState; onFound: (name: string, tag: string) => void }) {
  const [name, setName] = useState('')
  const [tag, setTag] = useState('')
  return (
    <section className="space-y-3 rounded-xl bg-panel p-5">
      <h2 className="text-sm uppercase tracking-wider text-muted">{t('Found your own team')}</h2>
      <p className="text-xs text-muted">
        {t('A team of three can enter clan cups. Founding costs ${n}.', { n: state.found_cost })}
      </p>
      {state.found_blocker && <p className="text-sm text-amber-400">{tx(state.found_blocker)}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={32}
          placeholder={t('Team name')}
          className="flex-1 rounded bg-bg px-3 py-1.5 text-sm"
        />
        <input
          value={tag}
          onChange={(e) => setTag(e.target.value.toUpperCase())}
          maxLength={5}
          placeholder={t('Tag')}
          className="w-20 rounded bg-bg px-3 py-1.5 text-sm"
        />
        <button
          onClick={() => onFound(name, tag)}
          disabled={!state.can_found || name.trim().length < 3 || tag.trim().length < 2}
          className="rounded-full bg-osu-pink px-4 py-1.5 text-sm font-semibold hover:bg-osu-pink-dark disabled:opacity-40"
        >
          {t('Found')}
        </button>
      </div>
      {state.history.length > 0 && (
        <div className="space-y-1 text-xs text-muted">
          <div className="uppercase">{t('Past teams')}</div>
          {state.history.map((h, i) => (
            <div key={i}>
              {h.name} [{h.tag}] · {h.status === 'left' ? t('left') : t('disbanded')}
              {h.left_on && ` · ${h.left_on}`}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function Recruiting({ playerId, full, onRecruited }: { playerId: number; full: boolean; onRecruited: (s: TeamState, message: string) => void }) {
  const [list, setList] = useState<TeamCandidate[] | null>(null)
  const [busy, setBusy] = useState(false)
  const load = () => teamApi.candidates(playerId).then(setList)
  return (
    <section className="space-y-2 rounded-xl bg-panel p-5">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Recruit')}</h2>
        <button onClick={() => void load()} disabled={full} className="rounded-full bg-panel-light px-3 py-0.5 text-xs hover:bg-osu-pink disabled:opacity-40">
          {list ? t('Refresh') : t('Look for players')}
        </button>
      </div>
      {full && <p className="text-xs text-muted">{t('The team is full.')}</p>}
      {list?.map((c) => (
        <div key={c.npc_id} className="flex items-center gap-3 rounded bg-bg px-3 py-2 text-sm">
          <div className="min-w-0 flex-1">
            <b>{c.name}</b> <span className="text-muted">[{c.country}]</span>
            {c.rival && <span className="ml-1 rounded bg-red-900 px-1 text-[10px]">{t('rival')}</span>}
            <div className="text-xs text-muted">
              {c.rank ? `#${c.rank.toLocaleString('en-US')}` : '—'} · {Math.round(c.pp).toLocaleString('en-US')}pp ·{' '}
              {GROUP_NAME[c.strength] ?? STAT_LABELS[c.strength] ?? c.strength}
            </div>
          </div>
          <span className="w-20 text-right text-xs text-muted" title={t('Chance they say yes')}>
            {Math.round(c.odds * 100)}%
          </span>
          <button
            disabled={busy || !!c.refused_until}
            title={c.refused_until ? t('Declined recently: try again after {d}', { d: c.refused_until }) : undefined}
            onClick={async () => {
              setBusy(true)
              try {
                const out = await teamApi.recruit(playerId, c.npc_id)
                onRecruited(out.state, out.message)
                await load()
              } finally {
                setBusy(false)
              }
            }}
            className="rounded-full bg-osu-pink px-3 py-1 text-xs font-semibold hover:bg-osu-pink-dark disabled:opacity-40"
          >
            {t('Ask')}
          </button>
        </div>
      ))}
    </section>
  )
}

export function TeamPanel({ playerId, dateKey, onChanged }: { playerId: number; dateKey: string; onChanged: () => void }) {
  const [state, setState] = useState<TeamState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [hours, setHours] = useState(2)
  const [confirmLeave, setConfirmLeave] = useState(false)

  const reload = useCallback(() => teamApi.state(playerId).then(setState).catch((e) => setError(e.message)), [playerId])
  useEffect(() => {
    void reload()
  }, [reload, dateKey])

  const act = async (fn: () => Promise<TeamState | { message: string; state: TeamState }>) => {
    setError(null)
    setNotice(null)
    try {
      const out = await fn()
      if ('state' in out) {
        setState(out.state)
        setNotice(out.message)
      } else setState(out)
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (!state) return error ? <p className="text-sm text-red-400">{tx(error)}</p> : null
  const team = state.team
  return (
    <div className="space-y-6">
      {error && <p className="text-sm text-red-400">{tx(error)}</p>}
      {notice && <p className="text-sm text-green-400">{tx(notice)}</p>}

      {state.invite && (
        <InviteBanner
          invite={state.invite}
          onAccept={() => void act(() => teamApi.accept(playerId, state.invite!.id))}
          onDecline={() => void act(() => teamApi.decline(playerId, state.invite!.id))}
        />
      )}

      {!team && <FoundForm state={state} onFound={(n, tg) => void act(() => teamApi.found(playerId, n, tg))} />}

      {team && (
        <>
          <section className="space-y-4 rounded-xl bg-panel p-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-lg font-bold">
                {team.name} <span className="text-muted">[{team.tag}]</span>
              </h2>
              <span className="text-xs text-muted">
                {t('Your role')}: {ROLE_LABEL[team.user_role] ?? team.user_role} · {team.channel} · {t('founded {d}', { d: team.founded_on })}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Meter label={t('Chemistry')} value={team.chemistry} color="bg-green-500" />
              <Meter label={t('Reputation')} value={team.reputation} color="bg-osu-pink" />
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
              <span>
                {t('Learning after a scrim')}: +{team.perks.learning_bonus_pct}%
              </span>
              <span>
                {t('Nerves in clan cups')}: +{team.perks.nerve_bonus_pct}%
              </span>
              {team.perks.sponsor_monthly > 0 && <span>{t('Sponsor')}: ${team.perks.sponsor_monthly.toLocaleString('en-US')}/{t('month')}</span>}
              {team.cups_won > 0 && <span>{t('Cups won')}: {team.cups_won}</span>}
            </div>
            <div className="space-y-1.5">
              {team.members.length === 0 && <p className="text-sm text-muted">{t('Nobody here yet: recruit teammates below.')}</p>}
              {team.members.map((m) => (
                <MemberRow key={m.npc_id} m={m} onKick={() => void act(() => teamApi.kick(playerId, m.npc_id))} />
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted">{t('Scrim')}</span>
              <select value={hours} onChange={(e) => setHours(Number(e.target.value))} className="rounded bg-bg px-2 py-1 text-sm">
                {[1, 2, 3, 4].map((h) => (
                  <option key={h} value={h}>
                    {h} {t('h')}
                  </option>
                ))}
              </select>
              <button
                onClick={() => void act(() => teamApi.scrim(playerId, hours))}
                disabled={team.scrim_today || team.members.length === 0}
                className="rounded-full bg-osu-pink px-4 py-1.5 text-xs font-semibold hover:bg-osu-pink-dark disabled:opacity-40"
              >
                {team.scrim_today ? t('Played today') : t('Play a scrim')}
              </button>
              <span className="flex-1" />
              {confirmLeave ? (
                <>
                  <button onClick={() => void act(() => teamApi.leave(playerId))} className="rounded-full bg-red-700 px-3 py-1 text-xs">
                    {t('Really leave')}
                  </button>
                  <button onClick={() => setConfirmLeave(false)} className="rounded-full bg-panel-light px-3 py-1 text-xs text-muted">
                    {t('Cancel')}
                  </button>
                </>
              ) : (
                <button onClick={() => setConfirmLeave(true)} className="rounded-full bg-panel-light px-3 py-1 text-xs text-muted hover:text-white">
                  {t('Leave team')}
                </button>
              )}
            </div>
          </section>

          <section className="space-y-2 rounded-xl bg-panel p-5">
            <h2 className="text-sm uppercase tracking-wider text-muted">{t('Clan cups')}</h2>
            {!team.ready_for_cup && (
              <p className="text-xs text-amber-400">
                {t('A cup needs you and {n} active teammates.', { n: state.limits.cup_size - 1 })}
              </p>
            )}
            {state.cups.length === 0 && <p className="text-sm text-muted">{t('No clan cups on the calendar yet.')}</p>}
            {state.cups.map((c) => (
              <div key={c.id} className="flex items-center gap-3 rounded bg-bg px-3 py-2 text-sm">
                <div className="flex-1">
                  <b>{c.name}</b>
                  <div className="text-xs text-muted">
                    {t('registration from {a}, starts {b}', { a: c.registration_opens, b: c.start_date })}
                  </div>
                </div>
                {c.registered ? (
                  <span className="text-xs text-green-400">{t('registered')}</span>
                ) : (
                  <button
                    disabled={!c.can_register}
                    onClick={() => void act(async () => { await worldApi.register(playerId, c.id); return teamApi.state(playerId) })}
                    className="rounded-full bg-osu-pink px-3 py-1 text-xs font-semibold hover:bg-osu-pink-dark disabled:opacity-40"
                  >
                    {t('Register')}
                  </button>
                )}
              </div>
            ))}
          </section>

          <Recruiting
            playerId={playerId}
            full={team.size >= state.limits.max_size}
            onRecruited={(s, message) => {
              setState(s)
              setNotice(message)
              onChanged()
            }}
          />

          {team.log.length > 0 && (
            <section className="space-y-1 rounded-xl bg-panel p-5">
              <h2 className="text-sm uppercase tracking-wider text-muted">{t('Team log')}</h2>
              {team.log.map((l, i) => (
                <div key={i} className="text-xs">
                  <span className="text-muted">{l.date}</span> {tx(l.text)}
                </div>
              ))}
            </section>
          )}
        </>
      )}
    </div>
  )
}
