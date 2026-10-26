import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, setUnauthorizedHandler, tokenStore } from '../api/client'
import { AuthPage } from '../pages/AuthPage'
import { validateAuth } from '../utils/validation'
import { mockApi, renderApp } from './utils'

afterEach(() => vi.unstubAllGlobals())

describe('validateAuth', () => {
  it('requires a valid email and password', () => {
    expect(validateAuth('login', 'nope', '', '')).toEqual({
      email: 'Enter a valid email address',
      password: 'Enter your password',
    })
  })
  it('enforces registration rules', () => {
    expect(validateAuth('register', 'a@b.co', 'short', 'short').password).toMatch(/10 characters/)
    expect(validateAuth('register', 'a@b.co', 'long-enough-pw', 'different').confirm).toMatch(/do not match/)
    expect(validateAuth('register', 'a@b.co', 'long-enough-pw', 'long-enough-pw')).toEqual({})
  })
})

describe('AuthPage', () => {
  it('shows validation errors without calling the API', async () => {
    const calls = mockApi({})
    renderApp(<AuthPage mode="register" />, { auth: true })
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('Enter a valid email address')).toBeInTheDocument()
    expect(screen.getByText('Use at least 10 characters')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true')
    expect(calls).toHaveLength(0)
  })

  it('shows the server error for bad credentials', async () => {
    mockApi({
      'POST /auth/login': {
        status: 401,
        body: { error: { code: 'unauthenticated', message: 'Invalid email or password' } },
      },
    })
    renderApp(<AuthPage mode="login" />, { auth: true })
    await userEvent.type(screen.getByLabelText('Email'), 'dev@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong-password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password')
    expect(tokenStore.get()).toBeNull()
  })

  it('stores the token and leaves the page after login', async () => {
    const calls = mockApi({
      'POST /auth/login': { body: { access_token: 'tok-123', token_type: 'bearer', expires_in: 3600 } },
      'GET /auth/me': { body: { id: 'u1', email: 'dev@example.com', created_at: '2026-01-01T00:00:00Z' } },
    })
    renderApp(<AuthPage mode="login" />, { auth: true, route: '/login', path: '/login' })
    await userEvent.type(screen.getByLabelText('Email'), 'dev@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'right-password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('navigated away')).toBeInTheDocument()
    expect(tokenStore.get()).toBe('tok-123')
    expect(calls[0].body).toEqual({ email: 'dev@example.com', password: 'right-password' })
  })
})

describe('api client', () => {
  it('sends the bearer token and reports 401 as an expired session', async () => {
    const calls = mockApi({
      'GET /endpoints': { status: 401, body: { error: { code: 'unauthenticated', message: 'Session expired' } } },
    })
    tokenStore.set('old-token')
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    await expect(api.get('/endpoints')).rejects.toMatchObject({ status: 401, message: 'Session expired' })
    expect(onUnauthorized).toHaveBeenCalledOnce()
    await waitFor(() => expect(calls).toHaveLength(1))
  })

  it('maps unreachable servers to a friendly error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(api.get('/endpoints')).rejects.toMatchObject({ code: 'network_error' })
  })
})
