// Public service for ODPS queries. Loads credentials from the secret store,
// runs queries through the sidecar supervisor, and applies the SQL safety
// gate before forwarding anything to the executor.

import { resolve as resolvePath } from "node:path"

import {
  OdpsSidecarSupervisor,
  resolveSidecarPath,
  type SidecarSupervisorOptions,
} from "./sidecar"
import { evaluateSql, sqlSummary, type SqlPolicyError } from "./sql-policy"
import type { QueryParams, QueryResult, SidecarError } from "./protocol"

// Re-export types so consumers can `import { OdpsService } from "./service"`.
export type { QueryParams, QueryResult, SidecarError } from "./protocol"

export interface OdpsServiceOptions {
  /**
   * Absolute path to the sidecar `pyproject.toml` directory. When omitted,
   * the service resolves the bundled sidecar next to the workspace root.
   */
  readonly sidecarPath?: string
  /**
   * Override the dry-run flag. When unset the supervisor reads
   * `DWA_PYODPS_DRY_RUN` (1/true/yes → on).
   */
  readonly dryRun?: boolean
  /**
   * Optional test injection of a pre-built supervisor. Used by the
   * integration test to avoid spawning real `uv` invocations.
   */
  readonly supervisor?: OdpsSidecarSupervisor
  /** Default timeout for every query when `query.timeoutMs` is absent. */
  readonly defaultTimeoutMs?: number
}

export interface OdpsQueryInput {
  readonly credential: { readonly accessKeyId: string; readonly accessKeySecret: string }
  readonly endpoint: string
  readonly project: string
  readonly sql: string
  readonly timeoutMs?: number
  readonly maxRows?: number
  readonly maxBytes?: number
  readonly signal?: AbortSignal
}

export interface OdpsService {
  query(input: OdpsQueryInput): Promise<QueryResult>
  health(): Promise<{ ok: boolean; version: string; dry_run: boolean }>
  stop(): Promise<void>
}

export class OdpsPolicyError extends Error {
  readonly code: SqlPolicyError["code"]
  readonly token?: string
  constructor(error: SqlPolicyError) {
    super(error.message)
    this.code = error.code
    if (error.token) this.token = error.token
  }
}

export class OdpsSidecarError extends Error {
  readonly code: string
  readonly retryable: boolean
  constructor(error: SidecarError) {
    super(error.message)
    this.code = error.code
    this.retryable = error.retryable
  }
}

export function makeOdpsService(options: OdpsServiceOptions = {}): OdpsService {
  const supervisor =
    options.supervisor ??
    new OdpsSidecarSupervisor({
      ...(options.sidecarPath ? { projectPath: resolvePath(options.sidecarPath) } : { projectPath: resolveSidecarPath(process.cwd()) }),
      ...(options.dryRun !== undefined ? { dryRun: options.dryRun } : {}),
    } satisfies SidecarSupervisorOptions)

  return {
    async query(input: OdpsQueryInput): Promise<QueryResult> {
      const policy = evaluateSql(input.sql)
      if (!policy.ok) {
        throw new OdpsPolicyError(policy.error!)
      }
      const params: QueryParams = {
        endpoint: input.endpoint,
        project: input.project,
        sql: input.sql,
        timeout_ms: input.timeoutMs ?? options.defaultTimeoutMs ?? 300_000,
        max_rows: input.maxRows ?? 10_000,
        max_bytes: input.maxBytes ?? 10 * 1024 * 1024,
        access_key_id: input.credential.accessKeyId,
        access_key_secret: input.credential.accessKeySecret,
      }
      try {
        return await supervisor.query({ ...params, ...(input.signal ? { signal: input.signal } : {}) })
      } catch (err) {
        if (err instanceof OdpsSidecarError) throw err
        if (err && typeof err === "object" && "code" in err && "retryable" in err) {
          throw new OdpsSidecarError(err as SidecarError)
        }
        throw new OdpsSidecarError({
          code: "INTERNAL",
          message: err instanceof Error ? err.message : "unknown error",
          retryable: false,
        })
      }
    },
    health() {
      return supervisor.health()
    },
    stop() {
      return supervisor.stop()
    },
  }
}

// Suppress warnings about unused symbols that are part of the public API.
void sqlSummary
