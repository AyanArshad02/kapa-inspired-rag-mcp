'use client'

import { type FormEvent, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import { formatSourceUrl, queryApi } from '@/lib/api'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: string[]
  cached?: boolean
}

interface Props {
  messages: ChatMessage[]
  conversationId: string | null
  onMessagesChange: (msgs: ChatMessage[]) => void
  onConversationChange: (id: string) => void
}

export default function ChatInterface({
  messages,
  conversationId,
  onMessagesChange,
  onConversationChange,
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const form = e.currentTarget as HTMLFormElement
    const input = (form.elements.namedItem('q') as HTMLInputElement)
    const q = input.value.trim()
    if (!q) return
    input.value = ''

    const optimistic: ChatMessage[] = [...messages, { role: 'user', content: q }]
    onMessagesChange([...optimistic, { role: 'assistant', content: '__loading__' }])

    try {
      const result = await queryApi(q, conversationId)
      onConversationChange(result.conversation_id)
      onMessagesChange([
        ...optimistic,
        {
          role: 'assistant',
          content: result.answer,
          sources: result.source_urls,
          cached: result.cached,
        },
      ])
    } catch (err: unknown) {
      onMessagesChange([
        ...optimistic,
        {
          role: 'assistant',
          content: err instanceof Error ? err.message : 'Something went wrong. Please try again.',
        },
      ])
    }
  }

  const isLoading = messages.at(-1)?.content === '__loading__'

  return (
    <div className="h-full flex flex-col bg-gray-50">
      {/* Chat header */}
      <div className="px-6 py-3 border-b border-gray-200 bg-white flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700">Chat with your Docs</h2>
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

        {messages.map((msg, i) => {
          if (msg.content === '__loading__') {
            return (
              <div key={i} className="flex justify-start">
                <div className="bg-white border border-gray-200 rounded-2xl px-4 py-3 shadow-sm">
                  <div className="flex gap-1 items-center h-5">
                    <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce [animation-delay:-0.3s]" />
                    <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce [animation-delay:-0.15s]" />
                    <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" />
                  </div>
                </div>
              </div>
            )
          }

          return (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-2xl rounded-2xl px-4 py-3 text-sm shadow-sm ${
                  msg.role === 'user'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white border border-gray-200 text-gray-800'
                }`}
              >
                {msg.role === 'user' ? (
                  <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                ) : (
                  <div className="prose prose-sm max-w-none prose-p:my-1 prose-pre:bg-gray-100 prose-pre:text-gray-800 prose-code:text-blue-700 prose-code:bg-blue-50 prose-code:px-1 prose-code:rounded prose-strong:text-gray-900 prose-li:my-0">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  </div>
                )}

                {msg.sources && msg.sources.length > 0 && (
                  <details className="mt-2">
                    <summary className="text-xs cursor-pointer select-none text-gray-400">
                      📎 {msg.sources.length} source{msg.sources.length !== 1 ? 's' : ''}
                    </summary>
                    <ul className="mt-1 space-y-0.5 pl-1">
                      {msg.sources.map((s, j) => (
                        <li key={j} className="text-xs truncate text-gray-500" title={s}>
                          {formatSourceUrl(s)}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}

                {msg.cached && (
                  <p className="text-xs mt-1.5 text-gray-400">⚡ Cached</p>
                )}
              </div>
            </div>
          )
        })}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-6 py-4 bg-white border-t border-gray-200">
        <form onSubmit={handleSubmit} className="flex gap-3">
          <input
            name="q"
            placeholder="Ask a question about your docs…"
            disabled={isLoading}
            className="flex-1 px-4 py-2.5 border border-gray-300 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50 disabled:bg-gray-50"
          />
          <button
            type="submit"
            disabled={isLoading}
            className="bg-blue-600 text-white px-5 py-2.5 rounded-xl text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  )
}
