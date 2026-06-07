'use client'

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'
import { logoutApi, refreshApi, setAccessToken } from '@/lib/api'

interface User {
  email: string
  tenantId: string
  isAdmin: boolean
}

interface AuthContextValue {
  user: User | null
  loading: boolean
  setAuth: (token: string) => void
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function decodeUser(token: string): User | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return {
      email: payload.email,
      tenantId: payload.tenant_id,
      isAdmin: payload.is_admin === true,
    }
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  // On mount: try to silently restore session via the httpOnly refresh cookie.
  useEffect(() => {
    refreshApi().then((token) => {
      if (token) {
        setAccessToken(token)
        setUser(decodeUser(token))
      }
      setLoading(false)
    })
  }, [])

  const setAuth = useCallback((token: string) => {
    setAccessToken(token)
    setUser(decodeUser(token))
  }, [])

  const logout = useCallback(async () => {
    await logoutApi()
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, setAuth, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
