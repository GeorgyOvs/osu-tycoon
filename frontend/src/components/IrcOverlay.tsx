import { useEffect, useRef, useState } from 'react'
import { socialApi, type ChatLine } from '../api'
import { t, tx } from '../i18n'

const POLL_MS = 4000

/** Floating osu!-style chat window; polls so lines written by SillyTavern show up live. */
export function IrcOverlay({ playerId }: { playerId: number }) {
  const [open, setOpen] = useState(false)
  const [channels, setChannels] = useState<string[]>(['#osu'])
  const [channel, setChannel] = useState('#osu')
  const [lines, setLines] = useState<ChatLine[]>([])
  const [unread, setUnread] = useState(0)
  const [draft, setDraft] = useState('')
  const [sendError, setSendError] = useState<string | null>(null)
  const lastId = useRef(0)
  const openRef = useRef(open)
  openRef.current = open
  const scroller = useRef<HTMLDivElement>(null)
  const tabs = useRef<HTMLDivElement>(null)

  useEffect(() => {
    socialApi.channels(playerId).then(setChannels)
  }, [playerId, open])

  useEffect(() => {
    lastId.current = 0
    setLines([])
    let cancelled = false
    const poll = async () => {
      const fresh = await socialApi.irc(playerId, channel, lastId.current).catch(() => [])
      if (cancelled || fresh.length === 0) return
      const firstLoad = lastId.current === 0
      lastId.current = fresh[fresh.length - 1].id
      setLines((cur) => [...cur, ...fresh].slice(-200))
      if (!openRef.current && !firstLoad) setUnread((n) => n + fresh.length)
    }
    void poll()
    const timer = setInterval(poll, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [playerId, channel])

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight })
  }, [lines, open])

  if (!open) {
    return (
      <button
        onClick={() => {
          setOpen(true)
          setUnread(0)
        }}
        className="fixed right-4 bottom-20 z-40 rounded-full bg-panel px-4 py-2 text-sm shadow-lg ring-1 ring-panel-light hover:bg-panel-light"
      >
        💬 IRC{unread > 0 && <span className="ml-1.5 rounded-full bg-osu-pink px-1.5 text-xs">{unread}</span>}
      </button>
    )
  }

  return (
    <div className="fixed right-4 bottom-20 z-40 flex h-80 w-96 flex-col rounded-xl bg-panel/95 shadow-2xl ring-1 ring-panel-light backdrop-blur">
      <div className="flex items-center gap-1 border-b border-panel-light px-2 py-1.5">
        <div
          ref={tabs}
          onWheel={(e) => {
            if (tabs.current && e.deltaY) tabs.current.scrollLeft += e.deltaY
          }}
          className="flex min-w-0 flex-1 gap-1 overflow-x-auto whitespace-nowrap [scrollbar-width:thin]"
        >
          {channels.map((c) => (
            <button
              key={c}
              onClick={() => setChannel(c)}
              title={c}
              className={`max-w-32 shrink-0 truncate rounded px-2 py-0.5 text-xs ${c === channel ? 'bg-osu-pink' : 'text-muted hover:text-white'}`}
            >
              {c.startsWith('DM:') ? `✉ ${c.slice(3)}` : c}
            </button>
          ))}
        </div>
        {channels.length > 5 && (
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
            title={t('All channels')}
            className="w-6 shrink-0 cursor-pointer appearance-none rounded bg-bg text-center text-xs text-muted"
          >
            {channels.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        )}
        <button onClick={() => setOpen(false)} className="shrink-0 px-1 text-muted hover:text-white">
          ▾
        </button>
      </div>
      {channel.startsWith('DM:') && (
        <div className="border-b border-panel-light px-3 py-1 text-[10px] text-muted">
          {t('Replies are written by your SillyTavern model when the bridge is on.')}
        </div>
      )}
      <div ref={scroller} className="flex-1 space-y-0.5 overflow-y-auto break-words px-3 py-2 font-mono text-xs">
        {lines.length === 0 && <p className="text-muted">* {t('Now talking in')} {channel}</p>}
        {lines.map((l) => (
          <div key={l.id}>
            <span className="text-muted">[{l.date.slice(5)}]</span>{' '}
            <span className={l.source === 'llm' ? 'text-sky-300' : l.source === 'user' ? 'text-green-300' : 'text-osu-pink'}>
              {l.author}
            </span>
            : {l.content}
          </div>
        ))}
      </div>
      {channel.startsWith('DM:') && (
        <form
          className="flex gap-1 border-t border-panel-light p-2"
          onSubmit={async (e) => {
            e.preventDefault()
            if (!draft.trim()) return
            setSendError(null)
            try {
              await socialApi.dm(playerId, channel.slice(3), draft.trim())
              setDraft('')
            } catch (err) {
              setSendError(tx((err as Error).message))
            }
          }}
        >
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            maxLength={500}
            placeholder={sendError ?? t('Message {name}…', { name: channel.slice(3) })}
            className="flex-1 rounded bg-bg px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-osu-pink"
          />
        </form>
      )}
    </div>
  )
}
