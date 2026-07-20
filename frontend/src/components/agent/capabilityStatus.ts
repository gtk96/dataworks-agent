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

function isObservedState(value: unknown): value is { online: boolean } {
  return typeof value === 'object' && value !== null && typeof (value as { online?: unknown }).online === 'boolean'
}

function isOnline(value: unknown): boolean {
  return isObservedState(value) ? value.online : Boolean(value)
}

export function countOnlineCapabilities(capabilities: Record<string, unknown>): number {
  return Object.values(capabilities).filter(value => isObservedState(value) && value.online).length
}

export function buildCapabilityBadges(capabilities: Record<string, unknown>): CapabilityBadge[] {
  const runtime = capabilities.agent_runtime as Record<string, unknown> | undefined
  const official = capabilities.official_mcp as Record<string, unknown> | undefined
  const cookieHealth = String(capabilities.cookie_health ?? '').toLowerCase()
  const cookieValue = capabilities.cookie_bff
  const observedCookie = isObservedState(cookieValue)
  const cookieOnline = observedCookie
    ? cookieValue.online
    : Boolean(cookieValue) && COOKIE_USABLE.has(cookieHealth)
  const cookieSuffix = cookieHealth === 'degraded' ? COOKIE_HEALTH_LABELS.degraded : cookieOnline ? '' : COOKIE_HEALTH_LABELS[cookieHealth]
  const tableSearchOnline = isOnline(capabilities.table_search ?? capabilities.cookie_bff)
  const idaQueryOnline = isOnline(capabilities.ida_query ?? capabilities.cookie_bff)

  return [
    { label: runtime?.framework ? String(runtime.framework) : 'Agent Runtime', online: isOnline(runtime) || Boolean(runtime?.ready) },
    { label: 'AK/SK', online: isOnline(capabilities.ak_sk) },
    { label: 'OpenAPI', online: isOnline(capabilities.openapi) },
    { label: 'MaxCompute', online: isOnline(capabilities.maxcompute) },
    { label: cookieSuffix ? `Cookie(${cookieSuffix})` : 'Cookie', online: cookieOnline },
    { label: '9222', online: isOnline(capabilities.cdp_9222) },
    { label: '官方 MCP', online: isOnline(official) || Boolean(official?.connected) },
    { label: '中文搜表', online: tableSearchOnline && cookieOnline },
    { label: 'IDA 问数', online: idaQueryOnline && cookieOnline },
  ]
}
