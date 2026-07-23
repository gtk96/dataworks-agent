import type { Database } from "../database"
import type { LlmConnection, AuthStrategy, DataClassificationLevel } from "@dataworks-agent/core"
import { LlmConnectionTable } from "../schema"
import { eq, and } from "drizzle-orm"
import { randomUUID } from "crypto"

export class LlmConnectionRepo {
  constructor(private db: Database) {}

  create(input: LlmConnection.CreateInput): LlmConnection.Info {
    const now = Date.now()
    const id = randomUUID()
    this.db._.insert(LlmConnectionTable).values({
      id,
      user_id: input.user_id as any,
      provider_id: input.provider_id,
      name: input.name,
      upstream_origin: input.upstream_origin,
      auth_strategy: input.auth_strategy,
      secret_ref: input.secret_ref,
      enabled: input.enabled ?? true,
      allowed_models: JSON.stringify(input.allowed_models),
      data_classification_allowlist: input.data_classification_allowlist,
      time_created: now,
      time_updated: now,
    }).run()
    return this.findById(id)!
  }

  findById(id: string): LlmConnection.Info | null {
    const row = this.db._
      .select()
      .from(LlmConnectionTable)
      .where(eq(LlmConnectionTable.id, id))
      .get()
    if (!row) return null
    return this.rowToInfo(row)
  }

  findByUserId(userId: string): LlmConnection.Info[] {
    const rows = this.db._
      .select()
      .from(LlmConnectionTable)
      .where(eq(LlmConnectionTable.user_id, userId as any))
      .all()
    return rows.map(r => this.rowToInfo(r))
  }

  findEnabledByUserId(userId: string): LlmConnection.Info[] {
    const rows = this.db._
      .select()
      .from(LlmConnectionTable)
      .where(and(
        eq(LlmConnectionTable.user_id, userId as any),
        eq(LlmConnectionTable.enabled, true),
      ))
      .all()
    return rows.map(r => this.rowToInfo(r))
  }

  update(id: string, input: LlmConnection.UpdateInput): LlmConnection.Info | null {
    const existing = this.findById(id)
    if (!existing) return null
    const updates: Record<string, any> = { time_updated: Date.now() }
    if (input.name !== undefined) updates.name = input.name
    if (input.upstream_origin !== undefined) updates.upstream_origin = input.upstream_origin
    if (input.auth_strategy !== undefined) updates.auth_strategy = input.auth_strategy
    if (input.secret_ref !== undefined) updates.secret_ref = input.secret_ref
    if (input.enabled !== undefined) updates.enabled = input.enabled
    if (input.allowed_models !== undefined) updates.allowed_models = JSON.stringify(input.allowed_models)
    if (input.data_classification_allowlist !== undefined) updates.data_classification_allowlist = input.data_classification_allowlist
    this.db._
      .update(LlmConnectionTable)
      .set(updates)
      .where(eq(LlmConnectionTable.id, id))
      .run()
    return this.findById(id)
  }

  delete(id: string): boolean {
    const before = this.findById(id)
    if (!before) return false
    this.db._
      .delete(LlmConnectionTable)
      .where(eq(LlmConnectionTable.id, id))
      .run()
    return true
  }

  private rowToInfo(row: Record<string, any>): LlmConnection.Info {
    return {
      id: row.id,
      user_id: row.user_id,
      provider_id: row.provider_id,
      name: row.name,
      upstream_origin: row.upstream_origin,
      auth_strategy: row.auth_strategy as AuthStrategy,
      secret_ref: row.secret_ref,
      enabled: Boolean(row.enabled),
      allowed_models: JSON.parse(row.allowed_models ?? "[]"),
      data_classification_allowlist: row.data_classification_allowlist as DataClassificationLevel,
      time_created: row.time_created,
      time_updated: row.time_updated,
    }
  }
}
