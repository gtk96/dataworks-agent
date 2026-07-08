/** HTTP 客户端 — 所有 API 请求的基础封装。 */

const BASE = ''

interface RequestOptions {
  method?: string
  headers?: Record<string, string>
  body?: unknown
}

export async function request<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', headers = {}, body } = options

  const init: RequestInit = {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...headers,
    },
  }

  if (body && method !== 'GET') {
    init.body = JSON.stringify(body)
  }

  const resp = await fetch(`${BASE}${path}`, init)
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(err.detail || `HTTP ${resp.status}`)
  }
  return resp.json()
}

/** 生成幂等键 */
export function idempotencyKey(): string {
  return crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
}
