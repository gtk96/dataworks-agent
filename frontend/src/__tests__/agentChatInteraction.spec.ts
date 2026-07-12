import { describe, expect, it, vi } from 'vitest'
import { buildAgentChatRequest, requestAgentChat } from '@/components/agent/chatInteraction'

describe('Agent chat interaction', () => {
  it('builds an automatic execution request for conversational use', () => {
    expect(buildAgentChatRequest('  查一下今天各家族的有效订单数  ', 'auto', true, false)).toEqual({
      message: '查一下今天各家族的有效订单数',
      execution_mode: 'auto',
      initialize_data: true,
      publish: false,
    })
  })

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
  it('preserves the conversation id for semantic follow-ups', () => {
    expect(buildAgentChatRequest('follow up', 'auto', true, false, 'conversation-1')).toEqual({
      message: 'follow up',
      execution_mode: 'auto',
      initialize_data: true,
      publish: false,
      conversation_id: 'conversation-1',
    })
  })

})
