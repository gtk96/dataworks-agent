/** Cap UI preview rows so tool metadata stays small enough for session history. */
export const SQL_PREVIEW_ROW_CAP = 200

export type SqlResultColumn = { name: string; type?: string }

export type SqlResultMetadata = {
  kind: "sql_result"
  columns: SqlResultColumn[]
  rowCount: number
  truncated: boolean
  previewRows: unknown[][]
  instanceId?: string | null
  durationMs?: number
  connectionID: string
  projectID: number
  maxRows: number
  timeoutMs: number
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

function normalizeRow(value: unknown, columnCount: number): unknown[] {
  if (Array.isArray(value)) {
    if (columnCount <= 0) return value
    if (value.length >= columnCount) return value.slice(0, columnCount)
    return [...value, ...Array.from({ length: columnCount - value.length }, () => null)]
  }
  const record = asRecord(value)
  if (!record) return columnCount > 0 ? Array.from({ length: columnCount }, () => value) : [value]
  return []
}

function rowsFromObjects(rows: unknown[], columns: SqlResultColumn[]): unknown[][] {
  return rows.map((row) => {
    const record = asRecord(row)
    if (!record) return normalizeRow(row, columns.length)
    if (columns.length === 0) return Object.values(record)
    return columns.map((column) => (column.name in record ? record[column.name] : null))
  })
}

function extractRows(data: Record<string, unknown>): unknown[] | undefined {
  if (Array.isArray(data.rows)) return data.rows
  if (Array.isArray(data.items)) return data.items
  if (Array.isArray(data.data)) return data.data
  return undefined
}

function extractColumns(data: Record<string, unknown>, sampleRow: unknown | undefined): SqlResultColumn[] {
  if (Array.isArray(data.columns) && data.columns.length > 0) {
    return data.columns.map((column, index) => normalizeColumn(column, index))
  }
  const record = asRecord(sampleRow)
  if (record) return Object.keys(record).map((name) => ({ name }))
  if (Array.isArray(sampleRow)) {
    return sampleRow.map((_, index) => ({ name: `col_${index + 1}` }))
  }
  return []
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return ""
  if (typeof value === "string") return value
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

/** Build model-facing plain text; keep stable enough for LLM consumption. */
export function formatSqlOutput(input: {
  columns: SqlResultColumn[]
  rows: unknown[][]
  truncated: boolean
  rowCount: number
}): string {
  if (input.rowCount === 0) return "(no rows)"
  const header = input.columns.map((column) => column.name).join("\t")
  const body = input.rows.map((row) => row.map(formatCell).join("\t")).join("\n")
  const table = header ? `${header}\n${body}` : body
  if (!input.truncated) return table
  return `${table}\n… truncated (${input.rowCount} rows total)`
}

/**
 * Normalize control-plane / ODPS SQL payloads into structured tool metadata.
 * Secrets must never be placed on this object.
 */
export function buildSqlResult(input: {
  data: unknown
  connectionID: string
  projectID: number
  maxRows: number
  timeoutMs: number
}): { title: string; output: string; metadata: SqlResultMetadata } {
  const empty = (extra?: Partial<SqlResultMetadata>) => {
    const metadata: SqlResultMetadata = {
      kind: "sql_result",
      columns: [],
      rowCount: 0,
      truncated: false,
      previewRows: [],
      connectionID: input.connectionID,
      projectID: input.projectID,
      maxRows: input.maxRows,
      timeoutMs: input.timeoutMs,
      ...extra,
    }
    return {
      title: "sql result",
      output: "(no rows)",
      metadata,
    }
  }

  if (input.data == null) return empty()
  if (typeof input.data === "string") {
    return {
      title: "sql result",
      output: input.data || "(no rows)",
      metadata: {
        kind: "sql_result",
        columns: [],
        rowCount: input.data.trim() ? 1 : 0,
        truncated: false,
        previewRows: input.data.trim() ? [[input.data]] : [],
        connectionID: input.connectionID,
        projectID: input.projectID,
        maxRows: input.maxRows,
        timeoutMs: input.timeoutMs,
      },
    }
  }

  const record = asRecord(input.data)
  if (!record) {
    return {
      title: "sql result",
      output: String(input.data),
      metadata: {
        kind: "sql_result",
        columns: [{ name: "value" }],
        rowCount: 1,
        truncated: false,
        previewRows: [[input.data]],
        connectionID: input.connectionID,
        projectID: input.projectID,
        maxRows: input.maxRows,
        timeoutMs: input.timeoutMs,
      },
    }
  }

  const rawRows = extractRows(record)
  if (!rawRows) {
    return {
      title: "sql result",
      output: JSON.stringify(input.data, null, 2),
      metadata: {
        kind: "sql_result",
        columns: [],
        rowCount: 0,
        truncated: false,
        previewRows: [],
        connectionID: input.connectionID,
        projectID: input.projectID,
        maxRows: input.maxRows,
        timeoutMs: input.timeoutMs,
        instanceId: typeof record.instanceId === "string" ? record.instanceId : null,
        durationMs: typeof record.durationMs === "number" ? record.durationMs : undefined,
      },
    }
  }

  const columns = extractColumns(record, rawRows[0])
  const matrix =
    rawRows.length > 0 && asRecord(rawRows[0])
      ? rowsFromObjects(rawRows, columns)
      : rawRows.map((row) => normalizeRow(row, columns.length))

  const truncatedFlag = record.truncated === true || matrix.length > input.maxRows
  const limited = matrix.slice(0, input.maxRows)
  const previewRows = limited.slice(0, SQL_PREVIEW_ROW_CAP)
  const rowCount =
    typeof record.rowCount === "number" && Number.isFinite(record.rowCount)
      ? record.rowCount
      : matrix.length

  const metadata: SqlResultMetadata = {
    kind: "sql_result",
    columns,
    rowCount,
    truncated: truncatedFlag || rowCount > previewRows.length,
    previewRows,
    instanceId:
      typeof record.instanceId === "string"
        ? record.instanceId
        : record.instanceId === null
          ? null
          : undefined,
    durationMs: typeof record.durationMs === "number" ? record.durationMs : undefined,
    connectionID: input.connectionID,
    projectID: input.projectID,
    maxRows: input.maxRows,
    timeoutMs: input.timeoutMs,
  }

  return {
    title: "sql result",
    output: formatSqlOutput({
      columns,
      rows: previewRows,
      truncated: metadata.truncated,
      rowCount,
    }),
    metadata,
  }
}
