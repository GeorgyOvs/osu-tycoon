import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CommentaryLine, MatchCommentary, MatchMap, Replay } from '../api'
import { LiveMatch, ReplayViewer, WatchReplay } from '../components/ReplayViewer'

const replay: Replay = {
  duration: 20,
  end: 20,
  max_combo: 100,
  objects: 100,
  t: [0, 5, 10, 15],
  combo: [10, 40, 0, 20],
  hp: [1, 0.9, 0.4, 0.7],
  misses: [0, 0, 2, 2],
  acc: [100, 100, 96, 97],
  strain: [0.2, 0.6, 1, 0.5],
  kind: ['calm', 'stream', 'jump', 'calm'],
  moments: [{ t: 5, type: 'stream', text: '200 BPM stream, 16 notes' }],
}
const lines: CommentaryLine[] = [
  { t: 0, text: 'Opening line', tone: 'neutral', who: 'Kirin' },
  { t: 10, text: 'Ouch, misses', tone: 'sad', who: 'Lumi' },
]

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('ReplayViewer', () => {
  it('reveals commentary and stats as the clock runs, then shows the summary', () => {
    const onEnded = vi.fn()
    render(
      <ReplayViewer replay={replay} commentary={lines} startSpeed={1} onEnded={onEnded}
        summary={{ passed: true, grade: 'A', accuracy: 97, misses: 2, combo: 40, maxCombo: 100 }} />,
    )
    expect(screen.getByText(/Opening line/)).toBeInTheDocument()
    expect(screen.queryByText(/Ouch, misses/)).toBeNull()
    expect(screen.getByText('10x')).toBeInTheDocument()

    act(() => void vi.advanceTimersByTime(10_500))
    expect(screen.getByText(/Ouch, misses/)).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument() // misses so far
    expect(screen.queryByTestId('replay-summary')).toBeNull()

    act(() => void vi.advanceTimersByTime(10_000))
    expect(screen.getByTestId('replay-summary')).toHaveTextContent('A')
    expect(onEnded).toHaveBeenCalledTimes(1)
  })

  it('pauses and scrubs', () => {
    render(<ReplayViewer replay={replay} commentary={lines} startSpeed={1} />)
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    act(() => void vi.advanceTimersByTime(5000))
    expect(screen.getByText('0:00 / 0:20')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Replay position'), { target: { value: '120' } })
    expect(screen.getByText(/Ouch, misses/)).toBeInTheDocument()
    expect(screen.getByText('0:12 / 0:20')).toBeInTheDocument()
  })

  it('WatchReplay renders nothing without replay data and toggles otherwise', () => {
    const { container, rerender } = render(<WatchReplay />)
    expect(container).toBeEmptyDOMElement()
    rerender(<WatchReplay replay={replay} />)
    fireEvent.click(screen.getByText('Watch replay'))
    expect(screen.getByRole('img', { name: 'Replay chart' })).toBeInTheDocument()
    fireEvent.click(screen.getByText('Hide replay'))
    expect(screen.queryByRole('img')).toBeNull()
  })
})

describe('LiveMatch', () => {
  const player = (side: 'a' | 'b', kind: string, name: string) => ({
    side, name, kind, score: 1, accuracy: 97, misses: 2, combo: 40, max_combo: 100, choked: false, key_moments: [],
    passed: true, grade: 'A', replay,
  })
  const map = (slot: string, a: number, b: number): MatchMap => ({
    slot, picked_by: 'a', score_a: a, score_b: b, title: `Song ${slot}`, stars: 5,
    players: [player('a', 'user', 'You'), player('b', 'npc', 'Mioto')],
  })
  const maps: MatchMap[] = [map('NM1', 900, 800), map('NM2', 700, 800), { bans: { a: ['DT1'], b: ['HR1'] } }]
  const cast: MatchCommentary = {
    pre: [{ t: 0, text: 'Welcome everyone', tone: 'neutral', who: 'Kirin' }],
    maps: [lines, lines],
    between: [[{ t: 0, text: 'Score: You 1 - 0 Mioto.', tone: 'neutral', who: 'Lumi' }], []],
    post: [{ t: 0, text: 'You wins 2-0! GG to both.', tone: 'hype', who: 'Kirin' }],
  }

  it('steps map by map with a running score and can skip to the result', () => {
    render(<LiveMatch maps={maps} commentary={cast} names={['You', 'Mioto']} onClose={() => {}} />)
    expect(screen.getByText('Welcome everyone', { exact: false })).toBeInTheDocument()
    expect(screen.getByText(/You 0 – 0 Mioto/)).toBeInTheDocument()
    expect(screen.getByText('Song NM1')).toBeInTheDocument()

    act(() => void vi.advanceTimersByTime(30_000)) // map 1 finishes at 4x
    expect(screen.getByText(/You 1 – 0 Mioto/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('Next map'))
    expect(screen.getByText('Song NM2')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Skip to result'))
    expect(screen.getByText(/You 1 – 1 Mioto/)).toBeInTheDocument()
    expect(screen.getByText(/GG to both/)).toBeInTheDocument()
  })
})
