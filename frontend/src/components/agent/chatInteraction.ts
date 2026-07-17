export type AgentExecutionMode = 'auto' | 'plan' | 'dev_execute'
export type AgentContextUpdates = Record<string, unknown>

export interface InteractionAnswer {
  interaction_id: string
  option_id?: string
  custom_text?: string
  state_version: number
}

export interface AgentInteractionOption {
  id: string
  label: string
  value?: unknown
  description?: string
  layer?: string
}

export interface AgentInteraction {
  interaction_id: string
  type: 'single_select' | 'confirm' | 'free_text'
  purpose: string
  prompt: string
  options: AgentInteractionOption[]
  allow_custom_input: boolean
  custom_input_placeholder?: string
  status: 'pending' | 'answered' | 'expired' | 'cancelled'
  state_version: number
}

export interface AgentChatRequest {
  message: string
  execution_mode: AgentExecutionMode
  initialize_data: boolean
  publish: boolean
  conversation_id?: string
  context_updates?: AgentContextUpdates
  interaction_answer?: InteractionAnswer
}

export function buildAgentChatRequest(
  message: string,
  executionMode: AgentExecutionMode,
  initializeData: boolean,
  publish: boolean,
  conversationId?: string,
  contextUpdates?: AgentContextUpdates,
  interactionAnswer?: InteractionAnswer,
): AgentChatRequest {
  return {
    message: message.trim(),
    execution_mode: executionMode,
    initialize_data: initializeData,
    publish,
    ...(conversationId ? { conversation_id: conversationId } : {}),
    ...(contextUpdates ? { context_updates: contextUpdates } : {}),
    ...(interactionAnswer ? { interaction_answer: interactionAnswer } : {}),
  }
}

export async function requestAgentChat<T>(
  payload: AgentChatRequest,
  fetcher: typeof fetch = fetch,
  timeoutMs = 90_000,
): Promise<T> {
  const controller = new AbortController()
  const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs)
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
    globalThis.clearTimeout(timeout)
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
