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

export interface ConversationMeta {
  conversation_id: string
  active_goal: string
  action: string
  status: string
  state_version: number
  selected_resources: Record<string, unknown>
}

const agentModeLabels: Record<string, string> = {
  idle: '等待目标',
  proposal: '计划完成',
  needs_context: '待确认',
  waiting_user: '等待补充',
  approval_required: '等待审批',
  blocked: '执行受阻',
  rejected: '已拒绝',
  recoverable_error: '依赖待恢复',
  execution_unknown: '执行结果待确认',
  executed: '开发完成',
}

export function agentModeLabel(mode: string): string {
  return agentModeLabels[mode] ?? mode
}

export interface InteractionMessage {
  role?: 'user' | 'assistant'
  isUser?: boolean
  interaction?: AgentInteraction
}

function isAssistantMessage(message: InteractionMessage): boolean {
  return message.role === 'assistant' || message.isUser === false
}

export function reconcileActiveInteraction<T extends InteractionMessage>(
  messages: T[],
  active: AgentInteraction | null | undefined,
): T[] {
  const reconciled = messages.map(message => ({
    ...message,
    ...(message.interaction ? { interaction: { ...message.interaction } } : {}),
  })) as T[]

  let activeIndex = -1
  for (let index = 0; index < reconciled.length; index += 1) {
    const interaction = reconciled[index].interaction
    if (!interaction) continue
    if (active && interaction.interaction_id === active.interaction_id) {
      activeIndex = index
      reconciled[index].interaction = { ...active }
    } else if (interaction.status === 'pending') {
      reconciled[index].interaction = { ...interaction, status: 'expired' }
    }
  }

  if (active && activeIndex < 0) {
    for (let index = reconciled.length - 1; index >= 0; index -= 1) {
      if (isAssistantMessage(reconciled[index])) {
        reconciled[index].interaction = { ...active }
        break
      }
    }
  }

  return reconciled
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
