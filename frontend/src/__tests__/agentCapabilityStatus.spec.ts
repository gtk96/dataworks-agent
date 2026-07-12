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
  }

  it('does not report an expired cookie as online', () => {
    const badges = buildCapabilityBadges({ ...base, cookie_health: 'expired' })
    expect(badges.find((item) => item.label.startsWith('Cookie'))).toEqual({ label: 'Cookie(过期)', online: false })
    expect(badges.filter((item) => item.online)).toHaveLength(5)
  })

  it.each(['healthy', 'warning'])('accepts %s cookie health as usable', (cookie_health) => {
    const badges = buildCapabilityBadges({ ...base, cookie_health })
    expect(badges.find((item) => item.label === 'Cookie')).toEqual({ label: 'Cookie', online: true })
    expect(badges.filter((item) => item.online)).toHaveLength(6)
  })

  it('shows partial degradation while keeping the Cookie fallback usable', () => {
    const badges = buildCapabilityBadges({ ...base, cookie_health: 'degraded' })
    expect(badges.find((item) => item.label.startsWith('Cookie'))).toEqual({ label: 'Cookie(部分降级)', online: true })
    expect(badges.filter((item) => item.online)).toHaveLength(6)
  })
})
