import type { AgentChatRequest } from '@/components/agent/chatInteraction'

export interface AgentPayload {
  message: string
  success: boolean
  data?: Record<string, any>
  error?: string | null
}

export interface RunEvent {
  type: string
  run_id: string
  sequence: number
  timestamp?: string
  data: Record<string, any>
}

function parseEvent(line: string): RunEvent {
  const parsed = JSON.parse(line) as RunEvent
  if (!parsed || typeof parsed.type !== 'string' || typeof parsed.sequence !== 'number') {
    throw new Error('Agent 事件流包含无效事件。')
  }
  return parsed
}

export async function streamAgentRun<T extends AgentPayload = AgentPayload>(
  request: AgentChatRequest,
  onEvent: (event: RunEvent) => void,
  fetcher: typeof fetch = fetch,
): Promise<T> {
  const response = await fetcher('/agent/runs/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(detail || `HTTP ${response.status}`)
  }
  if (!response.body) throw new Error('Agent 事件流没有响应正文。')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalResponse: T | null = null
  let finalCount = 0

  const consume = (line: string) => {
    const trimmed = line.trim()
    if (!trimmed) return
    const event = parseEvent(trimmed)
    onEvent(event)
    if (event.type === 'response.completed') {
      finalCount += 1
      finalResponse = event.data?.response as T
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    lines.forEach(consume)
  }
  buffer += decoder.decode()
  consume(buffer)

  if (finalCount !== 1 || !finalResponse) {
    throw new Error(`Agent 事件流必须包含且仅包含一个 response.completed，实际为 ${finalCount}。`)
  }
  return finalResponse
}
