import { useAudio } from '../audio'
import { t } from '../i18n'

export function MiniPlayer() {
  const { track, playing, progress, volume, toggle, seek, setVolume, stop } = useAudio()
  if (!track) return null

  return (
    <div className="fixed inset-x-0 bottom-0 z-50 border-t border-panel-light bg-panel/95 backdrop-blur">
      <div
        className="h-1 cursor-pointer bg-bg"
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect()
          seek((e.clientX - rect.left) / rect.width)
        }}
      >
        <div className="h-full bg-osu-pink" style={{ width: `${progress * 100}%` }} />
      </div>
      <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-2">
        <img
          src={`https://assets.ppy.sh/beatmaps/${track.beatmapsetId}/covers/list.jpg`}
          alt=""
          className="h-10 w-10 rounded object-cover"
        />
        <button
          onClick={() => toggle(track)}
          className="flex h-9 w-9 items-center justify-center rounded-full bg-osu-pink text-sm hover:bg-osu-pink-dark"
        >
          {playing ? '❚❚' : '▶'}
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">{track.title || `Beatmapset ${track.beatmapsetId}`}</div>
          <div className="truncate text-xs text-muted">{track.artist}</div>
        </div>
        <span className="text-xs text-muted">🔊</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={volume}
          onChange={(e) => setVolume(Number(e.target.value))}
          className="w-24 accent-osu-pink"
        />
        <button onClick={stop} title={t('Close')} className="text-muted hover:text-white">
          ✕
        </button>
      </div>
    </div>
  )
}
