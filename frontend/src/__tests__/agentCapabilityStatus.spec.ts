import { describe, expect, it } from 'vitest'
import { buildCapabilityBadges } from '@/components/agent/capabilityStatus'

describe('Agent capability status', () => {
  const base = {
    ak_sk: true,
    openapi: true,
    maxcompute: true,
    cookie_bff: true,
    cdp_9222: true,
    official_mcp: { connected: true },
    table_search: true,
    ida_query: true,
  }

  it('shows LangGraph as the primary Agent runtime', () => {
    const badges = buildCapabilityBadges({
      ...base,
      agent_runtime: { framework: 'LangGraph', ready: true },
      cookie_health: 'healthy',
    })
    expect(badges[0]).toEqual({ label: 'LangGraph', online: true })
  })

  it('does not report an expired cookie as online', () => {
    const badges = buildCapabilityBadges({ ...base, cookie_health: 'expired' })
    expect(badges.find((item) => item.label.startsWith('Cookie'))).toEqual({ label: 'Cookie(过期)', online: false })
    // AK/SK OpenAPI MaxCompute 9222 官方MCP = 5; Cookie/搜表/问数 offline
    expect(badges.filter((item) => item.online)).toHaveLength(5)
  })

  it.each(['healthy', 'warning'])('accepts %s cookie health as usable', (cookie_health) => {
    const badges = buildCapabilityBadges({ ...base, cookie_health })
    expect(badges.find((item) => item.label === 'Cookie')).toEqual({ label: 'Cookie', online: true })
    // + Cookie + 中文搜表 + IDA 问数
    expect(badges.filter((item) => item.online)).toHaveLength(8)
  })

  it('shows partial degradation while keeping the Cookie fallback usable', () => {
    const badges = buildCapabilityBadges({ ...base, cookie_health: 'degraded' })
    expect(badges.find((item) => item.label.startsWith('Cookie'))).toEqual({ label: 'Cookie(部分降级)', online: true })
    expect(badges.filter((item) => item.online)).toHaveLength(8)
  })

  it('exposes native Chinese search and IDA query badges', () => {
    const badges = buildCapabilityBadges({ ...base, cookie_health: 'healthy' })
    expect(badges.find((item) => item.label === '中文搜表')).toEqual({ label: '中文搜表', online: true })
    expect(badges.find((item) => item.label === 'IDA 问数')).toEqual({ label: 'IDA 问数', online: true })
  })
})
