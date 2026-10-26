import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'

type Handler = (url: URL, init: RequestInit) => { status?: number; body?: unknown } | undefined

/** Replace fetch with a router of `"METHOD /path"` handlers; records every call. */
export function mockApi(routes: Record<string, Handler | { status?: number; body?: unknown }>) {
  const calls: { method: string; url: URL; body: unknown }[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), 'http://localhost')
    const method = init.method ?? 'GET'
    const body = init.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ method, url, body })
    const key = `${method} ${url.pathname.replace('/api/v1', '')}`
    const route = routes[key]
    const result = typeof route === 'function' ? route(url, init) : route
    if (!result)
      return new Response(JSON.stringify({ error: { code: 'not_found', message: `No mock for ${key}` } }), {
        status: 404,
      })
    return new Response(result.status === 204 ? null : JSON.stringify(result.body ?? {}), {
      status: result.status ?? 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

export function renderApp(
  ui: ReactElement,
  { route = '/', path = '*', auth = false }: { route?: string; path?: string; auth?: boolean } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const routed = (
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path={path} element={ui} />
        <Route path="*" element={<div>navigated away</div>} />
      </Routes>
    </MemoryRouter>
  )
  return render(
    <QueryClientProvider client={client}>{auth ? <AuthProvider>{routed}</AuthProvider> : routed}</QueryClientProvider>,
  )
}
