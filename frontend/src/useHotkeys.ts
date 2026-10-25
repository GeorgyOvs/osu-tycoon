import { useEffect, useRef } from 'react'

function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

/** Single-key shortcuts. Ignored while typing and when Ctrl/Cmd/Alt is held (Ctrl+K belongs to search). */
export function useHotkeys(onKey: (key: string, event: KeyboardEvent) => void) {
  const handler = useRef(onKey)
  useEffect(() => {
    handler.current = onKey
  })
  useEffect(() => {
    const listener = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) return
      if (document.querySelector('[role="dialog"]') && e.key !== 'Escape') return
      handler.current(e.key, e)
    }
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [])
}
