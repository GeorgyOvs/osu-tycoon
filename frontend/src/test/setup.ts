// Component tests run in English (the i18n test switches to Russian itself).
localStorage.setItem('tycoon.lang', 'en')
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

/** Route fetch calls to handlers by "METHOD path" (query string ignored); records every call. */
export function mockApi(routes: Record<string, unknown | ((body: unknown) => unknown)>) {
  const calls: { method: string; path: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      const path = input.split('?')[0]
      const body = init?.body ? JSON.parse(init.body as string) : undefined
      calls.push({ method, path, body })
      const route = routes[`${method} ${path}`]
      if (route === undefined) return new Response(JSON.stringify({ detail: `no mock for ${method} ${path}` }), { status: 404 })
      const data = typeof route === 'function' ? (route as (b: unknown) => unknown)(body) : route
      return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }),
  )
  return calls
}
