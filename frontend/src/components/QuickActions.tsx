import { useRef, useState } from 'react'
import { api, presetApi, weekApi, type ActionResult, type Player, type SessionResult, type WeekDay, type WeekResult } from '../api'
import { t, tx } from '../i18n'
import { useHotkeys } from '../useHotkeys'
import { defaultPlan, STORAGE_KEY } from './WeekPlanner'

/** Read a value saved by usePersisted() elsewhere, at the moment it's needed. */
function persisted<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(`tycoon.ui.${key}`)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

function weekPlan(occupation: string): WeekDay[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as WeekDay[]) : defaultPlan(occupation)
  } catch {
    return defaultPlan(occupation)
  }
}

// G then a letter switches tabs; digits jump to the four groups.
const TAB_KEYS: Record<string, string> = {
  t: 'training', p: 'beatmaps', o: 'tournaments', w: 'world', c: 'chat', f: 'social',
  r: 'profile', s: 'story', m: 'team', l: 'life', y: 'legacy',
}
const GROUP_KEYS: Record<string, string> = { '1': 'training', '2': 'tournaments', '3': 'chat', '4': 'profile' }

const HELP: [string, string][] = [
  ['R', 'Rest one day'],
  ['W', 'Live a week'],
  ['S', 'Auto session'],
  ['1-4', 'Switch group'],
  ['G T / P / O / W / C / F', 'Training / Play / Tournaments / World / Chats / Forum'],
  ['G R / S / M / L / Y', 'Profile / Story / Team / Life / Legacy'],
  ['Ctrl+K', 'Search'],
  ['?', 'This help'],
]

export function QuickActions({
  player,
  onAction,
  onWeek,
  onSession,
  onTab,
}: {
  player: Player
  onAction: (r: ActionResult) => void
  onWeek: (w: WeekResult) => void
  onSession: (r: SessionResult, replay: { preset: string; hours: number; stream: boolean }) => void
  onTab: (tab: string) => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [help, setHelp] = useState(false)
  const pendingG = useRef(0)

  const run = async (key: string, fn: () => Promise<void>) => {
    if (busy) return
    setBusy(key)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(tx((e as Error).message))
    } finally {
      setBusy(null)
    }
  }

  const rest = () => run('rest', async () => onAction(await api.rest(player.id, { days: 1, physio: false })))
  const week = () => run('week', async () => onWeek(await weekApi.live(player.id, weekPlan(player.life?.occupation ?? 'school'))))
  const session = () =>
    run('session', async () => {
      const preset = persisted('session.preset', 'farm')
      const hours = persisted('session.hours', 2)
      const stream = persisted('session.stream', false)
      onSession(await presetApi.auto(player.id, preset, hours, stream), { preset, hours, stream })
    })

  useHotkeys((key) => {
    const k = key.toLowerCase()
    if (Date.now() - pendingG.current < 1200 && TAB_KEYS[k]) {
      pendingG.current = 0
      onTab(TAB_KEYS[k])
      return
    }
    if (k === 'g') {
      pendingG.current = Date.now()
      return
    }
    if (key === '?') setHelp((h) => !h)
    else if (key === 'Escape') setHelp(false)
    else if (GROUP_KEYS[k]) onTab(GROUP_KEYS[k])
    else if (k === 'r') void rest()
    else if (k === 'w') void week()
    else if (k === 's') void session()
  })

  const button = (key: string, label: string, hotkey: string, fn: () => void) => (
    <button
      onClick={fn}
      disabled={busy !== null}
      title={t('Shortcut: {key}', { key: hotkey })}
      className="rounded-full bg-panel-light px-3 py-1 text-xs font-semibold hover:bg-osu-pink disabled:opacity-50"
    >
      {busy === key ? '…' : label}
    </button>
  )

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {button('rest', t('Rest 1 day'), 'R', () => void rest())}
      {button('week', t('Live a week'), 'W', () => void week())}
      {button('session', t('Auto session'), 'S', () => void session())}
      <button onClick={() => setHelp(true)} title={t('Keyboard shortcuts')} className="rounded-full px-2 text-xs text-muted hover:text-white">
        ⌨ ?
      </button>
      {error && <span className="w-full text-xs text-red-400">{error}</span>}
      {help && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setHelp(false)}>
          <div role="dialog" aria-label={t('Keyboard shortcuts')} className="w-full max-w-md space-y-2 rounded-xl bg-panel p-5 shadow-2xl ring-1 ring-panel-light" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-semibold">{t('Keyboard shortcuts')}</h3>
            <table className="w-full text-sm">
              <tbody>
                {HELP.map(([keys, what]) => (
                  <tr key={keys}>
                    <td className="py-1 pr-3 font-mono text-xs text-osu-pink">{keys}</td>
                    <td className="py-1">{t(what)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-muted">{t('Shortcuts are ignored while you type.')}</p>
          </div>
        </div>
      )}
    </div>
  )
}
