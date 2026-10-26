import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, setUnauthorizedHandler, tokenStore } from '../api/client'
import type { TokenResponse, User } from '../api/types'

interface AuthState {
  user: User | null
  isLoading: boolean
  sessionExpired: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [token, setToken] = useState<string | null>(() => tokenStore.get())
  const [sessionExpired, setSessionExpired] = useState(false)

  const me = useQuery({
    queryKey: ['me', token],
    queryFn: () => api.get<User>('/auth/me'),
    enabled: token !== null,
    retry: false,
    staleTime: Infinity,
  })

  const signOut = useCallback(
    (expired: boolean) => {
      tokenStore.clear()
      setToken(null)
      setSessionExpired(expired)
      qc.clear()
    },
    [qc],
  )

  // Any 401 from the API (expired or revoked token) ends the session consistently.
  useEffect(() => {
    setUnauthorizedHandler(() => signOut(true))
  }, [signOut])

  const accept = useCallback((res: TokenResponse) => {
    tokenStore.set(res.access_token)
    setSessionExpired(false)
    setToken(res.access_token)
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user: token ? (me.data ?? null) : null,
      isLoading: token !== null && me.isPending,
      sessionExpired,
      login: async (email, password) => accept(await api.post<TokenResponse>('/auth/login', { email, password })),
      register: async (email, password) => accept(await api.post<TokenResponse>('/auth/register', { email, password })),
      logout: () => signOut(false),
    }),
    [token, me.data, me.isPending, sessionExpired, accept, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// oxlint-disable-next-line react/only-export-components -- hook lives next to its provider
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
