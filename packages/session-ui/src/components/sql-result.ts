export type SqlResultColumn = { name: string; type?: string }

export type SqlResultView = {
  columns: SqlResultColumn[]
  rows: unknown[][]
  rowCount: number
  truncated: boolean
  durationMs?: number
  instanceId?: string | null
  connectionID?: string
  projectID?: number
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined
  return value as Record<string, unknown>
}

function normalizeColumn(value: unknown, index: number): SqlResultColumn {
  if (typeof value === "string" && value) return { name: value }
  const record = asRecord(value)
  if (!record) return { name: `col_${index + 1}` }
  const name =
    typeof record.name === "string" && record.name
      ? record.name
      : typeof record.columnName === "string" && record.columnName
        ? record.columnName
        : `col_${index + 1}`
  const type =
    typeof record.type === "string"
      ? record.type
      : typeof record.columnType === "string"
        ? record.columnType
        : undefined
  return type ? { name, type } : { name }
}

/** Coerce tool metadata (preferred) or free-form output into a table view model. */
export function parseSqlResultView(input: {
  metadata?: Record<string, unknown>
  output?: string
  toolInput?: Record<string, unknown>
}): SqlResultView | undefined {
  const metadata = input.metadata ?? {}
  if (metadata.kind === "sql_result" || Array.isArray(metadata.previewRows) || Array.isArray(metadata.columns)) {
    const columns = Array.isArray(metadata.columns)
      ? metadata.columns.map((column, index) => normalizeColumn(column, index))
      : []
    const previewRows = Array.isArray(metadata.previewRows)
      ? metadata.previewRows.map((row) => (Array.isArray(row) ? row : [row]))
      : []
    const rowCount =
      typeof metadata.rowCount === "number" && Number.isFinite(metadata.rowCount)
        ? metadata.rowCount
        : previewRows.length
    return {
      columns,
      rows: previewRows,
      rowCount,
      truncated: metadata.truncated === true || rowCount > previewRows.length,
      durationMs: typeof metadata.durationMs === "number" ? metadata.durationMs : undefined,
      instanceId:
        typeof metadata.instanceId === "string"
          ? metadata.instanceId
          : metadata.instanceId === null
            ? null
            : undefined,
      connectionID:
        typeof metadata.connectionID === "string"
          ? metadata.connectionID
          : typeof input.toolInput?.connectionID === "string"
            ? input.toolInput.connectionID
            : undefined,
      projectID:
        typeof metadata.projectID === "number"
          ? metadata.projectID
          : typeof input.toolInput?.projectID === "number"
            ? input.toolInput.projectID
            : undefined,
    }
  }

  const output = input.output?.trim()
  if (!output || output === "(no rows)") {
    if (!output) return undefined
    return {
      columns: [],
      rows: [],
      rowCount: 0,
      truncated: false,
      connectionID: typeof input.toolInput?.connectionID === "string" ? input.toolInput.connectionID : undefined,
      projectID: typeof input.toolInput?.projectID === "number" ? input.toolInput.projectID : undefined,
    }
  }

  // Fallback: parse tab-separated output produced by the plugin formatter.
  const lines = output.split(/\r?\n/).filter((line) => line.length > 0 && !line.startsWith("…"))
  if (lines.length === 0) return undefined
  const header = lines[0]!.split("\t")
  const looksHeader = header.length > 1 || lines.length === 1
  const columns = looksHeader ? header.map((name) => ({ name })) : [{ name: "value" }]
  const body = looksHeader ? lines.slice(1) : lines
  const rows = body.map((line) => line.split("\t"))
  return {
    columns,
    rows,
    rowCount: rows.length,
    truncated: output.includes("truncated"),
    connectionID: typeof input.toolInput?.connectionID === "string" ? input.toolInput.connectionID : undefined,
    projectID: typeof input.toolInput?.projectID === "number" ? input.toolInput.projectID : undefined,
  }
}

export function formatSqlCell(value: unknown): string {
  if (value === null || value === undefined) return ""
  if (typeof value === "string") return value
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

export function sqlResultToTsv(view: SqlResultView): string {
  const header = view.columns.map((column) => column.name).join("\t")
  const body = view.rows.map((row) => row.map(formatSqlCell).join("\t")).join("\n")
  if (!header) return body
  if (!body) return header
  return `${header}\n${body}`
}

export function sqlResultSubtitle(view: SqlResultView): string {
  const parts = [`${view.rowCount} row${view.rowCount === 1 ? "" : "s"}`]
  if (view.truncated) parts.push("truncated")
  if (typeof view.durationMs === "number") parts.push(`${view.durationMs}ms`)
  if (typeof view.projectID === "number") parts.push(`project ${view.projectID}`)
  return parts.join(" · ")
}
