export type AgentExecutionMode = 'auto' | 'plan' | 'dev_execute'

export interface AgentChatRequest {
  message: string
  execution_mode: AgentExecutionMode
  initialize_data: boolean
  publish: boolean
  conversation_id?: string
}

export function buildAgentChatRequest(
  message: string,
  executionMode: AgentExecutionMode,
  initializeData: boolean,
  publish: boolean,
  conversationId?: string,
): AgentChatRequest {
  return {
    message: message.trim(),
    execution_mode: executionMode,
    initialize_data: initializeData,
    publish,
    ...(conversationId ? { conversation_id: conversationId } : {}),
  }
}

export async function requestAgentChat<T>(
  payload: AgentChatRequest,
  fetcher: typeof fetch = fetch,
  timeoutMs = 90_000,
): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetcher('/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
    const data = await response.json().catch(() => null)
    if (!response.ok) {
      const detail = data && typeof data === 'object' && 'detail' in data ? String(data.detail) : `HTTP ${response.status}`
      throw new Error(detail)
    }
    return data as T
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(`Agent 请求超过 ${Math.round(timeoutMs / 1000)} 秒，已停止等待，请重试。`)
    }
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
}

export interface PublishReviewResponse {
  success: boolean
  message: string
  request: Record<string, unknown>
}

export async function reviewPublishRequest(
  requestId: string,
  decision: 'approve' | 'reject',
  fetcher: typeof fetch = fetch,
): Promise<PublishReviewResponse> {
  const response = await fetcher(
    `/agent/publish-gate/${encodeURIComponent(requestId)}/${decision}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reviewer: 'web-user' }),
    },
  )
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? String(data.detail) : `HTTP ${response.status}`
    throw new Error(detail)
  }
  return data as PublishReviewResponse
}
