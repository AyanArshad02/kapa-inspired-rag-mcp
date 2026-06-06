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
  const form = new FormData()
  form.append('file', file)
  const res = await authFetch(`${INGESTION_URL}/ingest/upload`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw new Error(`Upload failed (${res.status}): ${await res.text()}`)
  return res.json()
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
  if (!res.ok) throw new Error(`Query failed (${res.status}): ${await res.text()}`)
  return res.json()
}
