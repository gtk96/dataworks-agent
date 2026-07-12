export interface CapabilityBadge {
  label: string
  online: boolean
}

const COOKIE_USABLE = new Set(['healthy', 'warning', 'degraded'])
const COOKIE_HEALTH_LABELS: Record<string, string> = {
  expired: '过期',
  critical: '异常',
  degraded: '部分降级',
  missing: '缺失',
  unavailable: '不可用',
}

export function buildCapabilityBadges(capabilities: Record<string, unknown>): CapabilityBadge[] {
  const official = capabilities.official_mcp as Record<string, unknown> | undefined
  const cookieHealth = String(capabilities.cookie_health ?? '').toLowerCase()
  const cookieOnline = Boolean(capabilities.cookie_bff) && COOKIE_USABLE.has(cookieHealth)
  const cookieSuffix = cookieHealth === 'degraded' ? COOKIE_HEALTH_LABELS.degraded : cookieOnline ? '' : COOKIE_HEALTH_LABELS[cookieHealth]

  return [
    { label: 'AK/SK', online: Boolean(capabilities.ak_sk) },
    { label: 'OpenAPI', online: Boolean(capabilities.openapi) },
    { label: 'MaxCompute', online: Boolean(capabilities.maxcompute) },
    { label: cookieSuffix ? `Cookie(${cookieSuffix})` : 'Cookie', online: cookieOnline },
    { label: '9222', online: Boolean(capabilities.cdp_9222) },
    { label: '官方 MCP', online: Boolean(official?.connected) },
  ]
}
