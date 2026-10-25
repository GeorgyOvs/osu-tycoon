import { useEffect, useState, type FormEvent } from 'react'
import { api, fmt, type Player, type CharacterOptions } from '../api'
import { getLang, setLang, t, tx } from '../i18n'

export function PlayerSelect({ onSelect }: { onSelect: (id: number) => void }) {
  const [players, setPlayers] = useState<Player[]>([])
  const [name, setName] = useState('')
  const [country, setCountry] = useState('RU')
  const [startDate, setStartDate] = useState('2014-01-01')
  const [age, setAge] = useState(15)
  const [gender, setGender] = useState('unspecified')
  const [error, setError] = useState<string | null>(null)
  const [options, setOptions] = useState<CharacterOptions | null>(null)
  const [optionsError, setOptionsError] = useState(false)
  const [preset, setPreset] = useState('random')
  const [perks, setPerks] = useState<string[]>([])
  const [unbalanced, setUnbalanced] = useState(false)
  const [scenario, setScenario] = useState('newcomer')
  const [hardcore, setHardcore] = useState(false)
  const [realisticEconomy, setRealisticEconomy] = useState(false)
  const spent = perks.reduce((sum, key) => sum + (options?.perks[key]?.cost ?? 0), 0)
  const overBudget = !unbalanced && spent > (options?.budget ?? 4)

  const reload = () => api.listPlayers().then(setPlayers).catch((e) => setError(e.message))
  useEffect(() => {
    void reload()
    api.creationOptions().then(setOptions).catch(() => setOptionsError(true))
  }, [])

  const create = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      if (overBudget) return
      const p = await api.createPlayer({ name, country, start_date: startDate, age, gender,
        preset, ...(preset !== 'random' ? { perks } : {}), unbalanced, scenario, hardcore, realistic_economy: realisticEconomy })
      onSelect(p.id)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const remove = async (id: number) => {
    const target = players.find((p) => p.id === id)
    let typed: string | undefined
    if (target?.character_build?.hardcore) {
      typed = prompt(t('Delete hardcore career: type its name to confirm')) ?? undefined
      if (!typed) return
    } else if (!confirm(t('Delete this career? This cannot be undone.'))) return
    try {
      await api.deletePlayer(id, typed)
    } catch (err) {
      setError((err as Error).message)
    }
    void reload()
  }

  return (
    <div className="mx-auto mt-16 max-w-xl space-y-8 px-4">
      <h1 className="text-center text-4xl font-bold">
        osu! <span className="text-osu-pink">Tycoon</span>
      </h1>
      <div className="-mt-6 text-center">
        <button onClick={() => setLang(getLang() === 'ru' ? 'en' : 'ru')} className="rounded bg-panel px-2 py-0.5 text-xs text-muted hover:text-white">
          {getLang() === 'ru' ? 'Русский · switch to English' : 'English · переключить на русский'}
        </button>
      </div>

      {players.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm uppercase tracking-wider text-muted">{t('Continue career')}</h2>
          {players.map((p) => (
            <div key={p.id} className="flex items-center gap-2">
              <button
                onClick={() => onSelect(p.id)}
                className="flex flex-1 items-center justify-between rounded-lg bg-panel px-4 py-3 text-left hover:bg-panel-light"
              >
                <span>
                  <span className="font-semibold">{p.name}</span>{' '}
                  <span className="text-muted">[{p.country}]</span>
                </span>
                <span className="text-sm text-muted">
                  {p.in_game_date} · {fmt.pp(p.total_pp)} · {fmt.rank(p.global_rank)}
                </span>
              </button>
              <button
                onClick={() => remove(p.id)}
                title={t('Delete')}
                className="rounded-lg bg-panel px-3 py-3 text-muted hover:bg-red-900 hover:text-white"
              >
                ✕
              </button>
            </div>
          ))}
        </section>
      )}

      <form onSubmit={create} className="space-y-4 rounded-xl bg-panel p-6">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('New career')}</h2>
        <div className="grid grid-cols-[1fr_5rem] gap-3">
          <input
            required
            maxLength={32}
            placeholder={t('Username')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded bg-bg px-3 py-2 outline-none focus:ring-2 focus:ring-osu-pink"
          />
          <input
            required
            pattern="[A-Za-z]{2}"
            title={t('Two-letter country code')}
            value={country}
            onChange={(e) => setCountry(e.target.value.toUpperCase())}
            className="rounded bg-bg px-3 py-2 text-center uppercase outline-none focus:ring-2 focus:ring-osu-pink"
          />
        </div>
        <label className="block space-y-1">
          <span className="text-sm text-muted">{t('Starting date')}</span>
          <input
            type="date"
            required
            min="2007-09-16"
            max="2024-12-31"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="w-full rounded bg-bg px-3 py-2 outline-none [color-scheme:dark] focus:ring-2 focus:ring-osu-pink"
          />
        </label>
        <label className="block space-y-1">
          <span className="text-sm text-muted">{t('Starting age')}: {age}</span>
          <input type="range" min={7} max={30} value={age} onChange={(e) => setAge(Number(e.target.value))} className="w-full accent-osu-pink" />
        </label>
        <label className="block space-y-1">
          <span className="text-sm text-muted">{t('Gender (role-play only, no effect on gameplay)')}</span>
          <select
            value={gender}
            onChange={(e) => setGender(e.target.value)}
            className="w-full rounded bg-bg px-3 py-2 outline-none focus:ring-2 focus:ring-osu-pink"
          >
            <option value="unspecified">{t('Prefer not to say (they/them)')}</option>
            <option value="female">{t('Female (she/her)')}</option>
            <option value="male">{t('Male (he/him)')}</option>
            <option value="nonbinary">{t('Non-binary (they/them)')}</option>
          </select>
        </label>
        <fieldset className="space-y-2 rounded bg-bg p-3">
          <legend className="text-sm">{t('Starting level')}</legend>
          <select aria-label={t('Starting level')} value={scenario} disabled={!options?.scenarios}
            onChange={(e) => {
              const key = e.target.value
              setScenario(key)
              const min = options?.scenarios?.[key]?.min_age ?? 7
              if (age < min) setAge(min)
            }} className="w-full rounded bg-panel p-2">
            {Object.entries(options?.scenarios ?? { newcomer: { label: t('Newcomer'), description: '', min_age: 7 } }).map(([key, s]) => (
              <option key={key} value={key}>{s.label}</option>
            ))}
          </select>
          {options?.scenarios?.[scenario] && (
            <p className="text-xs text-muted">
              {options.scenarios[scenario].description}
              {options.scenarios[scenario].min_age > 7 && ` · ${t('from age {n}', { n: options.scenarios[scenario].min_age })}`}
            </p>
          )}
        </fieldset>
        <fieldset className="space-y-2 rounded bg-bg p-3">
          <label className="flex gap-2 text-sm">
            <input type="checkbox" checked={hardcore} onChange={(e) => setHardcore(e.target.checked)} />
            {t('Hardcore (no second chances)')}
          </label>
          <p className="text-xs text-muted">
            {t('Harsher injuries, tougher default outcomes, deleting needs a typed confirmation. Months in debt or a career-ending injury end the run.')}
          </p>
          <label className="flex gap-2 text-sm">
            <input type="checkbox" checked={realisticEconomy} onChange={(e) => setRealisticEconomy(e.target.checked)} />
            {t('Realistic economy (living costs, taxes, loans)')}
          </label>
          <p className="text-xs text-muted">
            {t('Rent, tuition, taxes on winnings, interest on debt and loans. Off keeps the simple balance.')}
          </p>
        </fieldset>
        <fieldset className="space-y-3 rounded bg-bg p-3">
          <legend className="text-sm">{t('Character build')}</legend>
          <select aria-label={t('Character preset')} value={preset} disabled={!options}
            onChange={(e) => {
              const key = e.target.value
              setPreset(key)
              setPerks(options?.presets[key]?.perks ?? [])
            }} className="w-full rounded bg-panel p-2">
            <option value="random">{t('Random talents and weaknesses')}</option>
            {Object.entries(options?.presets ?? {}).map(([key, p]) => <option key={key} value={key}>{p.label}</option>)}
            <option value="custom">{t('Custom build')}</option>
          </select>
          {optionsError && <p className="text-xs text-amber-300">{t('Restart the backend to enable character presets.')}</p>}
          {preset !== 'random' && options && <>
            <label className="flex gap-2 text-sm">
              <input type="checkbox" checked={unbalanced} onChange={(e) => setUnbalanced(e.target.checked)} />
              {t('Unbalanced character (unlimited points)')}
            </label>
            <p className={`text-sm ${overBudget ? 'text-red-400' : 'text-muted'}`}>
              {t('Balance points')}: {unbalanced ? '∞' : options.budget - spent}
              {' · '}{t('Spent')}: {spent} / {options.budget}
            </p>
            <p className="text-xs text-muted">{t('Weaknesses refund points. Talents affect starting skills and future learning.')}</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {Object.entries(options.perks).map(([key, perk]) => {
                const conflict = options.conflicts.some(([a, b]) => (a === key && perks.includes(b)) || (b === key && perks.includes(a)))
                return <label key={key} className={`rounded bg-panel p-2 text-xs ${conflict ? 'opacity-40' : ''}`}>
                  <span className="flex gap-2">
                    <input type="checkbox" checked={perks.includes(key)} disabled={conflict}
                      onChange={(e) => { setPreset('custom'); setPerks(e.target.checked ? [...perks, key] : perks.filter((p) => p !== key)) }} />
                    <b>{perk.label}</b><span className={perk.cost > 0 ? 'text-osu-pink' : 'text-green-300'}>{perk.cost > 0 ? '−' : '+'}{Math.abs(perk.cost)}</span>
                  </span>
                  <span className="mt-1 block text-muted">{perk.description}</span>
                </label>
              })}
            </div>
          </>}
        </fieldset>
        {error && <p className="text-sm text-red-400">{tx(error)}</p>}
        <button disabled={overBudget} className="w-full rounded-full bg-osu-pink py-2 font-semibold hover:bg-osu-pink-dark disabled:opacity-40">
          {t('Start career')}
        </button>
      </form>
    </div>
  )
}
