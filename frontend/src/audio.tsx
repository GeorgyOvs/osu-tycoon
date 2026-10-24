import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

export interface Track {
  beatmapsetId: number
  artist: string
  title: string
}

interface AudioState {
  track: Track | null
  playing: boolean
  progress: number // 0..1
  volume: number
  toggle: (track: Track) => void
  seek: (fraction: number) => void
  setVolume: (v: number) => void
  stop: () => void
}

const AudioContext = createContext<AudioState | null>(null)

const VOLUME_KEY = 'tycoon.volume'

/** One shared <audio> element for every preview on the page, driven by the mini player. */
export function AudioProvider({ children }: { children: ReactNode }) {
  const audio = useRef<HTMLAudioElement>(new Audio())
  const [track, setTrack] = useState<Track | null>(null)
  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0)
  const [volume, setVolumeState] = useState(() => Number(localStorage.getItem(VOLUME_KEY) ?? 0.4))

  useEffect(() => {
    const el = audio.current
    el.volume = volume
    const onTime = () => setProgress(el.duration ? el.currentTime / el.duration : 0)
    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    el.addEventListener('timeupdate', onTime)
    el.addEventListener('play', onPlay)
    el.addEventListener('pause', onPause)
    el.addEventListener('ended', onPause)
    return () => {
      el.removeEventListener('timeupdate', onTime)
      el.removeEventListener('play', onPlay)
      el.removeEventListener('pause', onPause)
      el.removeEventListener('ended', onPause)
      el.pause()
    }
    // Listeners only need registering once; volume changes go through setVolume.
  }, [])

  const toggle = (next: Track) => {
    const el = audio.current
    if (track?.beatmapsetId === next.beatmapsetId) {
      if (el.paused) void el.play()
      else el.pause()
      return
    }
    el.src = `https://b.ppy.sh/preview/${next.beatmapsetId}.mp3`
    setTrack(next)
    setProgress(0)
    void el.play()
  }

  const seek = (fraction: number) => {
    const el = audio.current
    if (el.duration) el.currentTime = fraction * el.duration
  }

  const setVolume = (v: number) => {
    audio.current.volume = v
    localStorage.setItem(VOLUME_KEY, String(v))
    setVolumeState(v)
  }

  const stop = () => {
    audio.current.pause()
    setTrack(null)
  }

  return (
    <AudioContext.Provider value={{ track, playing, progress, volume, toggle, seek, setVolume, stop }}>
      {children}
    </AudioContext.Provider>
  )
}

export function useAudio(): AudioState {
  const ctx = useContext(AudioContext)
  if (!ctx) throw new Error('useAudio must be used inside <AudioProvider>')
  return ctx
}
