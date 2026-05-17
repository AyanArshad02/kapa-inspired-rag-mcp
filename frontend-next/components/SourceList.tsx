'use client'

import { useCallback, useEffect, useState } from 'react'
import { deleteSourceApi, listSourcesApi, type Source } from '@/lib/api'

function sourceIcon(type: string) {
  if (type === 'pdf') return '📄'
  if (type === 'github') return '🐙'
  return '🌐'
}

export default function SourceList({ refreshKey }: { refreshKey: number }) {
  const [sources, setSources] = useState<Source[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setSources(await listSourcesApi())
    } catch {
      // silently ignore — user sees empty state
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load, refreshKey])

  async function handleDelete(url: string) {
    try {
      await deleteSourceApi(url)
      setSources((prev) => prev.filter((s) => s.source_url !== url))
    } catch {
      alert('Delete failed')
    }
  }

  if (loading) {
    return <p className="text-xs text-gray-400 py-2">Loading…</p>
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Indexed Sources
        </h2>
        <button
          onClick={load}
          className="text-xs text-gray-400 hover:text-gray-600"
          title="Refresh"
        >
          ↻
        </button>
      </div>

      {sources.length === 0 ? (
        <p className="text-xs text-gray-400 py-2">No sources indexed yet.</p>
      ) : (
        <ul className="space-y-1">
          {sources.map((src) => {
            const name = src.source_url.split('/').filter(Boolean).pop() ?? src.source_url
            const short = name.length > 28 ? name.slice(0, 28) + '…' : name
            return (
              <li
                key={src.source_url}
                className="flex items-center justify-between group py-0.5"
              >
                <span className="text-xs text-gray-600 truncate" title={src.source_url}>
                  {sourceIcon(src.source_type)} {short}
                </span>
                <button
                  onClick={() => handleDelete(src.source_url)}
                  className="text-gray-300 hover:text-red-400 text-xs ml-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                  title="Delete source"
                >
                  ✕
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
