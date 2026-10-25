import { useEffect, useMemo, useRef, useState } from 'react'
import { socialApi, type ChannelSummary, type ChatLine } from '../api'
import { t, tx } from '../i18n'
import { openNpc } from '../npcBus'
import { GeneratedAvatar, PlayerAvatar } from './Avatar'

const POLL_MS = 3000
const NUDGE_MS = 40_000

function Thumb({ channel, size = 36 }: { channel: string; size?: number }) {
  if (channel.startsWith('DM:')) return <GeneratedAvatar seed={channel.slice(3)} size={size} />
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-full bg-panel-light text-xs font-bold text-osu-pink"
      style={{ width: size, height: size }}
    >
      #
    </div>
  )
}

const title = (c: string) => (c.startsWith('DM:') ? c.slice(3) : c)

function dayLabel(date: string) {
  return date
}

export function ChatPanel({
  playerId,
  playerName,
  summary,
  unread,
  markSeen,
  refresh,
  initialChannel,
}: {
  playerId: number
  playerName: string
  summary: ChannelSummary[]
  unread: Set<string>
  markSeen: (channel: string, id: number) => void
  refresh: () => Promise<unknown>
  initialChannel?: string | null
}) {
  const [channel, setChannel] = useState<string | null>(null)
  const [lines, setLines] = useState<ChatLine[]>([])
  const [draft, setDraft] = useState('')
  const [newTo, setNewTo] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [extra, setExtra] = useState<string[]>([])
  const lastId = useRef(0)
  const scroller = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!initialChannel) return
    setExtra((cur) => (cur.includes(initialChannel) ? cur : [initialChannel, ...cur]))
    setChannel(initialChannel)
  }, [initialChannel])

  const conversations = useMemo(() => {
    const known = new Set(summary.map((c) => c.channel))
    const added: ChannelSummary[] = extra
      .filter((c) => !known.has(c))
      .map((c) => ({ channel: c, last_id: 0, last_author: '', last_content: '', last_date: '', last_source: '', total: 0 }))
    return [...added, ...summary]
  }, [summary, extra])
  const channels = conversations.filter((c) => !c.channel.startsWith('DM:'))
  const dms = conversations.filter((c) => c.channel.startsWith('DM:'))

  useEffect(() => {
    if (channel === null && conversations.length) setChannel(conversations.find((c) => c.total > 0)?.channel ?? conversations[0].channel)
  }, [channel, conversations])

  useEffect(() => {
    if (!channel) return
    lastId.current = 0
    setLines([])
    setError(null)
    let cancelled = false
    const poll = async () => {
      const fresh = await socialApi.irc(playerId, channel, lastId.current).catch(() => [])
      if (cancelled || fresh.length === 0) return
      lastId.current = fresh[fresh.length - 1].id
      setLines((cur) => [...cur, ...fresh].slice(-300))
      markSeen(channel, lastId.current)
    }
    void poll()
    const timer = setInterval(poll, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [playerId, channel, markSeen])

  useEffect(() => {
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void socialApi.nudge(playerId).then((r) => r.new_lines && refresh()).catch(() => undefined)
    }, NUDGE_MS)
    return () => clearInterval(timer)
  }, [playerId, refresh])

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight })
  }, [lines, channel])

  const send = async () => {
    const text = draft.trim()
    if (!text || !channel) return
    setError(null)
    try {
      if (channel.startsWith('DM:')) await socialApi.dm(playerId, channel.slice(3), text)
      else await socialApi.say(playerId, channel, text)
      setDraft('')
      const fresh = await socialApi.irc(playerId, channel, lastId.current)
      if (fresh.length) {
        lastId.current = fresh[fresh.length - 1].id
        setLines((cur) => [...cur, ...fresh])
        markSeen(channel, lastId.current)
      }
      void refresh()
    } catch (e) {
      setError(tx((e as Error).message))
    }
  }

  const startDm = () => {
    const name = newTo.trim()
    if (!name) return
    const ch = `DM:${name}`
    setExtra((cur) => (cur.includes(ch) ? cur : [ch, ...cur]))
    setChannel(ch)
    setNewTo('')
  }

  const item = (c: ChannelSummary) => (
    <li key={c.channel}>
      <button
        onClick={() => setChannel(c.channel)}
        className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-panel-light ${channel === c.channel ? 'bg-panel-light' : ''}`}
      >
        <Thumb channel={c.channel} />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-2">
            <span className={`truncate text-sm ${unread.has(c.channel) ? 'font-bold' : 'font-medium'}`}>{title(c.channel)}</span>
            <span className="shrink-0 text-[10px] text-muted">{c.last_date ? c.last_date.slice(5) : ''}</span>
          </span>
          <span className="block truncate text-xs text-muted">
            {c.last_content ? `${c.last_source === 'user' ? t('You') + ': ' : ''}${c.last_content}` : '…'}
          </span>
        </span>
        {unread.has(c.channel) && <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-osu-pink" />}
      </button>
    </li>
  )

  return (
    <section className="grid h-[72vh] min-h-[28rem] overflow-hidden rounded-xl bg-panel md:grid-cols-[15rem_minmax(0,1fr)]">
      <aside className={`flex min-h-0 flex-col border-r border-panel-light ${channel && 'max-md:hidden'}`}>
        <form
          className="flex gap-1 border-b border-panel-light p-2"
          onSubmit={(e) => {
            e.preventDefault()
            startDm()
          }}
        >
          <input
            value={newTo}
            onChange={(e) => setNewTo(e.target.value)}
            placeholder={t('Write to a player…')}
            className="min-w-0 flex-1 rounded bg-bg px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-osu-pink"
          />
          <button className="rounded bg-panel-light px-2 text-sm hover:bg-osu-pink" title={t('New message')}>
            ✎
          </button>
        </form>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-2">
          <div>
            <h3 className="px-2 pb-1 text-[10px] uppercase tracking-wider text-muted">{t('Channels')}</h3>
            <ul className="space-y-0.5">{channels.map(item)}</ul>
          </div>
          <div>
            <h3 className="px-2 pb-1 text-[10px] uppercase tracking-wider text-muted">{t('Direct messages')}</h3>
            {dms.length === 0 && <p className="px-2 text-xs text-muted">{t('No private chats yet. Message someone from their profile in the World tab.')}</p>}
            <ul className="space-y-0.5">{dms.map(item)}</ul>
          </div>
        </div>
      </aside>

      <div className={`flex min-h-0 min-w-0 flex-col ${!channel && 'max-md:hidden'}`}>
        {channel ? (
          <>
            <header className="flex items-center gap-2 border-b border-panel-light px-3 py-2">
              <button onClick={() => setChannel(null)} className="text-muted hover:text-white md:hidden">
                ←
              </button>
              <Thumb channel={channel} size={32} />
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold">{title(channel)}</div>
                <div className="truncate text-[11px] text-muted">
                  {channel.startsWith('DM:') ? t('Replies are written by your SillyTavern model when the bridge is on.') : t('Public channel')}
                </div>
              </div>
            </header>
            <div ref={scroller} className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 py-3">
              {lines.length === 0 && <p className="text-center text-xs text-muted">{t('Nothing here yet.')}</p>}
              {lines.map((l, i) => {
                const mine = l.source === 'user' || l.author === playerName
                const newDay = i === 0 || lines[i - 1].date !== l.date
                return (
                  <div key={l.id}>
                    {newDay && <div className="py-1 text-center text-[10px] uppercase tracking-wider text-muted">{dayLabel(l.date)}</div>}
                    <div className={`flex items-end gap-2 ${mine ? 'flex-row-reverse' : ''}`}>
                      {mine ? <PlayerAvatar playerId={playerId} name={playerName} size={24} /> : <GeneratedAvatar seed={l.author} size={24} />}
                      <div className={`max-w-[75%] rounded-2xl px-3 py-1.5 text-sm break-words ${mine ? 'rounded-br-sm bg-osu-pink/80' : 'rounded-bl-sm bg-panel-light'}`}>
                        {!mine && (
                          <div className={`text-[11px] font-semibold ${l.source === 'llm' ? 'text-sky-300' : 'text-osu-pink'}`}>
                            <button type="button" onClick={() => openNpc({ name: l.author })} className="hover:underline">
                              {l.author}
                            </button>
                            {l.source === 'llm' && <span title={t('Written by the LLM via SillyTavern')}> ✦</span>}
                          </div>
                        )}
                        {l.content}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
            <form
              className="flex gap-2 border-t border-panel-light p-2"
              onSubmit={(e) => {
                e.preventDefault()
                void send()
              }}
            >
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                maxLength={channel.startsWith('DM:') ? 500 : 300}
                placeholder={error ?? t('Message {name}…', { name: title(channel) })}
                className={`min-w-0 flex-1 rounded-full bg-bg px-4 py-2 text-sm outline-none focus:ring-1 focus:ring-osu-pink ${error ? 'placeholder:text-red-400' : ''}`}
              />
              <button disabled={!draft.trim()} className="rounded-full bg-osu-pink px-4 text-sm font-semibold disabled:opacity-40">
                {t('Send')}
              </button>
            </form>
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center text-sm text-muted">{t('Choose a conversation')}</div>
        )}
      </div>
    </section>
  )
}
