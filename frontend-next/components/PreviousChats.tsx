'use client'

import { useCallback, useEffect, useState } from 'react'
import { listConversationsApi, type ConversationSummary } from '@/lib/api'

interface Props {
  activeId: string | null
  onSelect: (id: string) => void
  refreshKey: number
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export default function PreviousChats({ activeId, onSelect, refreshKey }: Props) {
  const [chats, setChats] = useState<ConversationSummary[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      setChats(await listConversationsApi())
    } catch {
      // silently ignore
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load, refreshKey])

  if (loading) return <p className="text-xs text-gray-400 py-1">Loading…</p>
  if (chats.length === 0) return null

  return (
    <div>
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Previous Chats
      </h2>
      <ul className="space-y-0.5">
        {chats.map((c) => {
          const isActive = c.conversation_id === activeId
          const preview = c.preview.length > 38 ? c.preview.slice(0, 38) + '…' : c.preview
          return (
            <li key={c.conversation_id}>
              <button
                onClick={() => onSelect(c.conversation_id)}
                className={`w-full text-left px-2 py-1.5 rounded-lg transition-colors group ${
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                <p className="text-xs truncate font-medium">{preview || 'Untitled chat'}</p>
                <p className={`text-xs mt-0.5 ${isActive ? 'text-blue-400' : 'text-gray-400'}`}>
                  {timeAgo(c.last_active)} · {Math.floor(c.message_count / 2)} msg{Math.floor(c.message_count / 2) !== 1 ? 's' : ''}
                </p>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
