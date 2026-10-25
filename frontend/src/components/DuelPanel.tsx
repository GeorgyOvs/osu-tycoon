import { useEffect, useState } from 'react'
import { duelApi, fmt, starColor, type Duel, type DuelChallenge } from '../api'
import { t, tx } from '../i18n'
import { MatchMaps } from './TournamentsPanel'
import { MapHint } from './MapHint'
import { slotMods } from '../api.hints'

const FORMATS = [1, 3, 5, 7, 9, 11, 13]
const DIFFICULTY_LABEL: Record<DuelChallenge['difficulty'], string> = {
  comfortable: t('Comfortable'),
  even: t('Even'),
  hard: t('Hard'),
}

function ResultLine({ duel }: { duel: Duel }) {
  return (
    <div className="flex items-center gap-2">
      <span className={`rounded px-1.5 text-xs font-bold ${duel.won ? 'bg-green-700' : 'bg-red-800'}`}>{duel.won ? t('WIN') : t('LOSS')}</span>
      <span className="font-mono font-bold">
        {duel.score_user}–{duel.score_npc}
      </span>
      <span className="text-muted">
        {t('vs')} {duel.opponent} · BO{duel.best_of} {duel.kind === 'rival' ? t('rival match') : t('friendly')}
      </span>
    </div>
  )
}

interface ChallengerProps {
  playerId: number
  npcId: number
  npcName: string
  rival?: boolean
  onPlayed?: () => void
}

/** Challenge someone to a 1v1: choose a format, see the drawn pool, plan bans and picks, play. */
export function DuelChallenger({ playerId, npcId, npcName, rival = false, onPlayed }: ChallengerProps) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<DuelChallenge>({
    npc_id: npcId,
    best_of: 5,
    kind: rival ? 'rival' : 'friendly',
    difficulty: 'even',
    bans_per_side: 1,
  })
  const [duel, setDuel] = useState<Duel | null>(null)
  const [mode, setMode] = useState<'ban' | 'pick'>('ban')
  const [bans, setBans] = useState<string[]>([])
  const [picks, setPicks] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

  const reset = () => {
    setDuel(null)
    setBans([])
    setPicks([])
    setMode('ban')
  }

  if (!open)
    return (
      <button onClick={() => setOpen(true)} className="rounded bg-panel-light px-2 py-1 text-xs font-semibold hover:bg-osu-pink">
        ⚔ {rival ? t('Rival 1v1') : t('Challenge to 1v1')}
      </button>
    )

  const field = 'rounded bg-panel px-1.5 py-1 text-xs outline-none focus:ring-1 focus:ring-osu-pink'
  const choosable = duel?.status === 'pending' ? duel.pool.filter((s) => s.slot && s.slot !== 'TB') : []
  const toggle = (slot: string) => {
    if (mode === 'ban') {
      setPicks(picks.filter((x) => x !== slot))
      setBans(bans.includes(slot) ? bans.filter((x) => x !== slot) : bans.length < (duel?.bans_per_side ?? 0) ? [...bans, slot] : bans)
    } else {
      setBans(bans.filter((x) => x !== slot))
      setPicks(picks.includes(slot) ? picks.filter((x) => x !== slot) : [...picks, slot])
    }
  }

  return (
    <div className="space-y-2 rounded-lg bg-panel p-3 text-xs" data-testid="duel">
      <div className="flex items-center justify-between">
        <b className="text-sm">{t('1v1 vs {name}', { name: npcName })}</b>
        <button
          onClick={() => {
            setOpen(false)
            reset()
          }}
          className="text-muted hover:text-white"
        >
          ✕
        </button>
      </div>

      {!duel && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1">
              {t('Format')}
              <select
                aria-label={t('Format')}
                value={form.best_of}
                onChange={(e) => setForm({ ...form, best_of: Number(e.target.value) })}
                className={field}
              >
                {FORMATS.map((n) => (
                  <option key={n} value={n}>
                    BO{n}
                  </option>
                ))}
              </select>
            </label>
            {rival && (
              <label className="flex items-center gap-1">
                {t('Type')}
                <select
                  value={form.kind}
                  onChange={(e) => setForm({ ...form, kind: e.target.value as DuelChallenge['kind'] })}
                  className={field}
                >
                  <option value="rival">{t('Rival (higher stakes)')}</option>
                  <option value="friendly">{t('Friendly')}</option>
                </select>
              </label>
            )}
            <label className="flex items-center gap-1">
              {t('Pool')}
              <select
                value={form.difficulty}
                onChange={(e) => setForm({ ...form, difficulty: e.target.value as DuelChallenge['difficulty'] })}
                className={field}
              >
                {Object.entries(DIFFICULTY_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1">
              {t('Bans each')}
              <select
                value={form.bans_per_side}
                onChange={(e) => setForm({ ...form, bans_per_side: Number(e.target.value) })}
                className={field}
              >
                {[0, 1, 2].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="text-muted">
            {t('Skill decides most of it, but form, nerves, map knowledge and luck can swing any map. Up to 3 1v1s a day; each one tires your hands.')}{' '}
            {form.kind === 'rival' && t('Rival matches hit morale twice as hard, either way.')}
          </p>
          <button
            disabled={busy}
            onClick={() => run(async () => setDuel(await duelApi.challenge(playerId, form)))}
            className="rounded-full bg-osu-pink px-4 py-1.5 font-semibold hover:bg-osu-pink-dark disabled:opacity-50"
          >
            {busy ? t('Asking…') : t('Send challenge')}
          </button>
        </>
      )}

      {duel?.status === 'pending' && (
        <>
          <div className="text-muted">
            {t('{name} accepted!', { name: npcName })} BO{duel.best_of} · {t('first to {n}', { n: (duel.best_of + 1) / 2 })}
            {duel.pool.some((s) => s.slot === 'TB') && ` · ${t('tiebreaker at match point')}`}.{' '}
            {t('Plan your bans and picks (optional; the AI fills the rest).')}
          </div>
          <div className="flex gap-1" role="radiogroup">
            {(['ban', 'pick'] as const).map((m) => (
              <button
                key={m}
                role="radio"
                aria-checked={mode === m}
                disabled={m === 'ban' && duel.bans_per_side === 0}
                onClick={() => setMode(m)}
                className={`rounded px-2 py-0.5 disabled:opacity-40 ${mode === m ? (m === 'ban' ? 'bg-red-700' : 'bg-green-700') : 'bg-bg'}`}
              >
                {m === 'ban' ? `${t('Ban')} (${bans.length}/${duel.bans_per_side})` : `${t('Pick order')} (${picks.length})`}
              </button>
            ))}
          </div>
          <div className="space-y-0.5">
            {duel.pool.map((s) => {
              const slot = s.slot as string
              const ban = bans.includes(slot)
              const pick = picks.indexOf(slot)
              const isTb = slot === 'TB'
              return (
                <button
                  key={slot}
                  disabled={isTb}
                  onClick={() => toggle(slot)}
                  className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left ${
                    ban ? 'bg-red-900/60 line-through' : pick >= 0 ? 'bg-green-900/50' : 'bg-bg hover:bg-panel-light'
                  } disabled:cursor-default`}
                >
                  <span className="w-8 font-bold">{slot}</span>
                  <MapHint playerId={playerId} beatmapId={s.beatmap_id} mods={slotMods(slot)} className="min-w-0 flex-1 truncate">
                    {s.title || '—'}
                  </MapHint>
                  {s.stars != null && <span style={{ color: starColor(s.stars) }}>~{s.stars.toFixed(2)}★</span>}
                  <span className="w-6 text-right">{pick >= 0 ? `#${pick + 1}` : ban ? '🚫' : isTb ? 'TB' : ''}</span>
                </button>
              )
            })}
          </div>
          {choosable.length > 0 && (
            <button
              disabled={busy}
              onClick={() => run(async () => {
                setDuel(await duelApi.play(playerId, duel.id, { bans, picks }))
                onPlayed?.()
              })}
              className="rounded-full bg-osu-pink px-4 py-1.5 font-semibold hover:bg-osu-pink-dark disabled:opacity-50"
            >
              {busy ? t('Playing…') : t('Play 1v1')}
            </button>
          )}
        </>
      )}

      {duel?.status === 'played' && (
        <>
          <ResultLine duel={duel} />
          <MatchMaps maps={duel.maps} names={[t('You'), duel.opponent]} commentary={duel.commentary} />
          <button onClick={reset} className="rounded bg-panel-light px-3 py-1 font-semibold hover:bg-osu-pink">
            {t('Rematch / new 1v1')}
          </button>
        </>
      )}

      {error && <p className="text-red-400">{tx(error)}</p>}
    </div>
  )
}

/** Recent 1v1 results, expandable to the full map-by-map story. */
export function DuelHistory({ playerId, dateKey }: { playerId: number; dateKey: string }) {
  const [duels, setDuels] = useState<Duel[]>([])
  const [open, setOpen] = useState<number | null>(null)
  useEffect(() => {
    duelApi.history(playerId).then(setDuels).catch(() => setDuels([]))
  }, [playerId, dateKey])
  return (
    <section className="space-y-2 rounded-xl bg-panel p-5">
      <h2 className="text-sm uppercase tracking-wider text-muted">{t('1v1s')}</h2>
      {duels.length === 0 ? (
        <p className="text-sm text-muted">
          {t('No 1v1s yet. Open a player in the World tab (or a rival in Life) and challenge them: BO1 to BO13, with a pool, bans and picks.')}
        </p>
      ) : (
        duels.map((d) => (
          <div key={d.id} className="rounded bg-bg text-sm">
            <button onClick={() => setOpen(open === d.id ? null : d.id)} className="flex w-full items-center gap-2 px-3 py-2 text-left">
              <span className="text-xs text-muted">{d.date}</span>
              <ResultLine duel={d} />
              <span className="ml-auto text-xs text-muted">{fmt.rank(d.opponent_rank)}</span>
            </button>
            {open === d.id && (
              <div className="p-2">
                <MatchMaps maps={d.maps} names={[t('You'), d.opponent]} commentary={d.commentary} />
              </div>
            )}
          </div>
        ))
      )}
    </section>
  )
}
