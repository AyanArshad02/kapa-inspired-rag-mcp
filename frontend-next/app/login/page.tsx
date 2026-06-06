'use client'

import { type FormEvent, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/components/AuthContext'
import { guestLoginApi, loginApi } from '@/lib/api'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const { setAuth } = useAuth()
  const router = useRouter()

  async function handleGuest() {
    setError('')
    setBusy(true)
    try {
      const { access_token } = await guestLoginApi()
      setAuth(access_token)
      router.push('/dashboard')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Guest login failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const { access_token } = await loginApi(email, password)
      setAuth(access_token)
      router.push('/dashboard')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="text-3xl mb-2">🤖</div>
          <h1 className="text-2xl font-bold text-gray-900">Kapa RAG</h1>
          <p className="text-sm text-gray-500 mt-1">Sign in to your account</p>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Email
              </label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Password
              </label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>

            {error && (
              <p className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy}
              className="w-full bg-blue-600 text-white py-2 px-4 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          <div className="mt-4 relative">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-200" />
            </div>
            <div className="relative flex justify-center text-xs text-gray-400">
              <span className="bg-white px-2">or</span>
            </div>
          </div>

          <button
            type="button"
            onClick={handleGuest}
            disabled={busy}
            className="w-full mt-3 border border-gray-300 text-gray-700 py-2 px-4 rounded-lg text-sm font-medium hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Continue as Guest
          </button>

          <p className="text-center text-sm text-gray-500 mt-4">
            No account?{' '}
            <Link href="/signup" className="text-blue-600 hover:underline font-medium">
              Sign up free
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
