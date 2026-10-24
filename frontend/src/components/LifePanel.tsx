import { useCallback, useEffect, useState } from 'react'
import { lifeApi, type Player, type Rival, type Shop, type ShopItem } from '../api'
import { t, tx } from '../i18n'
import { DuelChallenger } from './DuelPanel'

const CATEGORY_LABEL: Record<string, string> = {
  mouse: t('Mouse'),
  tablet: t('Tablet'),
  software: t('Drivers'),
  keyboard: t('Keyboard'),
  monitor: t('Monitor'),
  chair: t('Chair & desk'),
}

const OCCUPATION_LABEL: Record<string, string> = {
  school: t('school'),
  university: t('university'),
  work: t('work'),
  pro: t('pro'),
}

const STYLE_LABEL: Record<string, string> = {
  mouse: t('mouse'),
  tablet: t('tablet'),
  alternate: t('alternate'),
  singletap: t('singletap'),
}

const pct = (x: number) => `${x > 1 ? '+' : ''}${Math.round((x - 1) * 100)}%`

/** What an item does, in one line. */
function itemEffects(i: ShopItem): string {
  const parts: string[] = []
  if (i.category === 'mouse' || i.category === 'tablet' || i.category === 'software') parts.push(`${t('aim')} ${pct(i.aim)}`)
  if (i.category === 'keyboard') parts.push(`${t('tapping')} ${pct(i.tapping)}`)
  if (i.ar_cap) parts.push(t('reads up to AR ~{n}', { n: (i.ar_cap / 10.5).toFixed(1).replace('.0', '') }))
  if (i.ergonomics != null) parts.push(t('ergonomics {n}%', { n: Math.round(i.ergonomics * 100) }))
  return parts.join(' · ')
}

function GearRow({ item: i, year, money, onBuy, onEquip }: { item: ShopItem; year: number; money: number; onBuy: () => void; onEquip: () => void }) {
  const lastYear = i.until === year && !i.owned
  const gone = i.until != null && i.until < year
  return (
    <div className="flex items-center gap-3 rounded bg-bg px-3 py-2 text-sm">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={i.equipped ? 'font-semibold text-osu-pink' : ''}>{t(i.name)}</span>
          {i.is_new && <span className="rounded bg-green-700 px-1 text-[10px] font-bold">{t('NEW')}</span>}
          {lastYear && <span className="rounded bg-amber-700 px-1 text-[10px]">{t('last year on sale')}</span>}
          {gone && <span className="rounded bg-panel-light px-1 text-[10px] text-muted">{t('discontinued')}</span>}
        </div>
        <div className="text-xs text-muted">
          {t('since {y}', { y: `${String(i.month).padStart(2, '0')}.${i.year}` })} · {itemEffects(i)}
          {i.notes && ` · ${t(i.notes)}`}
        </div>
      </div>
      {i.owned ? (
        i.equipped ? (
          <span className="text-xs text-green-400">{t('in use')}</span>
        ) : (
          <button onClick={onEquip} className="rounded-full bg-panel-light px-3 py-1 text-xs hover:bg-osu-pink">
            {t('Equip')}
          </button>
        )
      ) : (
        <button
          onClick={onBuy}
          disabled={money < i.price}
          title={i.price < i.launch_price ? t('Launch price ${n}', { n: i.launch_price }) : undefined}
          className="rounded-full bg-osu-pink px-3 py-1 text-xs font-semibold hover:bg-osu-pink-dark disabled:opacity-40"
        >
          {i.price < i.launch_price && <s className="mr-1 font-normal opacity-60">${i.launch_price}</s>}
          {i.price ? `$${i.price}` : t('free')}
        </button>
      )}
    </div>
  )
}

interface Props {
  player: Player
  dateKey: string
  onChanged: () => void
}

export function LifePanel({ player, dateKey, onChanged }: Props) {
  const [shop, setShop] = useState<Shop | null>(null)
  const [rivals, setRivals] = useState<Rival[]>([])
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(() => {
    lifeApi.shop(player.id).then(setShop)
    lifeApi.rivals(player.id).then(setRivals)
  }, [player.id])
  useEffect(reload, [reload, dateKey])

  const act = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
      reload()
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const life = player.life
  if (!life || !shop) return null
  const categories = Object.keys(CATEGORY_LABEL)
  const year = Number(player.in_game_date.slice(0, 4))

  return (
    <div className="space-y-6">
      {error && <p className="text-sm text-red-400">{tx(error)}</p>}

      <section className="space-y-3 rounded-xl bg-panel p-5">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Life')}</h2>
        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div>
            <div className="text-xs text-muted">{t('Age')}</div>
            <b>{life.age ?? '?'}</b>
          </div>
          <div>
            <div className="text-xs text-muted">{t('Money')}</div>
            <b className="text-green-300">${Math.round(life.money).toLocaleString('en-US')}</b>
          </div>
          <div>
            <div className="text-xs text-muted">{t('Free time today')}</div>
            <b>{life.free_hours_today}{t('h')}</b>
          </div>
          <div>
            <div className="text-xs text-muted">{t('Followers')}</div>
            <b>{life.followers.toLocaleString('en-US')}</b>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted">{t('Occupation')}</span>
          {['school', 'university', 'work', 'pro'].map((o) => (
            <button
              key={o}
              onClick={() => act(() => lifeApi.occupation(player.id, o))}
              className={`rounded-full px-3 py-0.5 text-xs ${life.occupation === o ? 'bg-osu-pink' : 'bg-panel-light text-muted hover:text-white'}`}
            >
              {OCCUPATION_LABEL[o]}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted">
          {t('Training beyond your free time costs sleep: fatigue and form suffer. Pros live off prizes, streaming and sponsors.')}
        </p>
      </section>

      <section className="space-y-3 rounded-xl bg-panel p-5">
        <h2 className="text-sm uppercase tracking-wider text-muted">{t('Playstyle')}</h2>
        <div className="flex flex-wrap gap-4 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-muted">{t('Input')}</span>
            {['mouse', 'tablet'].map((d) => (
              <button
                key={d}
                onClick={() => act(() => lifeApi.playstyle(player.id, { input_device: d }))}
                className={`rounded-full px-3 py-0.5 text-xs ${life.input_device === d ? 'bg-osu-pink' : 'bg-panel-light text-muted hover:text-white'}`}
              >
                {STYLE_LABEL[d]}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-muted">{t('Tapping')}</span>
            {['alternate', 'singletap'].map((d) => (
              <button
                key={d}
                onClick={() => act(() => lifeApi.playstyle(player.id, { tap_style: d }))}
                className={`rounded-full px-3 py-0.5 text-xs ${life.tap_style === d ? 'bg-osu-pink' : 'bg-panel-light text-muted hover:text-white'}`}
              >
                {STYLE_LABEL[d]}
              </button>
            ))}
          </div>
        </div>
        <div className="text-xs text-muted">
          {t('Adaptation {n}%: switching setups costs performance until you get used to it. Singletap caps burst speed; a tablet suits flow aim, a mouse suits jumps.', { n: Math.round(life.style_adaptation * 100) })}
        </div>
      </section>

      <section className="space-y-3 rounded-xl bg-panel p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm uppercase tracking-wider text-muted">{t('Gear shop')}</h2>
          <span className="text-xs text-muted">
            {t('Your setup')}: {t('aim')} {pct(shop.effects.aim)} · {t('tapping')} {pct(shop.effects.tapping)} · AR ~
            {((shop.effects.ar_cap ?? 60) / 10.5).toFixed(1)}
            {shop.effects.missing.length > 0 && <span className="text-red-400"> · {t('no {d}!', { d: STYLE_LABEL[shop.effects.missing[0]] ?? shop.effects.missing[0] })}</span>}
          </span>
        </div>
        <p className="text-xs text-muted">
          {t('Only what is on sale in {y}: new models come out over the years, old ones are discontinued and get cheaper with age.', { y: year })}
        </p>
        {categories.map((cat) => {
          const items = shop.items.filter((i) => i.category === cat && (i.available || i.owned))
          if (items.length === 0) return null
          return (
            <div key={cat} className="space-y-1">
              <div className="text-xs uppercase text-muted">{CATEGORY_LABEL[cat]}</div>
              {items.map((i) => (
                <GearRow
                  key={i.key}
                  item={i}
                  year={year}
                  money={shop.money}
                  onBuy={() => act(() => lifeApi.buy(player.id, i.key))}
                  onEquip={() => act(() => lifeApi.equip(player.id, i.key))}
                />
              ))}
            </div>
          )
        })}
      </section>

      {rivals.length > 0 && (
        <section className="space-y-2 rounded-xl bg-panel p-5">
          <h2 className="text-sm uppercase tracking-wider text-muted">{t('Rivals')}</h2>
          {rivals.map((r) => (
            <div key={r.npc_id} className="space-y-2 rounded bg-bg px-3 py-2 text-sm">
            <div className="flex items-center gap-3">
              <div className="flex-1">
                <b>{r.name}</b> <span className="text-muted">[{r.country}]</span>
                <div className="text-xs text-muted">
                  #{r.rank?.toLocaleString('en-US')} · {t('snipes')} {r.record.snipes_for ?? 0}–{r.record.snipes_against ?? 0} · {t('matches')}{' '}
                  {r.record.matches_won ?? 0}–{r.record.matches_lost ?? 0}
                </div>
              </div>
              <div className="w-24" title={t('How personal it is')}>
                <div className="h-1.5 rounded-full bg-panel-light">
                  <div className="h-full rounded-full bg-red-500" style={{ width: `${r.heat}%` }} />
                </div>
              </div>
            </div>
            <DuelChallenger playerId={player.id} npcId={r.npc_id} npcName={r.name} rival onPlayed={onChanged} />
            </div>
          ))}
        </section>
      )}
    </div>
  )
}
