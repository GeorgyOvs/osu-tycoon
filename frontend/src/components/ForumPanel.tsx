import { useEffect, useState } from 'react'
import { socialApi, type ForumComment, type Thread, type ThreadSummary } from '../api'
import { t } from '../i18n'
import { MapLeaderboard } from './MapLeaderboard'

const KINDS: [string, string][] = [
  ['', t('All')],
  ['scorepost', t('Scoreposts')],
  ['tournament', t('Tournaments')],
  ['discussion', t('Discussions')],
  ['news', t('News')],
  ['drama', t('Drama')],
  ['milestone', t('Milestones')],
  ['rework', t('Reworks')],
  ['snipe', t('Snipes')],
]

const FLAIR_COLORS: Record<string, string> = {
  Gameplay: 'bg-osu-pink/30 text-osu-pink',
  Tournament: 'bg-amber-500/20 text-amber-300',
  News: 'bg-sky-500/20 text-sky-300',
  Discussion: 'bg-purple-500/20 text-purple-300',
  Milestone: 'bg-green-500/20 text-green-300',
}

function compact(n: number) {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
}

function CommentTree({ comments, parent, depth }: { comments: ForumComment[]; parent: number | null; depth: number }) {
  const children = comments.filter((c) => c.parent_id === parent)
  if (children.length === 0) return null
  return (
    <ul className={depth ? 'ml-4 border-l border-panel-light pl-3' : ''}>
      {children
        .sort((a, b) => b.upvotes - a.upvotes)
        .map((c) => (
          <li key={c.id} className="py-1.5">
            <div className="text-xs text-muted">
              <span className="font-semibold text-white/80">{c.author}</span> · {compact(c.upvotes)} {t('points')}
              {c.source === 'llm' && <span title={t('Written by the LLM via SillyTavern')}> · ✦</span>}
            </div>
            <div className="text-sm">{c.content}</div>
            <CommentTree comments={comments} parent={c.id} depth={depth + 1} />
          </li>
        ))}
    </ul>
  )
}

export function ForumPanel({ playerId, dateKey }: { playerId: number; dateKey: string }) {
  const [kind, setKind] = useState('')
  const [threads, setThreads] = useState<ThreadSummary[]>([])
  const [open, setOpen] = useState<Thread | null>(null)

  useEffect(() => {
    socialApi.forum(playerId, kind || undefined).then(setThreads)
  }, [playerId, kind, dateKey])

  // While an LLM reply is pending, keep checking so comments appear as SillyTavern writes them.
  const pending = open?.llm_status === 'pending'
  useEffect(() => {
    if (!open || !pending) return
    const timer = setInterval(() => socialApi.thread(playerId, open.id).then(setOpen), 5000)
    return () => clearInterval(timer)
  }, [playerId, open, pending])

  const board = threads[0]?.board ?? 'r/osugame'

  return (
    <section className="space-y-3 rounded-xl bg-panel p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-semibold">{board}</h2>
        <div className="flex gap-1">
          {KINDS.map(([k, label]) => (
            <button
              key={k}
              onClick={() => setKind(k)}
              className={`rounded-full px-2.5 py-0.5 text-xs ${kind === k ? 'bg-osu-pink' : 'bg-panel-light text-muted hover:text-white'}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {threads.length === 0 && (
        <p className="text-sm text-muted">{t('Quiet so far. Set a new top play or make some noise in a tournament.')}</p>
      )}

      <ul className="space-y-1">
        {threads.map((th) => (
          <li key={th.id}>
            <button
              onClick={() => (open?.id === th.id ? setOpen(null) : socialApi.thread(playerId, th.id).then(setOpen))}
              className={`flex w-full gap-3 rounded-lg px-3 py-2 text-left ${open?.id === th.id ? 'bg-panel-light' : 'bg-bg hover:bg-panel-light/60'}`}
            >
              <div className="w-10 shrink-0 text-center text-xs">
                <div className="text-osu-pink">▲</div>
                <div className="font-bold">{compact(th.upvotes)}</div>
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm">
                  {th.flair && (
                    <span className={`mr-1.5 rounded px-1.5 py-0.5 text-[10px] ${FLAIR_COLORS[th.flair] ?? 'bg-panel-light'}`}>
                      {th.flair}
                    </span>
                  )}
                  {th.title}
                </div>
                <div className="text-xs text-muted">
                  {th.date} · u/{th.author} · {t('{n} comments', { n: th.comment_count })}
                  {th.llm_status === 'pending' && ` · ${t('waiting for the community…')}`}
                </div>
              </div>
            </button>
            {open?.id === th.id && (
              <div className="mt-1 rounded-lg bg-bg px-4 py-3">
                {open.body && <p className="mb-2 whitespace-pre-line text-sm">{open.body}</p>}
                {open.flair !== 'Correction' && open.body?.match(/https:\/\/osu\.ppy\.sh\/beatmaps\/(\d+)/) && (
                  <MapLeaderboard playerId={playerId}
                    beatmapId={Number(open.body.match(/https:\/\/osu\.ppy\.sh\/beatmaps\/(\d+)/)![1])} dateKey={dateKey} />
                )}
                <CommentTree comments={open.comments} parent={null} depth={0} />
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
