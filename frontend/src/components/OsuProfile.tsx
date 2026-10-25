import { useEffect, useState } from 'react'
import { fmt, profileApi, type OsuProfile as Page, type PlayerProfile } from '../api'
import { legacyApi, type AchievementInfo } from '../api.legacy'
import { t, tx } from '../i18n'
import { PlayerAvatar } from './Avatar'
import { TournamentBadge } from './Badge'
import { HistoryChart } from './HistoryChart'
import { ScoreRow } from './ScoreRow'

const flag = (cc: string) =>
  /^[A-Z]{2}$/.test(cc) ? String.fromCodePoint(...[...cc].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65)) : '🏳'

const RARITY: Record<string, string> = {
  common: 'from-slate-500 to-slate-700',
  uncommon: 'from-emerald-500 to-emerald-800',
  rare: 'from-sky-500 to-sky-800',
  epic: 'from-fuchsia-500 to-fuchsia-800',
  legendary: 'from-amber-400 to-orange-700',
}

const GRADES: [keyof Page['grades'], string, string][] = [
  ['XH', 'SS', 'text-slate-100 bg-slate-500/30'],
  ['X', 'SS', 'text-yellow-200 bg-yellow-500/20'],
  ['SH', 'S', 'text-slate-200 bg-slate-500/25'],
  ['S', 'S', 'text-yellow-300 bg-yellow-500/15'],
  ['A', 'A', 'text-green-300 bg-green-500/15'],
]

function playtime(seconds: number) {
  const h = Math.floor(seconds / 3600)
  const d = Math.floor(h / 24)
  return d > 0 ? t('{d}d {h}h', { d, h: h % 24 }) : t('{h}h {m}m', { h, m: Math.floor((seconds % 3600) / 60) })
}

function Big({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="text-2xl font-bold leading-tight">{value}</div>
      {sub && <div className="text-[11px] text-muted">{sub}</div>}
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 py-0.5 text-sm">
      <span className="text-muted">{label}</span>
      <span className="font-semibold tabular-nums">{value}</span>
    </div>
  )
}

export function OsuProfile({ playerId, profile, dateKey }: { playerId: number; profile: PlayerProfile; dateKey: string }) {
  const [page, setPage] = useState<Page | null>(null)
  const [medals, setMedals] = useState<{ unlocked: AchievementInfo[]; total: number } | null>(null)
  const [chart, setChart] = useState<'rank' | 'pp'>('rank')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    profileApi.get(playerId).then(setPage).catch((e: Error) => setError(e.message))
    legacyApi
      .get(playerId)
      .then((l) => setMedals({ unlocked: l.achievements.unlocked, total: l.achievements.total }))
      .catch(() => setMedals(null))
  }, [playerId, dateKey])

  if (!page) return <p className="text-sm text-muted">{error ? tx(error) : t('Loading…')}</p>

  const rankPoints = page.history.filter((p) => p.rank != null).map((p) => ({ date: p.date, value: p.rank as number }))
  const ppPoints = page.history.map((p) => ({ date: p.date, value: p.pp }))
  const totalGrades = Object.values(page.grades).reduce((a, b) => a + b, 0)

  return (
    <div className="space-y-4">
      {/* cover */}
      <section className="overflow-hidden rounded-xl bg-panel">
        <div className="h-24 bg-gradient-to-r from-osu-pink/70 via-fuchsia-700/60 to-indigo-800/70" />
        <div className="-mt-12 flex flex-wrap items-end gap-4 px-5 pb-4">
          <div className="rounded-full ring-4 ring-panel">
            <PlayerAvatar playerId={playerId} name={profile.name} size={104} editable />
          </div>
          <div className="min-w-0 flex-1 pb-1">
            <h2 className="truncate text-2xl font-bold">{profile.name}</h2>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
              <span>
                {flag(profile.country)} {profile.country}
              </span>
              <span>{t('Joined {d}', { d: page.joined })}</span>
              <span className="rounded bg-panel-light px-1.5 text-xs">
                {page.input_device === 'tablet' ? t('Tablet') : t('Mouse')} · {t('Keyboard')} ({tx(page.tap_style)})
              </span>
              {page.followers > 0 && <span>{t('{n} followers', { n: page.followers.toLocaleString('en-US') })}</span>}
            </div>
          </div>
          <div className="flex items-center gap-3 pb-1">
            <div className="relative flex h-14 w-14 items-center justify-center" title={t('Level progress {n}%', { n: Math.round(page.level_progress * 100) })}>
              <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90">
                <circle cx="18" cy="18" r="15.5" fill="none" stroke="#382d32" strokeWidth="3" />
                <circle
                  cx="18"
                  cy="18"
                  r="15.5"
                  fill="none"
                  stroke="#ff66aa"
                  strokeWidth="3"
                  strokeDasharray={`${(page.level_progress * 97.4).toFixed(1)} 97.4`}
                  strokeLinecap="round"
                />
              </svg>
              <span className="text-lg font-bold">{page.level}</span>
            </div>
          </div>
        </div>
        {profile.badges.length > 0 && (
          <div className="flex flex-wrap gap-1.5 border-t border-panel-light px-5 py-3">
            {profile.badges.map((b) => (
              <TournamentBadge key={b.tournament_id} name={b.name} date={b.date} tier={b.tier} />
            ))}
          </div>
        )}
      </section>

      {/* ranks + chart */}
      <section className="space-y-4 rounded-xl bg-panel p-5">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Big label={t('Global ranking')} value={fmt.rank(page.global_rank)} sub={page.peak_rank ? t('peak #{n} · {d}', { n: page.peak_rank.toLocaleString('en-US'), d: page.peak_date ?? '' }) : undefined} />
          <Big label={t('Country ranking')} value={fmt.rank(page.country_rank)} sub={`${flag(profile.country)} ${profile.country}`} />
          <Big label={t('Performance')} value={fmt.pp(page.pp)} />
          <Big label={t('Accuracy')} value={fmt.acc(page.accuracy)} />
        </div>
        <div>
          <div className="mb-1 flex gap-1 text-xs">
            {(['rank', 'pp'] as const).map((k) => (
              <button
                key={k}
                onClick={() => setChart(k)}
                className={`rounded-full px-3 py-0.5 ${chart === k ? 'bg-panel-light text-white ring-1 ring-osu-pink' : 'text-muted hover:text-white'}`}
              >
                {k === 'rank' ? t('Rank history') : t('pp history')}
              </button>
            ))}
          </div>
          {chart === 'rank' ? (
            <HistoryChart points={rankPoints} kind="rank" label={t('Global rank')} />
          ) : (
            <HistoryChart points={ppPoints} kind="pp" label={t('Performance')} />
          )}
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {/* stats */}
        <section className="space-y-3 rounded-xl bg-panel p-5">
          <div>
            <Row label={t('Ranked score')} value={page.ranked_score.toLocaleString('en-US')} />
            <Row label={t('Hit accuracy')} value={fmt.acc(page.accuracy)} />
            <Row label={t('Play count')} value={page.play_count.toLocaleString('en-US')} />
            <Row label={t('Play time')} value={playtime(page.play_time_seconds)} />
            <Row label={t('Total score')} value={page.total_score.toLocaleString('en-US')} />
            <Row label={t('Total hits')} value={page.total_hits.toLocaleString('en-US')} />
            <Row label={t('Maximum combo')} value={`${page.max_combo.toLocaleString('en-US')}x`} />
          </div>
          <div className="flex flex-wrap gap-2" title={t('Grades of your best play on each map')}>
            {GRADES.map(([key, label, style]) => (
              <div key={key} className={`min-w-14 rounded-lg px-2 py-1 text-center ${style}`}>
                <div className="text-base font-black italic">{label}</div>
                <div className="text-xs tabular-nums">{page.grades[key]}</div>
              </div>
            ))}
            {totalGrades === 0 && <span className="self-center text-xs text-muted">{t('No grades yet.')}</span>}
          </div>
        </section>

        {/* me! */}
        <section className="space-y-2 rounded-xl bg-panel p-5">
          <div className="flex items-center justify-between">
            <h3 className="text-sm uppercase tracking-wider text-muted">me!</h3>
            {!editing && (
              <button
                onClick={() => {
                  setDraft(page.me)
                  setEditing(true)
                }}
                className="text-xs text-muted hover:text-white"
              >
                ✎ {t('Edit')}
              </button>
            )}
          </div>
          {editing ? (
            <form
              className="space-y-2"
              onSubmit={async (e) => {
                e.preventDefault()
                setPage(await profileApi.setMe(playerId, draft))
                setEditing(false)
              }}
            >
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                maxLength={2000}
                rows={6}
                placeholder={t('Write something about yourself: your setup, goals, favourite maps…')}
                className="w-full rounded bg-bg p-2 text-sm outline-none focus:ring-1 focus:ring-osu-pink"
              />
              <div className="flex justify-end gap-2 text-xs">
                <button type="button" onClick={() => setEditing(false)} className="rounded-full px-3 py-1 text-muted hover:text-white">
                  {t('Cancel')}
                </button>
                <button className="rounded-full bg-osu-pink px-3 py-1 font-semibold">{t('Save')}</button>
              </div>
            </form>
          ) : page.me ? (
            <p className="text-sm whitespace-pre-wrap break-words">{page.me}</p>
          ) : (
            <p className="text-sm text-muted">{t('Nothing here yet. Tell the world who you are.')}</p>
          )}
        </section>
      </div>

      {/* medals */}
      {medals && (
        <section className="space-y-2 rounded-xl bg-panel p-5">
          <h3 className="text-sm uppercase tracking-wider text-muted">
            {t('Medals')} ({medals.unlocked.length}/{medals.total})
          </h3>
          {medals.unlocked.length === 0 && <p className="text-sm text-muted">{t('No medals yet.')}</p>}
          <div className="flex flex-wrap gap-2">
            {medals.unlocked.map((m) => (
              <div
                key={m.key}
                title={`${m.name}: ${m.description}${m.unlocked_on ? ` (${m.unlocked_on})` : ''}`}
                className={`flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br text-center text-[9px] leading-tight font-bold shadow ring-2 ring-black/30 ${RARITY[m.rarity] ?? RARITY.common}`}
              >
                <span className="line-clamp-3 px-1">{m.name}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* plays */}
      <section className="space-y-2">
        <h3 className="text-sm uppercase tracking-wider text-muted">
          {t('Best performance')} ({profile.top_plays.length})
        </h3>
        {profile.top_plays.length === 0 && <p className="text-sm text-muted">{t('No scores yet.')}</p>}
        {profile.top_plays.map((s) => (
          <ScoreRow
            key={s.id}
            playerId={playerId}
            dateKey={dateKey}
            score={s}
            extra={
              <div className="text-xs text-muted">
                {Math.round(s.weighted_pp)}pp ({Math.round(s.weight * 100)}%)
              </div>
            }
          />
        ))}
      </section>
      {profile.recent_scores.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm uppercase tracking-wider text-muted">{t('Recent plays')}</h3>
          {profile.recent_scores.map((s) => (
            <ScoreRow key={s.id} score={s} playerId={playerId} dateKey={dateKey} />
          ))}
        </section>
      )}
    </div>
  )
}
