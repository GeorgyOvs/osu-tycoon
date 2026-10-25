import { useEffect, useState } from 'react'

/** useState that survives tab switches and reloads (localStorage, per key). */
export function usePersisted<T>(key: string, initial: T) {
  const full = `tycoon.ui.${key}`
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(full)
      return raw === null ? initial : (JSON.parse(raw) as T)
    } catch {
      return initial
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem(full, JSON.stringify(value))
    } catch {
      /* storage unavailable: keep in memory only */
    }
  }, [full, value])
  return [value, setValue] as const
}
