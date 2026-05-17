'use client'

import { useRef, useState } from 'react'
import { ingestUrlApi, pollJobApi, uploadFileApi } from '@/lib/api'

type Tab = 'upload' | 'github' | 'docs'

interface Job {
  id: string
  label: string
  status: string
}

const STATUS_ICON: Record<string, string> = {
  pending: '⏳',
  processing: '🔄',
  completed: '✅',
  failed: '❌',
}

export default function AddSourcePanel({ onIngested }: { onIngested: () => void }) {
  const [tab, setTab] = useState<Tab>('upload')
  const [url, setUrl] = useState('')
  const [jobs, setJobs] = useState<Job[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  function startPolling(jobId: string, label: string) {
    setJobs((prev) => [...prev, { id: jobId, label, status: 'pending' }])
    const timer = setInterval(async () => {
      const status = await pollJobApi(jobId)
      setJobs((prev) => prev.map((j) => (j.id === jobId ? { ...j, status } : j)))
      if (status === 'completed' || status === 'failed') {
        clearInterval(timer)
        if (status === 'completed') onIngested()
      }
    }, 2500)
  }

  async function handleUpload() {
    const file = fileRef.current?.files?.[0]
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const { job_id } = await uploadFileApi(file)
      startPolling(job_id, file.name)
      if (fileRef.current) fileRef.current.value = ''
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleUrl(sourceType: string) {
    if (!url.trim()) return
    setBusy(true)
    setError('')
    try {
      const { job_id } = await ingestUrlApi(url.trim(), sourceType)
      startPolling(job_id, url.trim())
      setUrl('')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to queue')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
        Add Knowledge Source
      </h2>

      {/* Tab bar */}
      <div className="flex border-b border-gray-200 mb-3 -mx-4 px-4">
        {(['upload', 'github', 'docs'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`text-xs px-3 py-2 -mb-px border-b-2 transition-colors ${
              tab === t
                ? 'border-blue-600 text-blue-600 font-medium'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t === 'upload' ? 'File' : t === 'github' ? 'GitHub' : 'Docs URL'}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'upload' && (
        <div className="space-y-2">
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.md"
            className="w-full text-xs text-gray-600 file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:text-xs file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer"
          />
          <button
            onClick={handleUpload}
            disabled={busy}
            className="w-full bg-blue-600 text-white text-xs py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {busy ? 'Uploading…' : 'Ingest File'}
          </button>
        </div>
      )}

      {tab === 'github' && (
        <div className="space-y-2">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/org/repo"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            onClick={() => handleUrl('github')}
            disabled={busy || !url.trim()}
            className="w-full bg-blue-600 text-white text-xs py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {busy ? 'Queuing…' : 'Ingest Repo'}
          </button>
        </div>
      )}

      {tab === 'docs' && (
        <div className="space-y-2">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://docs.example.com"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            onClick={() => handleUrl('docs_site')}
            disabled={busy || !url.trim()}
            className="w-full bg-blue-600 text-white text-xs py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {busy ? 'Queuing…' : 'Ingest Docs'}
          </button>
        </div>
      )}

      {error && (
        <p className="text-xs text-red-500 mt-2 bg-red-50 px-2 py-1.5 rounded">
          {error}
        </p>
      )}

      {/* Active jobs */}
      {jobs.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-medium text-gray-500 mb-1.5">Processing Jobs</p>
          <ul className="space-y-1">
            {jobs.map((j) => {
              const label = j.label.length > 26 ? j.label.slice(0, 26) + '…' : j.label
              return (
                <li key={j.id} className="flex items-center gap-1.5 text-xs text-gray-600">
                  <span>{STATUS_ICON[j.status] ?? '❓'}</span>
                  <span className="truncate">{label}</span>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
