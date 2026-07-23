import { Redacted } from "effect"
import type { Database } from "../database"
import {
  insertDataConnection,
  listDataConnectionsByUser,
  queryDataConnection,
  deleteDataConnection,
} from "../database"
import type { SecretStore } from "../secret/store"
import type { UserID } from "@dataworks-agent/core"
import { maskAccessKeyId } from "@dataworks-agent/core/src/data-connection"

export interface DataConnectionInfo {
  readonly id: string
  readonly userId: string
  readonly name: string
  readonly region: string
  readonly accessKeyDisplay: string
  readonly writeEnabled: boolean
  readonly timeCreated: number
  readonly timeUpdated: number
}

export interface DataConnectionCreateRequest {
  readonly user_id: UserID
  readonly name: string
  readonly region: string
  readonly access_key_id: string
  readonly access_key_secret: string
  readonly write_enabled: boolean
}

export class RedactedCredential {
  constructor(
    readonly accessKeyId: Redacted.Redacted<string>,
    readonly accessKeySecret: Redacted.Redacted<string>,
  ) {}
}

function toInfo(row: {
  id: string
  user_id: string
  name: string
  region: string
  access_key_display: string
  write_enabled: boolean
  time_created: number
  time_updated: number
}): DataConnectionInfo {
  return {
    id: row.id,
    userId: row.user_id,
    name: row.name,
    region: row.region,
    accessKeyDisplay: row.access_key_display,
    writeEnabled: row.write_enabled,
    timeCreated: row.time_created,
    timeUpdated: row.time_updated,
  }
}

export async function createDataConnection(
  db: Database,
  secrets: SecretStore,
  req: DataConnectionCreateRequest,
): Promise<DataConnectionInfo> {
  const now = Date.now()
  const id = crypto.randomUUID()
  const secretRef = `data-connection:${id}`

  await secrets.put(secretRef, {
    accessKeyId: req.access_key_id,
    accessKeySecret: req.access_key_secret,
  })

  insertDataConnection(db, {
    id,
    user_id: req.user_id,
    name: req.name,
    region: req.region,
    access_key_id: req.access_key_id,
    access_key_display: maskAccessKeyId(req.access_key_id),
    secret_ref: secretRef,
    write_enabled: req.write_enabled,
    time_created: now,
    time_updated: now,
  })

  return toInfo({
    id,
    user_id: req.user_id,
    name: req.name,
    region: req.region,
    access_key_display: maskAccessKeyId(req.access_key_id),
    write_enabled: req.write_enabled,
    time_created: now,
    time_updated: now,
  })
}

export function listDataConnections(db: Database, userId: UserID): DataConnectionInfo[] {
  return listDataConnectionsByUser(db, userId).map(toInfo)
}

export function getDataConnection(
  db: Database,
  id: string,
  userId: UserID,
): DataConnectionInfo | undefined {
  const row = queryDataConnection(db, id, userId)
  if (!row) return undefined
  return toInfo(row)
}

export async function removeDataConnection(
  db: Database,
  secrets: SecretStore,
  id: string,
  userId: UserID,
): Promise<boolean> {
  const row = queryDataConnection(db, id, userId)
  if (!row) return false
  await secrets.delete(row.secret_ref)
  deleteDataConnection(db, id, userId)
  return true
}

export async function resolveCredential(
  db: Database,
  secrets: SecretStore,
  userId: UserID,
  connectionId: string,
): Promise<RedactedCredential | null> {
  const row = queryDataConnection(db, connectionId, userId)
  if (!row) return null
  const payload = await secrets.ref(row.secret_ref)
  if (!payload) return null
  return new RedactedCredential(
    Redacted.make(payload.accessKeyId),
    Redacted.make(payload.accessKeySecret),
  )
}
