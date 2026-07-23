import { randomUUID } from "crypto"
import type { AuditAppendInput, AuditRecord } from "@dataworks-agent/core"
import type { UserID } from "@dataworks-agent/core"
import type { Database } from "../database"

interface AuditRow {
  id: string
  user_id: UserID
  connection_id: string
  session_id: string | null
  tool: string
  permission: "read" | "write"
  args_hash: string
  reason: string | null
  outcome: "success" | "error" | "denied"
  error_code: string | null
  duration_ms: number
  time_created: number
}

export interface AuditListInput {
  readonly userID: UserID
  readonly connectionID?: string
  readonly limit?: number
}

export class AuditRepo {
  constructor(private readonly db: Database) {}

  append(input: AuditAppendInput): AuditRecord {
    const row: AuditRow = {
      id: randomUUID(),
      user_id: input.userID,
      connection_id: input.connectionID,
      session_id: input.sessionID ?? null,
      tool: input.tool,
      permission: input.permission,
      args_hash: input.argsHash,
      reason: input.reason ?? null,
      outcome: input.outcome,
      error_code: input.errorCode ?? null,
      duration_ms: input.durationMs,
      time_created: Date.now(),
    }
    this.db.run(
      `INSERT INTO dwa_audit (
        id, user_id, connection_id, session_id, tool, permission, args_hash,
        reason, outcome, error_code, duration_ms, time_created
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        row.id,
        row.user_id,
        row.connection_id,
        row.session_id,
        row.tool,
        row.permission,
        row.args_hash,
        row.reason,
        row.outcome,
        row.error_code,
        row.duration_ms,
        row.time_created,
      ],
    )
    return toRecord(row)
  }

  list(input: AuditListInput): AuditRecord[] {
    const limit = Math.max(1, Math.min(input.limit ?? 100, 100))
    const rows = input.connectionID
      ? this.db.all<AuditRow>(
          "SELECT * FROM dwa_audit WHERE user_id = ? AND connection_id = ? ORDER BY time_created DESC, id DESC LIMIT ?",
          [input.userID, input.connectionID, limit],
        )
      : this.db.all<AuditRow>(
          "SELECT * FROM dwa_audit WHERE user_id = ? ORDER BY time_created DESC, id DESC LIMIT ?",
          [input.userID, limit],
        )
    return rows.map(toRecord)
  }
}

function toRecord(row: AuditRow): AuditRecord {
  return {
    id: row.id,
    userID: row.user_id,
    connectionID: row.connection_id,
    sessionID: row.session_id,
    tool: row.tool,
    permission: row.permission,
    argsHash: row.args_hash,
    reason: row.reason,
    outcome: row.outcome,
    errorCode: row.error_code,
    durationMs: row.duration_ms,
    timeCreated: row.time_created,
  }
}
