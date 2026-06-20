'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/components/AuthContext'
import { adminOverviewApi, type AdminOverview } from '@/lib/api'

export default function AdminPage() {
  const { user, loading } = useAuth()
  const router = useRouter()
  const [data, setData] = useState<AdminOverview | null>(null)
  const [error, setError] = useState('')
  const [fetching, setFetching] = useState(true)

  useEffect(() => {
    if (!loading && !user) { router.replace('/login'); return }
    if (!loading && user && !user.isAdmin) { router.replace('/dashboard'); return }
  }, [user, loading, router])

  useEffect(() => {
    if (!user?.isAdmin) return
    adminOverviewApi()
      .then(setData)
      .catch(() => setError('Failed to load admin data'))
      .finally(() => setFetching(false))
  }, [user])

  if (loading || fetching) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <p className="text-red-600">{error}</p>
      </div>
    )
  }

  if (!data) return null

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-lg font-semibold text-gray-900">Admin Dashboard</span>
        </div>
        <Link
          href="/dashboard"
          className="text-sm text-gray-500 hover:text-gray-700 border border-gray-200 px-3 py-1 rounded-lg hover:bg-gray-50 transition-colors"
        >
          ← Back to Dashboard
        </Link>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-8">

        {/* Totals */}
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">Overview</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            {[
              { label: 'Tenants', value: data.totals.tenants.toLocaleString() },
              { label: 'Users', value: data.totals.users.toLocaleString() },
              { label: 'Sources', value: data.totals.sources.toLocaleString() },
              { label: 'Total Queries', value: data.totals.queries.toLocaleString() },
              { label: 'Tokens In (30d)', value: data.totals.tokens_in.toLocaleString() },
              { label: 'Tokens Out (30d)', value: data.totals.tokens_out.toLocaleString() },
            ].map((stat) => (
              <div key={stat.label} className="bg-white rounded-xl border border-gray-200 p-5">
                <p className="text-sm text-gray-500">{stat.label}</p>
                <p className="text-2xl font-bold text-gray-900 mt-1">{stat.value}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Sources by type */}
        {data.sources_by_type.length > 0 && (
          <section>
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">Sources by Type</h2>
            <div className="flex gap-3 flex-wrap">
              {data.sources_by_type.map((s) => (
                <div key={s.type} className="bg-white rounded-lg border border-gray-200 px-4 py-2 flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-700">{s.type}</span>
                  <span className="text-sm text-gray-400">·</span>
                  <span className="text-sm font-bold text-blue-600">{s.count}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Tenant table */}
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">Tenants</h2>
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  {['Email', 'Sources', 'Conversations', 'Queries', 'Tokens In', 'Tokens Out', 'Cost (30d)', 'Role'].map((h) => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.tenants.map((t) => (
                  <tr key={t.tenant_id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3 text-gray-900 font-medium">{t.email ?? '—'}</td>
                    <td className="px-4 py-3 text-gray-600">{t.source_count}</td>
                    <td className="px-4 py-3 text-gray-600">{t.conversation_count}</td>
                    <td className="px-4 py-3 font-semibold text-blue-600">{t.query_count.toLocaleString()}</td>
                    <td className="px-4 py-3 text-gray-600 tabular-nums">{t.tokens_in.toLocaleString()}</td>
                    <td className="px-4 py-3 text-gray-600 tabular-nums">{t.tokens_out.toLocaleString()}</td>
                    <td className="px-4 py-3 text-gray-600 tabular-nums">${t.cost_usd}</td>
                    <td className="px-4 py-3">
                      {t.is_admin
                        ? <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full font-medium">Admin</span>
                        : <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">User</span>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Recent queries */}
        {data.recent_queries.length > 0 && (
          <section>
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">Recent Queries</h2>
            <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
              {data.recent_queries.map((q, i) => (
                <div key={i} className="px-4 py-3 flex items-start justify-between gap-4">
                  <p className="text-sm text-gray-800 flex-1">{q.content}</p>
                  <div className="text-right shrink-0">
                    <p className="text-xs text-gray-400">{q.tenant_name}</p>
                    <p className="text-xs text-gray-400">{new Date(q.created_at).toLocaleString()}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

      </main>
    </div>
  )
}
