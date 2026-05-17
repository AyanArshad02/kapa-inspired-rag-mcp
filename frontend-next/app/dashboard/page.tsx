'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/components/AuthContext'
import AddSourcePanel from '@/components/AddSourcePanel'
import ChatInterface from '@/components/ChatInterface'
import SourceList from '@/components/SourceList'

export default function DashboardPage() {
  const { user, loading, logout } = useAuth()
  const router = useRouter()
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    if (!loading && !user) router.replace('/login')
  }, [user, loading, router])

  if (loading || !user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-5 py-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xl">🤖</span>
          <span className="text-base font-semibold text-gray-900">Kapa RAG</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-500">{user.email}</span>
          <button
            onClick={() => logout().then(() => router.push('/login'))}
            className="text-sm text-gray-500 hover:text-gray-700 border border-gray-200 px-3 py-1 rounded-lg hover:bg-gray-50 transition-colors"
          >
            Sign out
          </button>
        </div>
      </header>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside className="w-72 bg-white border-r border-gray-200 flex flex-col overflow-hidden shrink-0">
          <div className="p-4 border-b border-gray-100 overflow-y-auto">
            <AddSourcePanel onIngested={() => setRefreshKey((k) => k + 1)} />
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            <SourceList refreshKey={refreshKey} />
          </div>
        </aside>

        {/* Chat */}
        <main className="flex-1 overflow-hidden">
          <ChatInterface />
        </main>
      </div>
    </div>
  )
}
