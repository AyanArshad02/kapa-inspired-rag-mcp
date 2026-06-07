'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/components/AuthContext'
import AddSourcePanel from '@/components/AddSourcePanel'
import ChatInterface, { type ChatMessage } from '@/components/ChatInterface'
import SourceList from '@/components/SourceList'
import PreviousChats from '@/components/PreviousChats'
import { getConversationMessagesApi } from '@/lib/api'

type SidebarTab = 'chats' | 'sources'

export default function DashboardPage() {
  const { user, loading, logout } = useAuth()
  const router = useRouter()
  const [tab, setTab] = useState<SidebarTab>('chats')
  const [sourceRefreshKey, setSourceRefreshKey] = useState(0)
  const [chatRefreshKey, setChatRefreshKey] = useState(0)
  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])

  useEffect(() => {
    if (!loading && !user) router.replace('/login')
  }, [user, loading, router])

  async function handleSelectConversation(convId: string) {
    try {
      const msgs = await getConversationMessagesApi(convId)
      setMessages(msgs.map((m) => ({ role: m.role, content: m.content })))
      setActiveConvId(convId)
    } catch {
      // ignore
    }
  }

  function handleNewChat() {
    setMessages([])
    setActiveConvId(null)
  }

  function handleConversationChange(id: string) {
    setActiveConvId(id)
    setChatRefreshKey((k) => k + 1)
  }

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
          <span className="text-base font-semibold text-gray-900">Kapa RAG</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-500">{user.email}</span>
          {user.isAdmin && (
            <Link
              href="/admin"
              className="text-sm text-purple-600 hover:text-purple-800 border border-purple-200 px-3 py-1 rounded-lg hover:bg-purple-50 transition-colors font-medium"
            >
              Admin
            </Link>
          )}
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
        <aside className="w-64 bg-white border-r border-gray-200 flex flex-col shrink-0">
          {/* Tab switcher */}
          <div className="flex border-b border-gray-200 shrink-0">
            <button
              onClick={() => setTab('chats')}
              className={`flex-1 py-3 text-xs font-semibold tracking-wide transition-colors ${
                tab === 'chats'
                  ? 'text-blue-600 border-b-2 border-blue-600'
                  : 'text-gray-400 hover:text-gray-600'
              }`}
            >
              CHATS
            </button>
            <button
              onClick={() => setTab('sources')}
              className={`flex-1 py-3 text-xs font-semibold tracking-wide transition-colors ${
                tab === 'sources'
                  ? 'text-blue-600 border-b-2 border-blue-600'
                  : 'text-gray-400 hover:text-gray-600'
              }`}
            >
              SOURCES
            </button>
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-y-auto">
            {tab === 'chats' && (
              <div className="p-3 space-y-2">
                <button
                  onClick={handleNewChat}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 transition-colors"
                >
                  <span className="text-base leading-none">+</span>
                  New Chat
                </button>
                <PreviousChats
                  activeId={activeConvId}
                  onSelect={handleSelectConversation}
                  refreshKey={chatRefreshKey}
                />
              </div>
            )}

            {tab === 'sources' && (
              <div className="p-3 space-y-4">
                <AddSourcePanel onIngested={() => { setSourceRefreshKey((k) => k + 1); setTab('sources') }} />
                <SourceList refreshKey={sourceRefreshKey} />
              </div>
            )}
          </div>
        </aside>

        {/* Chat */}
        <main className="flex-1 overflow-hidden">
          <ChatInterface
            messages={messages}
            conversationId={activeConvId}
            onMessagesChange={setMessages}
            onConversationChange={handleConversationChange}
          />
        </main>
      </div>
    </div>
  )
}
