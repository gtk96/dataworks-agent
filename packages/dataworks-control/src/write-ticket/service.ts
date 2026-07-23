import { createHash, randomBytes } from "crypto"
import type { UserID } from "@dataworks-agent/core"
import type { Database } from "../database"

const TICKET_TTL_MS = 60_000
const WRITE_TOOLS = new Set([
  "dw_rerun_job",
  "dw_trigger_supplement",
  "dw_pause_schedule",
  "dw_alert_silence",
])

export interface WriteTicketIssueInput {
  readonly userID: UserID
  readonly connectionID: string
  readonly sessionID?: string | null
  readonly tool: string
  readonly argsHash: string
  readonly reason: string
}

export interface IssuedWriteTicket {
  readonly ticket: string
  readonly timeExpires: number
}

export interface WriteTicketConsumeInput {
  readonly ticket: string
  readonly userID: UserID
  readonly connectionID: string
  readonly sessionID?: string | null
  readonly tool: string
  readonly argsHash: string
}

export interface ConsumedWriteTicket {
  readonly userID: UserID
  readonly connectionID: string
  readonly sessionID: string | null
  readonly tool: string
  readonly argsHash: string
  readonly reason: string
  readonly timeExpires: number
  readonly timeConsumed: number
}

interface TicketRow {
  user_id: UserID
  connection_id: string
  session_id: string | null
  tool: string
  args_hash: string
  reason: string
  time_expires: number
  time_consumed: number
}

export class WriteTicketService {
  constructor(private readonly db: Database) {}

  issue(input: WriteTicketIssueInput): IssuedWriteTicket {
    if (!WRITE_TOOLS.has(input.tool)) throw new WriteTicketDeniedError("tool_not_write_enabled")
    if (!/^[a-f0-9]{64}$/.test(input.argsHash)) throw new WriteTicketDeniedError("invalid_args_hash")
    if (!input.reason.trim()) throw new WriteTicketDeniedError("reason_required")
    const connection = this.db.get<{ write_enabled: number }>(
      "SELECT write_enabled FROM dwa_data_connection WHERE id = ? AND user_id = ?",
      [input.connectionID, input.userID],
    )
    if (!connection?.write_enabled) throw new WriteTicketDeniedError("write_disabled")

    const ticket = randomBytes(32).toString("base64url")
    const timeExpires = Date.now() + TICKET_TTL_MS
    this.db.run(
      `INSERT INTO dwa_write_ticket (
        token_hash, user_id, connection_id, session_id, tool, args_hash, reason, time_expires, time_consumed
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)`,
      [
        hashTicket(ticket),
        input.userID,
        input.connectionID,
        input.sessionID ?? null,
        input.tool,
        input.argsHash,
        input.reason.trim(),
        timeExpires,
      ],
    )
    return { ticket, timeExpires }
  }

  consume(input: WriteTicketConsumeInput): ConsumedWriteTicket | null {
    const consumed: { row: TicketRow | undefined } = { row: undefined }
    const timeConsumed = Date.now()
    this.db.transaction(() => {
      consumed.row = this.db.get<TicketRow>(
        `UPDATE dwa_write_ticket
         SET time_consumed = ?
         WHERE token_hash = ?
           AND user_id = ?
           AND connection_id = ?
           AND tool = ?
           AND args_hash = ?
           AND ((session_id IS NULL AND ? IS NULL) OR session_id = ?)
           AND time_consumed IS NULL
           AND time_expires >= ?
         RETURNING user_id, connection_id, session_id, tool, args_hash, reason, time_expires, time_consumed`,
        [
          timeConsumed,
          hashTicket(input.ticket),
          input.userID,
          input.connectionID,
          input.tool,
          input.argsHash,
          input.sessionID ?? null,
          input.sessionID ?? null,
          timeConsumed,
        ],
      )
    })
    if (!consumed.row) return null
    return {
      userID: consumed.row.user_id,
      connectionID: consumed.row.connection_id,
      sessionID: consumed.row.session_id,
      tool: consumed.row.tool,
      argsHash: consumed.row.args_hash,
      reason: consumed.row.reason,
      timeExpires: consumed.row.time_expires,
      timeConsumed: consumed.row.time_consumed,
    }
  }
}

export class WriteTicketDeniedError extends Error {
  constructor(readonly code: "tool_not_write_enabled" | "invalid_args_hash" | "reason_required" | "write_disabled") {
    super(code)
    this.name = "WriteTicketDeniedError"
  }
}

function hashTicket(ticket: string) {
  return createHash("sha256").update(ticket).digest("hex")
}
