import { describe, expect, it, vi } from 'vitest'
import { buildAgentChatRequest, requestAgentChat } from '@/components/agent/chatInteraction'

describe('Agent chat interaction', () => {
  it('builds an explicit safe planning request', () => {
    expect(buildAgentChatRequest('  查询 ods_order  ', 'plan', true, false)).toEqual({
      message: '查询 ods_order',
      execution_mode: 'plan',
      initialize_data: true,
      publish: false,
    })
  })

  it('uses HTTP and returns the structured payload', async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ success: true, message: 'ok' }),
    })
    const payload = buildAgentChatRequest('检查状态', 'plan', false, false)

    await expect(requestAgentChat(payload, fetcher as typeof fetch, 1000)).resolves.toEqual({ success: true, message: 'ok' })
    expect(fetcher).toHaveBeenCalledWith('/agent/chat', expect.objectContaining({ method: 'POST' }))
  })

  it('surfaces non-2xx API errors', async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: vi.fn().mockResolvedValue({ detail: 'backend unavailable' }),
    })
    const payload = buildAgentChatRequest('检查状态', 'plan', false, false)

    await expect(requestAgentChat(payload, fetcher as typeof fetch, 1000)).rejects.toThrow('backend unavailable')
  })
})
