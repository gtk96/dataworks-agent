export const SQL_ARTIFACT_EVENT = "opencode:sql-artifact"
export type SqlArtifactDetail = { sql: string; source: "agent-markdown" | "sql-tool"; sourceMessageID?: string }

export function isSqlArtifactDetail(value: unknown): value is SqlArtifactDetail {
  if (!value || typeof value !== "object") return false
  const detail = value as Record<string, unknown>
  if (typeof detail.sql !== "string" || !detail.sql.trim() || detail.sql.length > 4000) return false
  return detail.source === "agent-markdown" || detail.source === "sql-tool"
}

export function emitSqlArtifact(target: EventTarget, detail: SqlArtifactDetail) {
  if (!isSqlArtifactDetail(detail)) return false
  return target.dispatchEvent(new CustomEvent(SQL_ARTIFACT_EVENT, { detail }))
}
