import { createHash } from "crypto"
import type { UserID } from "./identity"

export type AuditPermission = "read" | "write"
export type AuditOutcome = "success" | "error" | "denied"

export interface AuditRecord {
  readonly id: string
  readonly userID: UserID
  readonly connectionID: string
  readonly sessionID: string | null
  readonly tool: string
  readonly permission: AuditPermission
  readonly argsHash: string
  readonly reason: string | null
  readonly outcome: AuditOutcome
  readonly errorCode: string | null
  readonly durationMs: number
  readonly timeCreated: number
}

export interface AuditAppendInput {
  readonly userID: UserID
  readonly connectionID: string
  readonly sessionID?: string | null
  readonly tool: string
  readonly permission: AuditPermission
  readonly argsHash: string
  readonly reason?: string | null
  readonly outcome: AuditOutcome
  readonly errorCode?: string | null
  readonly durationMs: number
}

export function hashAuditArgs(args: unknown): string {
  return createHash("sha256").update(canonicalJson(args)).digest("hex")
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value)
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("audit arguments must contain finite numbers")
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`
  if (typeof value === "object") {
    return `{${Object.entries(value)
      .filter((entry) => entry[1] !== undefined)
      .sort((left, right) => left[0] < right[0] ? -1 : left[0] > right[0] ? 1 : 0)
      .map((entry) => `${JSON.stringify(entry[0])}:${canonicalJson(entry[1])}`)
      .join(",")}}`
  }
  throw new Error("audit arguments must be JSON serializable")
}
