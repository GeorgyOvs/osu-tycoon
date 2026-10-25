import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MapHint } from '../components/MapHint'

const hint = {
  beatmap_id: 7,
  mods: 'HR',
  stars: 5.4,
  bpm: 200,
  length: 95,
  main_skills: [{ key: 'aim', label: 'jumps', detail: 'jumps at 200 BPM' }],
  dims: [
    { key: 'aim', label: 'Aim', need_comfort: [60, 64], need_pass: [48, 52], yours: 55, verdict: 'passable', verdict_label: 'passable' },
  ],
  notes: ['HR makes this AR10.3'],
  precision: 'sharp',
  precision_label: 'sharp',
  experience: 0.8,
}

describe('MapHint', () => {
  afterEach(() => vi.restoreAllMocks())

  it('shows the skill card after a short hover, lazily', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(hint), { status: 200 }))
    render(
      <MapHint playerId={1} beatmapId={7} mods="HR1">
        <span>Some Map</span>
      </MapHint>,
    )
    expect(fetchMock).not.toHaveBeenCalled()
    fireEvent.mouseEnter(screen.getByText('Some Map').parentElement as HTMLElement)
    await act(async () => {
      vi.advanceTimersByTime(300)
    })
    vi.useRealTimers()
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(String(fetchMock.mock.calls[0][0])).toContain('/maps/7/hint?mods=HR1')
    expect(await screen.findByText(/jumps at 200 BPM/)).toBeInTheDocument()
    expect(screen.getByText(/HR makes this AR10.3/)).toBeInTheDocument()
  })
})
