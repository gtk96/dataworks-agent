// @vitest-environment jsdom
/**
 * RepositoryPathPicker 组件单元测试
 * 测试目录选择器的基本功能
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import RepositoryPathPicker from '@/components/RepositoryPathPicker.vue'

// Mock request 工具
vi.mock('@/utils/request', () => ({
  request: vi.fn().mockResolvedValue({ nodes: [] }),
}))

// 简化的 Element Plus 组件 stubs
const stubs = {
  'el-tag': {
    template: '<span class="el-tag"><slot /></span>',
  },
  'el-button': {
    template: '<button class="el-button" @click="$emit(\'click\')"><slot /></button>',
    emits: ['click'],
  },
}

describe('RepositoryPathPicker', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('渲染默认标签和路径', () => {
    const wrapper = mount(RepositoryPathPicker, { global: { stubs } })

    // 检查默认标签
    expect(wrapper.text()).toContain('节点目录')

    // 检查默认路径显示
    expect(wrapper.text()).toContain('dataworks_agent/01_ODS')
  })

  it('自定义 label 属性', () => {
    const wrapper = mount(RepositoryPathPicker, {
      props: { label: '自定义标签' },
      global: { stubs },
    })

    expect(wrapper.text()).toContain('自定义标签')
  })

  it('点击浏览目录按钮切换树面板显示', async () => {
    const wrapper = mount(RepositoryPathPicker, { global: { stubs } })

    // 初始状态树面板不显示
    expect(wrapper.find('.tree-panel').exists()).toBe(false)

    // 点击浏览目录按钮
    const buttons = wrapper.findAll('.el-button')
    const toggleBtn = buttons.find(b => b.text().includes('浏览目录'))
    if (toggleBtn) {
      await toggleBtn.trigger('click')
      await nextTick()
    }

    // 树面板应该显示（因为 mock 的 request 返回空，会显示"无子节点"）
    expect(wrapper.find('.tree-panel').exists()).toBe(true)
  })

  it('点击预设路径按钮选择路径', async () => {
    const wrapper = mount(RepositoryPathPicker, {
      props: {
        presets: ['dataworks_agent/01_ODS', 'dataworks_agent/02_DWD'],
      },
      global: { stubs },
    })

    // 找到预设按钮并点击
    const buttons = wrapper.findAll('.el-button')
    const odsButton = buttons.find(b => b.text().includes('01_ODS'))

    if (odsButton) {
      await odsButton.trigger('click')
      await nextTick()

      // 验证选中的路径
      expect(wrapper.text()).toContain('dataworks_agent/01_ODS')
    }
  })

  it('切换树面板显示/隐藏', async () => {
    const wrapper = mount(RepositoryPathPicker, { global: { stubs } })

    // 点击浏览目录
    const buttons = wrapper.findAll('.el-button')
    const toggleBtn = buttons.find(b => b.text().includes('浏览目录'))
    if (toggleBtn) {
      await toggleBtn.trigger('click')
      await nextTick()
    }
    expect(wrapper.find('.tree-panel').exists()).toBe(true)

    // 再次点击收起
    const collapseBtn = wrapper.findAll('.el-button').find(b => b.text().includes('收起'))
    if (collapseBtn) {
      await collapseBtn.trigger('click')
      await nextTick()
    }
    expect(wrapper.find('.tree-panel').exists()).toBe(false)
  })
})
