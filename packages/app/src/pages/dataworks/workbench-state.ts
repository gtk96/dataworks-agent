import type { DataWorksSqlResult } from "@/context/dataworks"
import { uuid } from "@/utils/uuid"

export type WorkbenchTab = "plan" | "sql" | "results" | "schema"
export type WorkbenchScope = {
  connectionID?: string
  projectID?: string
  projectName?: string
  region?: string
}
export type SqlArtifact = { sql: string; title?: string; sourceMessageID?: string }
export type SqlDocument = SqlArtifact & {
  id: string
  baseSql: string
  editedVersion: number
  executedVersion?: number
}
export type ScopedSqlResult = { scope: WorkbenchScope; result: DataWorksSqlResult; sqlVersion: number }

export function scopeKey(scope: WorkbenchScope) {
  return [scope.connectionID, scope.projectID, scope.projectName, scope.region].map((value) => value ?? "").join("\n")
}

export function openSqlArtifact(current: SqlDocument | undefined, artifact: SqlArtifact): SqlDocument {
  const dirty = current && current.sql !== current.baseSql
  if (!current || dirty) return { ...artifact, id: uuid(), baseSql: artifact.sql, editedVersion: 0, executedVersion: undefined }
  return {
    ...artifact,
    id: current.id,
    baseSql: artifact.sql,
    editedVersion: current.editedVersion + 1,
  }
}

export function editSqlDocument(document: SqlDocument, sql: string): SqlDocument {
  if (document.sql === sql) return document
  return { ...document, sql, editedVersion: document.editedVersion + 1 }
}

export function acceptScopedResult(scope: WorkbenchScope, requested: WorkbenchScope, result: DataWorksSqlResult) {
  if (scopeKey(scope) !== scopeKey(requested)) return
  return result
}

export function createResultPreview(result: DataWorksSqlResult) {
  const columns = result.columns.slice(0, 50)
  return {
    columns,
    rows: result.rows.slice(0, 20).map((row) => row.slice(0, columns.length)),
    truncated: result.truncated || result.columns.length > columns.length || result.rows.length > 20,
    durationMs: result.durationMs,
  }
}

export const clampResourceWidth = (width: number) => Math.min(360, Math.max(200, width))
export const clampAgentWidth = (width: number) => Math.min(600, Math.max(320, width))
export const responsiveWorkbench = (width: number) => ({ resourceOverlay: width < 960, agentOverlay: width < 960 })
