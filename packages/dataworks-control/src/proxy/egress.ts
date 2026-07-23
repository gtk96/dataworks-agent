export interface EgressDecision {
  allowed: boolean
  reason?: string
}

function parseIPv4(host: string): number[] | null {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host)
  if (!m) return null
  const parts = m.slice(1).map((p) => Number(p))
  if (parts.some((p) => Number.isNaN(p) || p < 0 || p > 255)) return null
  return parts
}

function isPrivateIPv4(parts: number[]): boolean {
  const a = parts[0] ?? 0
  const b = parts[1] ?? 0
  if (a === 10) return true
  if (a === 127) return true
  if (a === 169 && b === 254) return true
  if (a === 172 && b >= 16 && b <= 31) return true
  if (a === 192 && b === 168) return true
  if (a === 0) return true
  if (a >= 224) return true
  return false
}

export function checkEgressPolicy(
  url: string,
  allow: Set<string> | undefined,
): EgressDecision {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return { allowed: false, reason: "invalid_url" }
  }
  const proto = parsed.protocol.toLowerCase()
  if (proto !== "http:" && proto !== "https:") {
    return { allowed: false, reason: "non_http_scheme" }
  }
  const hostname = parsed.hostname.toLowerCase()
  if (hostname === "localhost") {
    return { allowed: false, reason: "loopback_hostname" }
  }
  const v4 = parseIPv4(hostname)
  if (v4 && isPrivateIPv4(v4)) {
    return { allowed: false, reason: "private_ip" }
  }
  if (allow && allow.has(hostname)) {
    return { allowed: true }
  }
  return { allowed: false, reason: "host_not_allowlisted" }
}
