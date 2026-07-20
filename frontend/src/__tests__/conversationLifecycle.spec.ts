// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SmartChatPage from '@/pages/SmartChatPage.vue'
import {
  agentModeLabel,
  reconcileActiveInteraction,
  type AgentInteraction,
  type InteractionMessage,
} from '@/components/agent/chatInteraction'

const firstInteraction: AgentInteraction = {
  interaction_id: 'int-old',
  type: 'single_select',
  purpose: 'choose_entry',
  prompt: 'Choose an entry',
  options: [{ id: 'ask', label: 'Ask data' }],
  allow_custom_input: true,
  status: 'pending',
  state_version: 1,
}

const latestInteraction: AgentInteraction = {
  ...firstInteraction,
  interaction_id: 'int-latest',
  prompt: 'Choose a target table',
  options: [{ id: 'table-1', label: 'Order detail table' }],
  state_version: 3,
}

function ndjsonResponse(events: Record<string, unknown>[]): Response {
  const bytes = new TextEncoder().encode(`${events.map(event => JSON.stringify(event)).join('\n')}\n`)
  let consumed = false
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () => {
          if (consumed) return { done: true, value: undefined }
          consumed = true
          return { done: false, value: bytes }
        },
      }),
    },
  } as unknown as Response
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('conversation interaction lifecycle', () => {
  it('labels recovery and uncertainty modes without exposing backend identifiers', () => {
    expect(agentModeLabel('waiting_user')).toBe('等待补充')
    expect(agentModeLabel('recoverable_error')).toBe('依赖待恢复')
    expect(agentModeLabel('execution_unknown')).toBe('执行结果待确认')
  })

  it('expires historical pending cards and installs the server-owned active card', () => {
    const messages: InteractionMessage[] = [
      { role: 'assistant', interaction: firstInteraction },
      { role: 'user' },
      { role: 'assistant' },
    ]

    const reconciled = reconcileActiveInteraction(messages, latestInteraction)

    expect(reconciled[0].interaction?.status).toBe('expired')
    expect(reconciled[2].interaction).toEqual(latestInteraction)
    expect(messages[0].interaction?.status).toBe('pending')
  })

  it('replaces a matching history card with the authoritative server snapshot', () => {
    const stale = { ...latestInteraction, prompt: 'stale prompt', state_version: 2 }
    const reconciled = reconcileActiveInteraction(
      [{ role: 'assistant', interaction: stale }],
      latestInteraction,
    )

    expect(reconciled[0].interaction).toEqual(latestInteraction)
  })

  it('marks every unresolved card expired when the server has no active interaction', () => {
    const reconciled = reconcileActiveInteraction(
      [
        { role: 'assistant', interaction: firstInteraction },
        { role: 'assistant', interaction: { ...latestInteraction, status: 'answered' } },
      ],
      null,
    )

    expect(reconciled[0].interaction?.status).toBe('expired')
    expect(reconciled[1].interaction?.status).toBe('answered')
  })

  it('applies the latest interaction returned by an expired answer response', async () => {
    localStorage.setItem('conversation_id', 'conv-smart-chat')
    const replacement: AgentInteraction = {
      ...latestInteraction,
      interaction_id: 'int-replacement',
      options: [{ id: 'refund-table', label: 'Refund detail table' }],
      state_version: 4,
    }
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/agent/messages')) {
        return {
          ok: true,
          json: async () => ({
            messages: [{
              role: 'assistant',
              content: firstInteraction.prompt,
              payload: { interaction: firstInteraction },
            }],
            active_interaction: firstInteraction,
            conversation: {
              conversation_id: 'conv-smart-chat',
              active_goal: '',
              action: '',
              status: 'idle',
              state_version: 1,
              selected_resources: {},
            },
          }),
        } as Response
      }
      if (url === '/agent/capabilities') {
        return { ok: true, json: async () => ({ capabilities: {} }) } as Response
      }
      if (url === '/agent/runs/stream') {
        return ndjsonResponse([{
          type: 'response.completed',
          run_id: 'run-test',
          sequence: 1,
          data: {
            response: {
              success: false,
              message: 'The previous option expired. Continue with the latest card.',
              error: 'interaction_expired',
              data: {
                interaction: replacement,
                conversation: {
                  conversation_id: 'conv-smart-chat',
                  active_goal: '',
                  action: '',
                  status: 'idle',
                  state_version: 4,
                  selected_resources: {},
                },
              },
            },
          },
        }])
      }
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetcher)

    const wrapper = mount(SmartChatPage)
    await flushPromises()
    await wrapper.get('[data-interaction-option="ask"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-interaction-option="ask"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-interaction-option="refund-table"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('The previous option expired')
  })
})
