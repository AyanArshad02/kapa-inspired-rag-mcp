'use client'

import { useEffect, useState } from 'react'
import { getUsageApi, type UsageStats } from '@/lib/api'

type Period = 7 | 30

function StatRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-gray-100 last:border-0">
      <span className="text-sm text-gray-500">{label}</span>
      <span className="text-sm font-semibold text-gray-900 tabular-nums">{value}</span>
    </div>
  )
}

function fmt(n: number): string {
  return n.toLocaleString()
}

export default function UsagePanel() {
  const [period, setPeriod] = useState<Period>(30)
  const [stats, setStats] = useState<UsageStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    getUsageApi(period)
      .then(setStats)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [period])

  return (
    <div className="p-3 space-y-3">
      {/* Period toggle */}
      <div className="flex gap-1 bg-gray-100 p-0.5 rounded-lg">
        {([7, 30] as Period[]).map((d) => (
          <button
            key={d}
            onClick={() => setPeriod(d)}
            className={`flex-1 py-1.5 text-xs font-semibold rounded-md transition-colors ${
              period === d
                ? 'bg-white text-blue-600 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {d} days
          </button>
        ))}
      </div>

      {/* Content */}
      {loading && (
        <div className="flex justify-center py-8">
          <div className="w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {error && (
        <p className="text-xs text-red-500 text-center py-4">{error}</p>
      )}

      {stats && !loading && (
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-1 shadow-sm">
          <StatRow label="Queries" value={fmt(stats.total_queries)} />
          <StatRow label="Input tokens" value={fmt(stats.tokens_in)} />
          <StatRow label="Output tokens" value={fmt(stats.tokens_out)} />
          <StatRow label="Total tokens" value={fmt(stats.tokens_total)} />
          <StatRow label="Est. cost" value={`$${parseFloat(stats.cost_usd).toFixed(4)}`} />
        </div>
      )}

      <p className="text-xs text-gray-400 text-center px-2">
        Cache hits excluded — only LLM calls are counted
      </p>
    </div>
  )
}
