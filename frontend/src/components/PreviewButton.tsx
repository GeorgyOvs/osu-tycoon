import { useAudio } from '../audio'
import { t } from '../i18n'

interface Props {
  beatmapsetId: number | null
  artist?: string
  title?: string
}

export function PreviewButton({ beatmapsetId, artist = '', title = '' }: Props) {
  const { track, playing, toggle } = useAudio()
  if (!beatmapsetId) return null

  const active = track?.beatmapsetId === beatmapsetId && playing
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        toggle({ beatmapsetId, artist, title })
      }}
      title={t('Preview')}
      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm ${
        active ? 'bg-osu-pink' : 'bg-panel-light hover:bg-osu-pink'
      }`}
    >
      {active ? '❚❚' : '▶'}
    </button>
  )
}
