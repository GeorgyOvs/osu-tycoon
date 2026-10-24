import { useState } from 'react'
import { AudioProvider } from './audio'
import { MiniPlayer } from './components/MiniPlayer'
import { PlayerSelect } from './components/PlayerSelect'
import { Profile } from './components/Profile'

const STORAGE_KEY = 'tycoon.playerId'

export default function App() {
  const [playerId, setPlayerId] = useState<number | null>(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? Number(saved) : null
  })

  const select = (id: number | null) => {
    if (id == null) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, String(id))
    setPlayerId(id)
  }

  return (
    <AudioProvider>
      {playerId == null ? <PlayerSelect onSelect={select} /> : <Profile playerId={playerId} onExit={() => select(null)} />}
      <MiniPlayer />
    </AudioProvider>
  )
}
