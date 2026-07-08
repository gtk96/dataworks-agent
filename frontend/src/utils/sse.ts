/** SSE 流式消费者 — 用于任务实时进度推送，支持自动重连。 */

export interface SSEEvent {
  event: string
  task_id: string
  step: string
  status: string
  message: string
  data: Record<string, unknown>
  timestamp: string
}

export interface SSEOptions {
  /** 最大重试次数 */
  maxRetries?: number
  /** 初始重试延迟（毫秒） */
  initialRetryDelay?: number
  /** 最大重试延迟（毫秒） */
  maxRetryDelay?: number
}

export function createSSEStream(
  url: string,
  onEvent: (event: SSEEvent) => void,
  onError?: (err: Error) => void,
  options: SSEOptions = {},
): AbortController {
  const {
    maxRetries = 5,
    initialRetryDelay = 1000,
    maxRetryDelay = 30000,
  } = options

  const controller = new AbortController()
  let retryCount = 0
  let retryTimeout: ReturnType<typeof setTimeout> | null = null

  const connect = () => {
    fetch(url, { signal: controller.signal })
      .then(async (resp) => {
        if (!resp.ok) throw new Error(`SSE 连接失败: ${resp.status}`)

        // 连接成功，重置重试计数
        retryCount = 0

        const reader = resp.body?.getReader()
        if (!reader) throw new Error('无法读取响应流')

        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) {
            // 流结束，尝试重连
            if (!controller.signal.aborted) {
              scheduleReconnect()
            }
            break
          }

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data: SSEEvent = JSON.parse(line.slice(6))
                onEvent(data)
              } catch {
                // skip malformed events
              }
            }
          }
        }
      })
      .catch((err) => {
        if (err.name !== 'AbortError') {
          // 连接失败，尝试重连
          if (retryCount < maxRetries) {
            scheduleReconnect()
          } else {
            onError?.(err)
          }
        }
      })
  }

  const scheduleReconnect = () => {
    if (controller.signal.aborted) return

    const delay = Math.min(
      initialRetryDelay * Math.pow(2, retryCount),
      maxRetryDelay
    )
    retryCount++

    console.warn(`SSE 重连中，延迟 ${delay}ms (第 ${retryCount} 次)`)
    retryTimeout = setTimeout(connect, delay)
  }

  // 开始连接
  connect()

  // 返回 controller 时，清除重试定时器
  const originalAbort = controller.abort.bind(controller)
  controller.abort = () => {
    if (retryTimeout) {
      clearTimeout(retryTimeout)
      retryTimeout = null
    }
    originalAbort()
  }

  return controller
}
