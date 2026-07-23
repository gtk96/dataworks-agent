// Shared NDJSON protocol types between the Bun supervisor and the Python sidecar.
// The wire format is fixed by the brief and exercised by sidecars/pyodps/tests.
//
// One JSON object per stdin line. Only protocol JSON on stdout.
// Diagnostics go to stderr. Credentials and SQL literals never appear in logs.

export type SidecarMethod = "query" | "cancel" | "health"

export interface QueryParams {
  endpoint?: string
  project: string
  sql: string
  timeout_ms: number
  max_rows: number
  max_bytes: number
  access_key_id: string
  access_key_secret: string
  /**
   * Optional dry-run flag. When true the sidecar uses the canned
   * deterministic path and never reaches the real ODPS endpoint. The Bun
   * supervisor sets this automatically based on the read mode.
   */
  dry_run?: boolean
}

export interface CancelParams {
  id: string
}

export interface SidecarRequest<P = unknown> {
  id: string
  method: SidecarMethod
  params?: P
}

export interface QueryResult {
  columns: ReadonlyArray<{ name: string; type: string }>
  rows: ReadonlyArray<ReadonlyArray<unknown>>
  truncated: boolean
  instance_id: string | null
  duration_ms: number
}

export interface SidecarError {
  code: string
  message: string
  retryable: boolean
}

export interface SidecarSuccess<R = unknown> {
  id: string
  result: R
}

export interface SidecarFailure {
  id: string | null
  error: SidecarError
}

/** True when the wire payload is a success line. */
export function isSuccess(line: unknown): line is SidecarSuccess<unknown> {
  if (!line || typeof line !== "object") return false
  const obj = line as Record<string, unknown>
  return typeof obj.id === "string" && "result" in obj
}

/** True when the wire payload is an error line. */
export function isFailure(line: unknown): line is SidecarFailure {
  if (!line || typeof line !== "object") return false
  const obj = line as Record<string, unknown>
  return "error" in obj && !!obj.error && typeof obj.error === "object"
}

/** Stable error codes used by both ends of the wire. */
export const ERROR_CODES = {
  INVALID_JSON: "INVALID_JSON",
  INVALID_SHAPE: "INVALID_SHAPE",
  INVALID_UTF8: "INVALID_UTF8",
  MISSING_ID: "MISSING_ID",
  MISSING_METHOD: "MISSING_METHOD",
  UNKNOWN_METHOD: "UNKNOWN_METHOD",
  INVALID_PARAMS: "INVALID_PARAMS",
  MISSING_CANCEL_TARGET: "MISSING_CANCEL_TARGET",
  LINE_TOO_LONG: "LINE_TOO_LONG",
  BUSY: "BUSY",
  QUERY_FAILED: "QUERY_FAILED",
  TIMEOUT: "TIMEOUT",
  CANCELLED: "CANCELLED",
  UPSTREAM_ERROR: "UPSTREAM_ERROR",
  INTERNAL: "INTERNAL",
} as const

export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES]

/** Hard cap on a single stdout/stderr line. Matches the brief: 16 MB. */
export const MAX_LINE_BYTES = 16 * 1024 * 1024

/** Maximum concurrent in-flight queries per sidecar process. */
export const MAX_CONCURRENT_QUERIES = 4
