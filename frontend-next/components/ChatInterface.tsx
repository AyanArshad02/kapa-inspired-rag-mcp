'use client'

import { type FormEvent, useEffect, useRef, useState } from 'react'
import { queryApi } from '@/lib/api'

interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: string[]
  cached?: boolean
}

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [convId, setConvId] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const q = input.trim()
    if (!q || loading) return

    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: q }])
    setLoading(true)

    try {
      const result = await queryApi(q, convId)
      setConvId(result.conversation_id)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: result.answer,
          sources: result.source_urls,
          cached: result.cached,
        },
      ])
    } catch (err: unknown) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: err instanceof Error ? err.message : 'Something went wrong. Please try again.',
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  function newChat() {
    setMessages([])
    setConvId(null)
  }

  return (
    <div className="h-full flex flex-col bg-gray-50">
      {/* Chat header */}
      <div className="px-6 py-3 border-b border-gray-200 bg-white flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700">Chat with your Docs</h2>
        {messages.length > 0 && (
          <button
            onClick={newChat}
            className="text-xs text-gray-500 hover:text-gray-700 border border-gray-200 px-3 py-1 rounded-lg hover:bg-gray-50 transition-colors"
          >
            New chat
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center pb-16">
            <div className="text-5xl mb-4">💬</div>
            <p className="text-gray-500 text-sm font-medium">Ask anything about your docs</p>
            <p className="text-gray-400 text-xs mt-1">Add a source from the left sidebar first</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-2xl rounded-2xl px-4 py-3 text-sm shadow-sm ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-white border border-gray-200 text-gray-800'
              }`}
            >
              <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>

              {msg.sources && msg.sources.length > 0 && (
                <details className="mt-2">
                  <summary
                    className={`text-xs cursor-pointer select-none ${
                      msg.role === 'user' ? 'text-blue-200' : 'text-gray-400'
                    }`}
                  >
                    📎 {msg.sources.length} source{msg.sources.length !== 1 ? 's' : ''}
                  </summary>
                  <ul className="mt-1 space-y-0.5 pl-1">
                    {msg.sources.map((s, j) => (
                      <li
                        key={j}
                        className={`text-xs truncate ${
                          msg.role === 'user' ? 'text-blue-200' : 'text-gray-500'
                        }`}
                        title={s}
                      >
                        {s}
                      </li>
                    ))}
                  </ul>
                </details>
              )}

              {msg.cached && (
                <p
                  className={`text-xs mt-1.5 ${
                    msg.role === 'user' ? 'text-blue-200' : 'text-gray-400'
                  }`}
                >
                  ⚡ Cached
                </p>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-white border border-gray-200 rounded-2xl px-4 py-3 shadow-sm">
              <div className="flex gap-1 items-center h-5">
                <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce [animation-delay:-0.3s]" />
                <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce [animation-delay:-0.15s]" />
                <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" />
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-6 py-4 bg-white border-t border-gray-200">
        <form onSubmit={handleSubmit} className="flex gap-3">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question about your docs…"
            disabled={loading}
            className="flex-1 px-4 py-2.5 border border-gray-300 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50 disabled:bg-gray-50"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="bg-blue-600 text-white px-5 py-2.5 rounded-xl text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  )
}
