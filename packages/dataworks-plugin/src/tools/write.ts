import { tool } from "@opencode-ai/plugin"
import { client, ControlPlaneError } from "../client.js"
import { askDwWrite, writeArgsHash, WritePermissionDeniedError } from "../permission.js"

function operationTarget(parts: Array<string | number | undefined | null>): string {
  return parts.filter((p) => p !== undefined && p !== null && String(p).length > 0).join(":")
}

function formatWriteResult(toolName: string, data: unknown): { title: string; output: string; metadata: Record<string, unknown> } {
  if (data == null) {
    return { title: toolName, output: "queued", metadata: { tool: toolName } }
  }
  if (typeof data === "string") {
    return { title: toolName, output: data, metadata: { tool: toolName } }
  }
  const status =
    data && typeof data === "object" && "status" in data
      ? String((data as { status: unknown }).status)
      : "ok"
  // Never return raw upstream credential material — only a short status line.
  return {
    title: toolName,
    output: status,
    metadata: { tool: toolName, status },
  }
}

async function runWriteTool(
  toolName: "dw_rerun_job" | "dw_trigger_supplement" | "dw_pause_schedule" | "dw_alert_silence",
  args: Readonly<Record<string, unknown>> & { connectionID: string },
  ctx: Parameters<typeof askDwWrite>[0],
  target: string,
) {
  const cp = client(ctx)
  const argsHash = writeArgsHash(args)

  // Gate 1: connection must have writes enabled — deny before ticket / ask when known.
  const enabled = await cp.isWriteEnabled(args.connectionID, ctx.abort).catch(() => null)
  if (enabled === false) {
    throw new WritePermissionDeniedError("write_disabled", "write_disabled")
  }

  // Gate 2: PermissionV1 confirmation (emits permission.asked with permission="dw_write")
  let asked: Awaited<ReturnType<typeof askDwWrite>>
  try {
    asked = await askDwWrite(ctx, {
      connectionID: args.connectionID,
      operationTarget: target,
      tool: toolName,
      args,
    })
  } catch (error) {
    // Reject reply → record denied audit (errorCode=rejected), no ticket / no execute.
    await cp.recordWriteRejected(
      {
        connectionID: args.connectionID,
        tool: toolName,
        argsHash,
        sessionID: ctx.sessionID,
      },
      ctx.abort,
    ).catch(() => undefined)
    throw new WritePermissionDeniedError("rejected", error instanceof Error ? error.message : "rejected")
  }

  if (!asked.reason.trim()) {
    // Empty reason must not reach ticket issuance as a successful execute.
    // Surface as 400-equivalent for the integration harness / web dock.
    const err = new WritePermissionDeniedError("reason_required", "reason_required")
    ;(err as unknown as { status: number }).status = 400
    throw err
  }

  let ticket: string
  try {
    ticket = await cp.issueWriteTicket(
      {
        connectionID: args.connectionID,
        tool: toolName,
        argsHash,
        reason: asked.reason,
        sessionID: ctx.sessionID,
      },
      ctx.abort,
    )
  } catch (error) {
    if (error instanceof ControlPlaneError && error.message === "write_disabled") {
      throw new WritePermissionDeniedError("write_disabled", "write_disabled")
    }
    if (error instanceof ControlPlaneError && (error.message === "reason_required" || error.status === 400)) {
      const err = new WritePermissionDeniedError("reason_required", "reason_required")
      ;(err as unknown as { status: number }).status = 400
      throw err
    }
    throw error
  }

  const data = await cp.executeWrite(toolName, args, ticket, ctx.sessionID, ctx.abort)
  return formatWriteResult(toolName, data)
}

export const dw_rerun_job = tool({
  description: "Rerun a DataWorks job instance. Requires write permission and a one-time ticket.",
  args: {
    connectionID: tool.schema.string().describe("Configured DataConnection ID"),
    projectID: tool.schema.number().int().describe("DataWorks project ID"),
    instanceID: tool.schema.number().int().describe("Job instance ID to rerun"),
  },
  async execute(args, ctx) {
    return runWriteTool(
      "dw_rerun_job",
      args,
      ctx,
      operationTarget([args.projectID, args.instanceID]),
    )
  },
})

export const dw_trigger_supplement = tool({
  description: "Trigger a DataWorks data-backfill (supplement) job. Requires write permission and a one-time ticket.",
  args: {
    connectionID: tool.schema.string().describe("Configured DataConnection ID"),
    projectID: tool.schema.number().int().describe("DataWorks project ID"),
    nodeID: tool.schema.number().int().describe("Node ID to supplement"),
    bizDate: tool.schema.string().describe("Business date (YYYY-MM-DD)"),
  },
  async execute(args, ctx) {
    return runWriteTool(
      "dw_trigger_supplement",
      args,
      ctx,
      operationTarget([args.projectID, args.nodeID, args.bizDate]),
    )
  },
})

export const dw_pause_schedule = tool({
  description: "Pause or resume a DataWorks schedule. Requires write permission and a one-time ticket.",
  args: {
    connectionID: tool.schema.string().describe("Configured DataConnection ID"),
    projectID: tool.schema.number().int().describe("DataWorks project ID"),
    scheduleID: tool.schema.number().int().describe("Schedule ID"),
    paused: tool.schema.boolean().describe("true to pause, false to resume"),
  },
  async execute(args, ctx) {
    return runWriteTool(
      "dw_pause_schedule",
      args,
      ctx,
      operationTarget([args.projectID, args.scheduleID, args.paused ? "pause" : "resume"]),
    )
  },
})

export const dw_alert_silence = tool({
  description: "Silence a DataWorks alert. Requires write permission and a one-time ticket.",
  args: {
    connectionID: tool.schema.string().describe("Configured DataConnection ID"),
    alertID: tool.schema.string().describe("Alert ID"),
    durationMinutes: tool.schema.number().int().min(1).max(7 * 24 * 60).default(60),
  },
  async execute(args, ctx) {
    return runWriteTool(
      "dw_alert_silence",
      args,
      ctx,
      operationTarget([args.alertID, args.durationMinutes]),
    )
  },
})
