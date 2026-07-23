import { createHash } from "crypto"
import type { ToolContext } from "@opencode-ai/plugin"
import { hashAuditArgs } from "@dataworks-agent/core"

export type WriteToolName =
  | "dw_rerun_job"
  | "dw_trigger_supplement"
  | "dw_pause_schedule"
  | "dw_alert_silence"

export interface WritePermissionMeta {
  readonly tool: WriteToolName
  readonly argsHash: string
  readonly connectionID: string
  readonly operationTarget: string
}

export interface WriteAskResult {
  readonly reason: string
  readonly reply: "once" | "always" | "reject"
}

/**
 * Canonical args hash for ticket issuance / audit (stable JSON → sha256).
 */
export function writeArgsHash(args: unknown): string {
  return hashAuditArgs(args)
}

/**
 * SHA-256 helper used only when a lightweight fingerprint is needed for metadata
 * without the audit canonicalization rules.
 */
export function sha256Hex(value: string): string {
  return createHash("sha256").update(value).digest("hex")
}

/**
 * Ask the user for dw_write permission. Always passes `always: []` so approvals
 * cannot permanently auto-allow write tools.
 *
 * The Web app permission dock captures a reason on approve and places it on the
 * permission reply as `message`. Plugin `ctx.ask` resolves on approve; when the
 * host cannot surface the reply body, callers may pass `reason` via
 * `ctx.extra.dwWriteReason` (test harness / bridge).
 */
export async function askDwWrite(
  ctx: ToolContext,
  input: {
    connectionID: string
    operationTarget: string
    tool: WriteToolName
    args: Readonly<Record<string, unknown>>
  },
): Promise<WriteAskResult> {
  const argsHash = writeArgsHash(input.args)
  const metadata: WritePermissionMeta & Record<string, unknown> = {
    tool: input.tool,
    argsHash,
    connectionID: input.connectionID,
    operationTarget: input.operationTarget,
  }

  await ctx.ask({
    permission: "dw_write",
    patterns: [input.connectionID, input.operationTarget],
    always: [],
    metadata,
  })

  const extra = (ctx as ToolContext & { extra?: Record<string, unknown> }).extra
  const reasonFromExtra =
    typeof extra?.dwWriteReason === "string"
      ? extra.dwWriteReason
      : typeof extra?.reason === "string"
        ? extra.reason
        : ""

  // Hosts that surface the reply message as a property on the context.
  const reasonFromCtx =
    typeof (ctx as unknown as { writeReason?: unknown }).writeReason === "string"
      ? (ctx as unknown as { writeReason: string }).writeReason
      : ""

  const reason = (reasonFromExtra || reasonFromCtx).trim()
  return { reason, reply: "once" }
}

export class WritePermissionDeniedError extends Error {
  readonly code: "write_disabled" | "rejected" | "reason_required" | "ticket_failed"

  constructor(code: WritePermissionDeniedError["code"], message?: string) {
    super(message ?? code)
    this.name = "WritePermissionDeniedError"
    this.code = code
  }
}
