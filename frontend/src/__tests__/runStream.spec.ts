import { describe, expect, it, vi } from 'vitest'
import { streamAgentRun, type RunEvent } from '@/components/agent/runStream'

function chunkedResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  let index = 0
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () => index < chunks.length
          ? { done: false, value: encoder.encode(chunks[index++]) }
          : { done: true, value: undefined },
      }),
    },
  } as unknown as Response
}

describe('streamAgentRun', () => {
  it('parses arbitrary UTF-8 chunk boundaries and returns exactly one final response', async () => {
    const rows = [
      { type: 'run.started', run_id: 'run-1', sequence: 1, data: {} },
      { type: 'tool.started', run_id: 'run-1', sequence: 2, data: { tool: 'find_table' } },
      {
        type: 'response.completed',
        run_id: 'run-1',
        sequence: 3,
        data: { response: { message: '请选择订单表', success: true, data: {} } },
      },
    ]
    const wire = `${rows.map(row => JSON.stringify(row)).join('\n')}\n`
    const bytes = [...wire]
    const chunks = [bytes.slice(0, 17).join(''), bytes.slice(17, 53).join(''), bytes.slice(53).join('')]
    const fetcher = vi.fn(async () => chunkedResponse(chunks)) as unknown as typeof fetch
    const events: RunEvent[] = []

    const response = await streamAgentRun(
      { message: '找订单表', execution_mode: 'auto', initialize_data: true, publish: false },
      event => events.push(event),
      fetcher,
    )

    expect(events.map(event => event.type)).toEqual(rows.map(row => row.type))
    expect(response.message).toBe('请选择订单表')
    expect(fetcher).toHaveBeenCalledWith('/agent/runs/stream', expect.objectContaining({ method: 'POST' }))
  })

  it('rejects a stream without one authoritative completed response', async () => {
    const fetcher = vi.fn(async () => chunkedResponse([
      '{"type":"run.started","run_id":"run-1","sequence":1,"data":{}}\n',
    ])) as unknown as typeof fetch

    await expect(streamAgentRun(
      { message: '你好', execution_mode: 'auto', initialize_data: true, publish: false },
      () => undefined,
      fetcher,
    )).rejects.toThrow('response.completed')
  })
})
