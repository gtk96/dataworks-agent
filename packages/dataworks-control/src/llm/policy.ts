import type { LlmConnection } from "@dataworks-agent/core"

const PRIVATE_IP_PATTERNS = [
  /^10\./,
  /^172\.(1[6-9]|2[0-9]|3[0-1])\./,
  /^192\.168\./,
  /^127\./,
  /^localhost$/i,
  /^::1$/,
  /^0\.0\.0\.0$/,
]

const BLOCKED_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1"])

export function isPrivateHost(hostname: string): boolean {
  if (BLOCKED_HOSTS.has(hostname.toLowerCase())) return true
  for (const pattern of PRIVATE_IP_PATTERNS) {
    if (pattern.test(hostname)) return true
  }
  return false
}

export function validateUpstreamRedirect(upstreamUrl: string, connection: LlmConnection.Info): {
  allowed: boolean
  reason?: string
} {
  let url: URL
  try {
    url = new URL(upstreamUrl)
  } catch {
    return { allowed: false, reason: "invalid_url" }
  }

  // Block private IPs and localhost
  if (isPrivateHost(url.hostname)) {
    return { allowed: false, reason: "private_ip_blocked" }
  }

  // Block non-HTTPS
  if (url.protocol !== "https:") {
    return { allowed: false, reason: "non_https_blocked" }
  }

  // Only allow redirects to the configured upstream_origin host
  // (upstream_origin is server-side config, never from worker request)
  let allowedOrigin: URL
  try {
    allowedOrigin = new URL(connection.upstream_origin)
  } catch {
    return { allowed: false, reason: "invalid_connection_origin" }
  }
  if (url.hostname !== allowedOrigin.hostname) {
    return { allowed: false, reason: "host_not_allowlisted" }
  }

  return { allowed: true }
}

export function validateModel(model: string, connection: LlmConnection.Info): boolean {
  const allowed = connection.allowed_models
  if (allowed.length === 0) return true // No restriction
  return allowed.includes(model)
}

export function validateContextPolicy(
  contextType: string | null,
  connection: LlmConnection.Info
): { allowed: boolean; reason?: string } {
  if (contextType === "automatic_full_file") {
    if (connection.data_classification_allowlist === "prompt_only") {
      return { allowed: false, reason: "prompt_only_blocks_full_file_context" }
    }
  }
  return { allowed: true }
}

export function isUserContextApproved(headers: Headers): boolean {
  return headers.get("x-dwa-context-approval") === "approved"
}
