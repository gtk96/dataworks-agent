import { createHmac, randomBytes, timingSafeEqual } from "crypto"

export interface WorkerTokenScope {
  readonly userID: string
  readonly workerID: string
  readonly expires: number
}

/**
 * Max accepted remaining lifetime for a worker token (clock-skew / long-lived bound).
 * Default worker idle is 900s; process-lifetime tokens use 1h (DEFAULT_WORKER_TOKEN_TTL_MS).
 * Tokens signed with expires farther than this from `now` are rejected to limit stolen-token window.
 */
export const MAX_WORKER_TOKEN_TTL_MS = 3_600_000

/** Default TTL when signing a worker process token at native start (aligned ≥ idle 900s). */
export const DEFAULT_WORKER_TOKEN_TTL_MS = 3_600_000

export function generateWorkerToken(): string {
  return Buffer.from(randomBytes(32)).toString("base64url")
}

export function deriveWorkerTokenSecret(masterKey: Uint8Array): Uint8Array {
  return createHmac("sha256", masterKey).update("dataworks-agent:worker-token:v1").digest()
}

export function signWorkerToken(secret: Uint8Array, scope: WorkerTokenScope): string {
  const payload = Buffer.from(JSON.stringify({
    userID: scope.userID,
    workerID: scope.workerID,
    expires: scope.expires,
  })).toString("base64url")
  return `v1.${payload}.${signature(secret, payload)}`
}

export function verifyWorkerToken(
  secret: Uint8Array,
  token: string,
  expectedWorkerID: string,
  now = Date.now(),
): WorkerTokenScope | null {
  const parts = token.split(".")
  if (parts.length !== 3 || parts[0] !== "v1" || !parts[1] || !parts[2]) return null
  const expected = Buffer.from(signature(secret, parts[1]), "base64url")
  const actual = Buffer.from(parts[2], "base64url")
  if (expected.length !== actual.length || !timingSafeEqual(expected, actual)) return null

  const scope = parseScope(parts[1])
  if (!scope || scope.workerID !== expectedWorkerID || scope.expires <= now) return null
  if (scope.expires > now + MAX_WORKER_TOKEN_TTL_MS) return null
  return scope
}

function signature(secret: Uint8Array, payload: string) {
  return createHmac("sha256", secret).update(`v1.${payload}`).digest("base64url")
}

function parseScope(payload: string): WorkerTokenScope | null {
  return parseWorkerScope(Buffer.from(payload, "base64url").toString("utf8"))
}

function parseWorkerScope(raw: string): WorkerTokenScope | null {
  try {
    const value = JSON.parse(raw) as Partial<WorkerTokenScope>
    if (typeof value.userID !== "string" || !value.userID) return null
    if (typeof value.workerID !== "string" || !value.workerID) return null
    if (typeof value.expires !== "number" || !Number.isFinite(value.expires)) return null
    return { userID: value.userID, workerID: value.workerID, expires: value.expires }
  } catch {
    return null
  }
}
