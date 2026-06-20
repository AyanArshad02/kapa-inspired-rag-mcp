const AUTH_URL = process.env.NEXT_PUBLIC_AUTH_URL ?? 'http://localhost:8004'
const INGESTION_URL = process.env.NEXT_PUBLIC_INGESTION_URL ?? 'http://localhost:8001'
const QUERY_URL = process.env.NEXT_PUBLIC_QUERY_URL ?? 'http://localhost:8000'

// Module-level access token — lives in JS memory (not localStorage, not cookie).
// Safe from XSS because nothing persists it to storage.
let _accessToken: string | null = null

export function setAccessToken(t: string | null) {
  _accessToken = t
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function signupApi(email: string, password: string): Promise<{ access_token: string }> {
  const res = await fetch(`${AUTH_URL}/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? 'Signup failed')
  }
  return res.json()
}

export async function guestLoginApi(): Promise<{ access_token: string }> {
  const res = await fetch(`${AUTH_URL}/auth/guest`, {
    method: 'POST',
    credentials: 'include',
  })
  if (!res.ok) throw new Error('Guest login failed')
  return res.json()
}

export async function loginApi(email: string, password: string): Promise<{ access_token: string }> {
  const res = await fetch(`${AUTH_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? 'Invalid email or password')
  }
  return res.json()
}

// Called on page load to restore session from the httpOnly refresh cookie.
// Returns the new access token, or null if no valid session exists or backend is unreachable.
export async function refreshApi(): Promise<string | null> {
  try {
    const res = await fetch(`${AUTH_URL}/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
    })
    if (!res.ok) return null
    const data = await res.json()
    _accessToken = data.access_token
    return _accessToken
  } catch {
    return null
  }
}

export async function logoutApi(): Promise<void> {
  try {
    await fetch(`${AUTH_URL}/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    })
  } catch {
    // ignore — clear local state regardless
  }
  _accessToken = null
}

// ── Authenticated fetch with auto-refresh on 401 ──────────────────────────────

async function authFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const withAuth = (token: string | null): RequestInit => ({
    ...init,
    headers: {
      ...init.headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })

  let res = await fetch(url, withAuth(_accessToken))

  if (res.status === 401) {
    const newToken = await refreshApi()
    if (newToken) {
      res = await fetch(url, withAuth(newToken))
    }
  }

  return res
}

// ── Ingestion ─────────────────────────────────────────────────────────────────

export interface Source {
  source_url: string
  source_type: string
}

export async function listSourcesApi(): Promise<Source[]> {
  const res = await authFetch(`${INGESTION_URL}/sources`)
  if (!res.ok) throw new Error('Failed to list sources')
  return res.json()
}

export async function ingestUrlApi(sourceUrl: string, sourceType: string): Promise<{ job_id: string }> {
  const res = await authFetch(`${INGESTION_URL}/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_url: sourceUrl, source_type: sourceType }),
  })
  if (!res.ok) throw new Error(`Ingest failed (${res.status}): ${await res.text()}`)
  return res.json()
}

export async function uploadFileApi(file: File): Promise<{ job_id: string }> {
  // Step 1 — ask backend for a presigned S3 PUT URL
  const presignRes = await authFetch(`${INGESTION_URL}/ingest/presign`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: file.name, content_type: file.type }),
  })
  if (!presignRes.ok) throw new Error(`Presign failed (${presignRes.status}): ${await presignRes.text()}`)
  const { presigned_url, s3_url } = await presignRes.json()

  // Step 2 — PUT file bytes directly to S3 (no auth header — presigned URL is self-contained)
  const s3Res = await fetch(presigned_url, {
    method: 'PUT',
    headers: { 'Content-Type': file.type },
    body: file,
  })
  if (!s3Res.ok) throw new Error(`S3 upload failed (${s3Res.status})`)

  // Step 3 — tell backend the file is in S3, start ingestion job
  const confirmRes = await authFetch(`${INGESTION_URL}/ingest/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ s3_url }),
  })
  if (!confirmRes.ok) throw new Error(`Confirm failed (${confirmRes.status}): ${await confirmRes.text()}`)
  return confirmRes.json()
}

export async function deleteSourceApi(sourceUrl: string): Promise<void> {
  const res = await authFetch(
    `${INGESTION_URL}/ingest/upload?${new URLSearchParams({ source_url: sourceUrl })}`,
    { method: 'DELETE' },
  )
  if (!res.ok) throw new Error('Delete failed')
}

export async function pollJobApi(jobId: string): Promise<string> {
  const res = await authFetch(`${INGESTION_URL}/ingest/${jobId}`)
  if (!res.ok) return 'unknown'
  const data = await res.json()
  return data.status as string
}

// ── Conversations ─────────────────────────────────────────────────────────────

export interface ConversationSummary {
  conversation_id: string
  last_active: string
  message_count: number
  preview: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export async function listConversationsApi(): Promise<ConversationSummary[]> {
  const res = await authFetch(`${QUERY_URL}/query/conversations`)
  if (!res.ok) throw new Error('Failed to list conversations')
  return res.json()
}

export async function getConversationMessagesApi(conversationId: string): Promise<ChatMessage[]> {
  const res = await authFetch(`${QUERY_URL}/query/conversations/${conversationId}/messages`)
  if (!res.ok) throw new Error('Failed to load conversation')
  return res.json()
}

// ── Query ─────────────────────────────────────────────────────────────────────

export interface QueryResult {
  answer: string
  conversation_id: string
  source_urls: string[]
  cached: boolean
}

export async function queryApi(query: string, conversationId: string | null): Promise<QueryResult> {
  const res = await authFetch(`${QUERY_URL}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, stream: false, conversation_id: conversationId }),
  })
  if (res.status === 429) {
    throw new Error('Rate limit reached — you can send 20 requests per minute. Please wait 60 seconds and try again.')
  }
  if (!res.ok) throw new Error(`Query failed (${res.status}): ${await res.text()}`)
  return res.json()
}

// ── Display helpers ───────────────────────────────────────────────────────────

/**
 * Returns a human-readable label for a source URL.
 *   s3://bucket/tenant/My File_abc123def.pdf  →  "My File.pdf"
 *   https://fastapi.tiangolo.com/tutorial/     →  "fastapi.tiangolo.com/tutorial"
 */
export function formatSourceUrl(url: string): string {
  if (url.startsWith('s3://')) {
    const filename = url.split('/').filter(Boolean).pop() ?? url
    // Strip the upload hash suffix appended by S3Storage: "name_<32 hex chars>.ext" → "name.ext"
    return filename.replace(/_[a-f0-9]{32}(\.[^.]+)$/, '$1')
  }
  try {
    const { hostname, pathname } = new URL(url)
    const path = pathname.replace(/\/$/, '')
    return path ? `${hostname}${path}` : hostname
  } catch {
    return url
  }
}

// ── Usage ─────────────────────────────────────────────────────────────────────

export interface UsageStats {
  tenant_id: string
  period_days: number
  total_queries: number
  tokens_in: number
  tokens_out: number
  tokens_total: number
  cost_usd: string
}

export async function getUsageApi(days: number = 30): Promise<UsageStats> {
  const res = await authFetch(`${QUERY_URL}/usage?days=${days}`)
  if (!res.ok) throw new Error('Failed to load usage stats')
  return res.json()
}

// ── Admin ─────────────────────────────────────────────────────────────────────

export interface AdminTenant {
  tenant_id: string
  name: string
  email: string
  is_admin: boolean
  source_count: number
  conversation_count: number
  query_count: number
  tokens_in: number
  tokens_out: number
  cost_usd: string
}

export interface AdminOverview {
  totals: { tenants: number; users: number; sources: number; queries: number; tokens_in: number; tokens_out: number }
  tenants: AdminTenant[]
  recent_queries: { content: string; tenant_name: string; created_at: string }[]
  sources_by_type: { type: string; count: number }[]
}

export async function adminOverviewApi(): Promise<AdminOverview> {
  const res = await authFetch(`${QUERY_URL}/admin/overview`)
  if (!res.ok) throw new Error('Failed to load admin overview')
  return res.json()
}
