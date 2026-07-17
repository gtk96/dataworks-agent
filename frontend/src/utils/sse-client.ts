/**
 * SSE Stream Client for real-time chat.
 * Connects to /agent/chat/stream?q=...&conversation_id=...&execution_mode=...
 * Returns an async generator of events.
 */

export interface SSEConnectResponse {
  type: 'connected';
  stream_id: string;
  conversation_id: string;
}

export interface SSEStatusResponse {
  type: 'thinking';
  message: string;
}

export interface SSEErrorResponse {
  type: 'error';
  message: string;
}

export interface SSEResponseResponse {
  type: 'response';
  message: string;
  success: boolean;
  data: Record<string, unknown>;
  error?: string | null;
  conversation_id: string;
}

export type SSEEvent = SSEConnectResponse | SSEStatusResponse | SSEErrorResponse | SSEResponseResponse;

export interface SSEStreamOptions {
  onEvent?: (event: SSEEvent) => void;
  onError?: (err: Error) => void;
  executionMode?: 'auto' | 'plan' | 'dev_execute';
  conversationId?: string;
}

export function createSSEStream(
  message: string,
  options: SSEStreamOptions = {},
): AbortController {
  const { onEvent, onError, executionMode = 'auto', conversationId } = options;

  const params = new URLSearchParams();
  params.set('q', message);
  if (conversationId) params.set('conversation_id', conversationId);
  params.set('execution_mode', executionMode);

  const url = `/agent/chat/stream?${params.toString()}`;
  const controller = new AbortController();

  fetch(url, { signal: controller.signal })
    .then(async (resp) => {
      if (!resp.ok) {
        throw new Error(`SSE 连接失败: ${resp.status}`);
      }

      const reader = resp.body?.getReader();
      if (!reader) throw new Error('无法读取响应流');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        // Parse SSE frames (events are separated by double newlines)
        for (let i = 0; i < lines.length; i++) {
          const line = lines[i];
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              const event: SSEEvent = data;
              onEvent?.(event);
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onError?.(err);
      }
    });

  return controller;
}
