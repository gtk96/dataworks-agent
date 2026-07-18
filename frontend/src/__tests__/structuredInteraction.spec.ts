// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MessageBubble from '@/components/agent/MessageBubble.vue'

const interaction = {
  interaction_id: 'int-1',
  type: 'single_select' as const,
  purpose: 'select_table',
  prompt: '请选择目标表',
  options: [
    {
      id: 'table-1',
      label: '订单明细表',
      description: 'DWD · 日分区',
      value: 'giikin_aliyun.tb_dwd_order',
      layer: 'dwd',
    },
  ],
  allow_custom_input: true,
  custom_input_placeholder: '输入其他表名',
  status: 'pending' as const,
  state_version: 3,
}

describe('MessageBubble structured interaction', () => {
  it('emits the server option id and locks after one click', async () => {
    const wrapper = mount(MessageBubble, {
      props: {
        role: 'assistant',
        content: '请选择表',
        interaction,
        activeInteractionId: 'int-1',
      },
    })

    const option = wrapper.get('[data-interaction-option="table-1"]')
    await option.trigger('click')
    await option.trigger('click')

    expect(wrapper.emitted('answer-interaction')).toHaveLength(1)
    expect(wrapper.emitted('answer-interaction')?.[0]?.[0]).toEqual({
      message: '订单明细表',
      answer: {
        interaction_id: 'int-1',
        option_id: 'table-1',
        state_version: 3,
      },
    })
  })

  it('always renders custom input and emits custom text', async () => {
    const wrapper = mount(MessageBubble, {
      props: {
        role: 'assistant',
        content: '请选择表',
        interaction,
        activeInteractionId: 'int-1',
      },
    })

    await wrapper.get('[data-interaction-custom]').setValue('只要退款金额表')
    await wrapper.get('[data-interaction-submit]').trigger('click')

    expect(wrapper.emitted('answer-interaction')?.[0]?.[0]).toEqual({
      message: '只要退款金额表',
      answer: {
        interaction_id: 'int-1',
        custom_text: '只要退款金额表',
        state_version: 3,
      },
    })
  })

  it('keeps expired or inactive interactions visible but disabled', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        role: 'assistant',
        content: '请选择表',
        interaction: { ...interaction, status: 'expired' },
        activeInteractionId: 'int-current',
      },
    })

    expect(wrapper.find('[data-interaction-card]').exists()).toBe(true)
    expect(wrapper.get('[data-interaction-option="table-1"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-interaction-custom]').attributes('disabled')).toBeDefined()
  })

  it('unlocks a choice when the parent restores the pending interaction after failure', async () => {
    const wrapper = mount(MessageBubble, {
      props: {
        role: 'assistant',
        content: '请选择表',
        interaction,
        activeInteractionId: 'int-1',
      },
    })

    await wrapper.get('[data-interaction-option="table-1"]').trigger('click')
    await wrapper.setProps({
      interaction: { ...interaction, status: 'answered' },
      activeInteractionId: null,
    })
    await wrapper.setProps({ interaction, activeInteractionId: 'int-1' })
    await wrapper.get('[data-interaction-option="table-1"]').trigger('click')

    expect(wrapper.emitted('answer-interaction')).toHaveLength(2)
  })
})
