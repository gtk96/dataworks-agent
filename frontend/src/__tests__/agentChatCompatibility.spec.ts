// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AgentChat from '@/components/agent/AgentChat.vue'

const interaction = {
  interaction_id: 'int-agent-chat',
  type: 'single_select' as const,
  purpose: 'select_table',
  prompt: '请选择目标表',
  options: [
    {
      id: 'table-1',
      label: '订单明细表',
      value: 'giikin_aliyun.tb_dwd_order',
      payload: {},
    },
  ],
  allow_custom_input: true,
  custom_input_placeholder: '输入其他表名',
  status: 'pending' as const,
  state_version: 3,
}

class MockWebSocket {
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  close() {}
}

describe('AgentChat structured interaction compatibility', () => {
  beforeEach(() => {
    localStorage.setItem('conversation_id', 'conv-agent-chat')
    vi.stubGlobal('WebSocket', MockWebSocket)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('restores the active interaction and submits the server-owned option id', async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input)
      if (url.startsWith('/agent/messages')) {
        return {
          ok: true,
          json: async () => ({
            messages: [
              { role: 'user', content: '找订单表', timestamp: '2026-07-17T00:00:00Z', payload: {} },
              {
                role: 'assistant',
                content: '请选择目标表',
                timestamp: '2026-07-17T00:00:01Z',
                payload: { interaction },
              },
            ],
            active_interaction: interaction,
            state_version: 3,
          }),
        } as Response
      }
      if (url === '/agent/capabilities') {
        return { ok: true, json: async () => ({ capabilities: {} }) } as Response
      }
      if (url === '/agent/chat') {
        return {
          ok: true,
          json: async () => ({ success: true, message: '已选择', data: {} }),
        } as Response
      }
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetcher)

    const wrapper = mount(AgentChat, {
      global: {
        stubs: {
          'el-button': true,
          'el-collapse': true,
          'el-collapse-item': true,
          'el-icon': true,
          'el-segmented': true,
        },
      },
    })
    await flushPromises()

    const option = wrapper.get('[data-interaction-option="table-1"]')
    await option.trigger('click')
    await flushPromises()

    const chatCall = fetcher.mock.calls.find(([url]) => String(url) === '/agent/chat')
    expect(chatCall).toBeTruthy()
    expect(JSON.parse(String(chatCall?.[1]?.body))).toMatchObject({
      conversation_id: 'conv-agent-chat',
      interaction_answer: {
        interaction_id: 'int-agent-chat',
        option_id: 'table-1',
        state_version: 3,
      },
    })
  })

  it('restores the active option when submitting the answer fails', async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/agent/messages')) {
        return {
          ok: true,
          json: async () => ({
            messages: [
              { role: 'user', content: '找订单表', timestamp: '2026-07-17T00:00:00Z', payload: {} },
              {
                role: 'assistant',
                content: '请选择目标表',
                timestamp: '2026-07-17T00:00:01Z',
                payload: { interaction },
              },
            ],
            active_interaction: interaction,
            state_version: 3,
          }),
        } as Response
      }
      if (url === '/agent/capabilities') {
        return { ok: true, json: async () => ({ capabilities: {} }) } as Response
      }
      if (url === '/agent/chat') {
        return {
          ok: false,
          status: 503,
          json: async () => ({ detail: 'backend unavailable' }),
        } as Response
      }
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetcher)

    const wrapper = mount(AgentChat, {
      global: {
        stubs: {
          'el-button': true,
          'el-collapse': true,
          'el-collapse-item': true,
          'el-icon': true,
          'el-segmented': true,
        },
      },
    })
    await flushPromises()

    await wrapper.get('[data-interaction-option="table-1"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-interaction-option="table-1"]').attributes('disabled')).toBeUndefined()
  })
})
