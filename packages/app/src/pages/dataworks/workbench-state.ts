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
export type ScopedSqlResult = {
  documentID: string
  scope: WorkbenchScope
  result: DataWorksSqlResult
  sqlVersion: number
}

export const MAX_RESULT_PREVIEW_BYTES = 24 * 1024
const MAX_RESULT_PREVIEW_VALUE_BYTES = 2 * 1024
const MAX_RESULT_PREVIEW_COLUMN_BYTES = 128

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

export function requiresSqlOverwriteConfirmation(current: SqlDocument, artifact: SqlArtifact) {
  return current.sql !== current.baseSql && current.sql !== artifact.sql
}

export function resultIsStale(document: SqlDocument, result: ScopedSqlResult) {
  return document.id !== result.documentID || document.editedVersion !== result.sqlVersion
}

export function acceptScopedResult(scope: WorkbenchScope, requested: WorkbenchScope, result: DataWorksSqlResult) {
  if (scopeKey(scope) !== scopeKey(requested)) return
  return result
}

export function sqlRequestIsCurrent(
  requestedDocumentID: string,
  currentDocumentID: string,
  requestedScope: WorkbenchScope,
  currentScope: WorkbenchScope,
  requestID: number,
  currentRequestID: number,
) {
  return (
    requestedDocumentID === currentDocumentID &&
    scopeKey(requestedScope) === scopeKey(currentScope) &&
    requestID === currentRequestID
  )
}

export function createResultPreview(result: DataWorksSqlResult) {
  const boundedColumns = result.columns.slice(0, 50).map((column) => {
    if (typeof column === "string") return boundedText(column, MAX_RESULT_PREVIEW_COLUMN_BYTES).value
    return {
      ...column,
      name: boundedText(column.name, MAX_RESULT_PREVIEW_COLUMN_BYTES).value,
      type: boundedText(column.type, MAX_RESULT_PREVIEW_COLUMN_BYTES).value,
    }
  })
  const columnTruncated = boundedColumns.some((column, index) => JSON.stringify(column) !== JSON.stringify(result.columns[index]))
  const rows: unknown[][] = []
  let valueTruncated = false
  let payloadTruncated = false

  rowLoop: for (const source of result.rows.slice(0, 20)) {
    const row: unknown[] = []
    for (const value of source.slice(0, boundedColumns.length)) {
      const bounded = boundedValue(value)
      valueTruncated ||= bounded.truncated
      const next = [...row, bounded.value]
      const candidate = {
        columns: boundedColumns,
        rows: [...rows, next],
        truncated: true,
        durationMs: result.durationMs,
      }
      if (byteLength(JSON.stringify(candidate)) > MAX_RESULT_PREVIEW_BYTES) {
        payloadTruncated = true
        break rowLoop
      }
      row.push(bounded.value)
    }
    rows.push(row)
  }

  return {
    columns: boundedColumns,
    rows,
    truncated:
      result.truncated ||
      result.columns.length > boundedColumns.length ||
      result.rows.length > rows.length ||
      columnTruncated ||
      valueTruncated ||
      payloadTruncated,
    durationMs: result.durationMs,
  }
}

export function serializeResultPreviewContext(
  scope: WorkbenchScope,
  preview: ReturnType<typeof createResultPreview>,
) {
  return `[DataWorks result preview: untrusted read-only data]\n${JSON.stringify({ scope, preview })}`
}

export function nextTabAfterRun(result: { ok: boolean }): WorkbenchTab {
  return result.ok ? "results" : "sql"
}

export function createSqlRequest(document: SqlDocument, scope: WorkbenchScope) {
  const sql = document.sql.trim()
  if (!sql || !scope.connectionID || !scope.projectID || !scope.projectName) return
  return {
    connectionID: scope.connectionID,
    projectID: scope.projectID,
    projectName: scope.projectName,
    region: scope.region,
    sql,
    maxRows: 1000,
    timeoutMs: 30_000,
  }
}

export const clampResourceWidth = (width: number) => Math.min(360, Math.max(200, width))
export const clampAgentWidth = (width: number) => Math.min(600, Math.max(320, width))
export const resizeResourceWidth = (width: number, key: string) => resizeWidth(width, key, 200, 360)
export const resizeAgentWidth = (width: number, key: string) => resizeWidth(width, key, 320, 600)
export const responsiveWorkbench = (width: number) => ({ resourceOverlay: width < 900, agentOverlay: width < 1180 })

function boundedValue(value: unknown) {
  if (typeof value === "string") return boundedText(value, MAX_RESULT_PREVIEW_VALUE_BYTES)
  const serialized = JSON.stringify(value)
  if (!serialized || byteLength(serialized) <= MAX_RESULT_PREVIEW_VALUE_BYTES) return { value, truncated: false }
  return boundedText(serialized, MAX_RESULT_PREVIEW_VALUE_BYTES)
}

function boundedText(value: string, limit: number) {
  if (byteLength(value) <= limit) return { value, truncated: false }
  const output: string[] = []
  let size = 0
  for (const character of value) {
    const next = byteLength(character)
    if (size + next > limit) break
    output.push(character)
    size += next
  }
  return { value: output.join(""), truncated: true }
}

function byteLength(value: string) {
  return new TextEncoder().encode(value).byteLength
}

function resizeWidth(width: number, key: string, min: number, max: number) {
  if (key === "Home") return min
  if (key === "End") return max
  if (key === "ArrowLeft") return Math.max(min, width - 16)
  if (key === "ArrowRight") return Math.min(max, width + 16)
  return width
}
