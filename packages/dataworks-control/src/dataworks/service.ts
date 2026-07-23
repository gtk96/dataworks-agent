import * as Eff from "effect/Effect"
import { hashAuditArgs } from "@dataworks-agent/core"
import type { ConsumedWriteTicket } from "../write-ticket/service"
import type {
  DataWorksClient,
  DataWorksError,
  JobPage,
  JobStatus,
  Lineage,
  ProjectPage,
  TableDescription,
  TablePage,
} from "@dataworks-agent/core"
import { DryRunDataWorksClient } from "./dry-run"
import { OpenApiClientCache } from "./openapi"

export type DataWorksMode = "dry-run" | "staging" | "production"

export interface ServiceConfig {
  readonly mode: DataWorksMode
  readonly openApiCache?: OpenApiClientCache
  readonly connectionID?: string
}

export interface DataWorksService {
  listProjects(args: {
    region: string
    pageNumber: number
    pageSize: number
  }): Promise<ProjectPage>
  listJobs(args: {
    projectID: number
    pageNumber: number
    pageSize: number
    region?: string
  }): Promise<JobPage>
  getJobStatus(args: {
    projectID: number
    instanceID: number
    region?: string
  }): Promise<JobStatus>
  tableLineage(args: {
    projectID: number
    tableName: string
    region?: string
  }): Promise<Lineage>
  listTables(args: {
    projectID: number
    keyword?: string
    pageNumber: number
    pageSize: number
    projectName?: string
    region?: string
  }): Promise<TablePage>
  describeTable(args: {
    projectID: number
    tableName: string
    projectName?: string
    region?: string
  }): Promise<TableDescription>
}

// Reads the deployment mode from the environment. Defaults to dry-run so that
// tests and unconfigured deployments never reach the live SDK by accident.
export function readModeFromEnv(env: NodeJS.ProcessEnv = process.env): DataWorksMode {
  const raw = (env.DATAWORKS_AGENT_MODE ?? "dry-run").toLowerCase()
  if (raw === "staging" || raw === "production") return raw
  return "dry-run"
}

async function runOrFail<T, E>(effect: Eff.Effect<T, E>): Promise<T> {
  const exit = await Eff.runPromiseExit(effect as Eff.Effect<T, never>)
  if (exit._tag === "Failure") {
    const cause = exit.cause as unknown as {
      failures?: ReadonlyArray<unknown>
      defects?: ReadonlyArray<unknown>
    }
    const failure = (cause.failures && cause.failures.length > 0)
      ? cause.failures[0]
      : cause.defects && cause.defects.length > 0
        ? cause.defects[0]
        : new Error("unknown failure")
    throw failure
  }
  return exit.value as T
}

export class DataWorksServiceImpl implements DataWorksService {
  private readonly mode: DataWorksMode
  private readonly openApiCache: OpenApiClientCache | undefined
  private readonly connectionID: string | undefined
  // Dry-run has a single shared client.
  private readonly dryRunClient: DryRunDataWorksClient | undefined

  constructor(private readonly config: ServiceConfig) {
    this.mode = config.mode
    this.openApiCache = config.openApiCache
    this.connectionID = config.connectionID
    if (this.mode === "dry-run") {
      this.dryRunClient = new DryRunDataWorksClient()
    }
  }

  private async acquireClient(region: string): Promise<DataWorksClient> {
    if (this.mode === "dry-run") {
      return this.dryRunClient!
    }
    // staging or production: must use OpenApiClientCache
    if (!this.openApiCache) {
      throw new Error("openApiCache is required for staging/production mode")
    }
    if (!this.connectionID) {
      throw new Error("connectionID is required for staging/production mode")
    }
    return await this.openApiCache.acquire(this.connectionID, region)
  }

  async listProjects(args: { region: string; pageNumber: number; pageSize: number }) {
    const client = await this.acquireClient(args.region)
    return runOrFail(client.listProjects(args)) as Promise<ProjectPage>
  }

  async listJobs(args: {
    projectID: number
    pageNumber: number
    pageSize: number
    region?: string
  }) {
    const client = await this.acquireClient(args.region ?? "cn-hangzhou")
    return runOrFail(
      client.listJobs({
        projectID: args.projectID,
        pageNumber: args.pageNumber,
        pageSize: args.pageSize,
      }),
    ) as Promise<JobPage>
  }

  async getJobStatus(args: { projectID: number; instanceID: number; region?: string }) {
    const client = await this.acquireClient(args.region ?? "cn-hangzhou")
    return runOrFail(
      client.getJobStatus({
        projectID: args.projectID,
        instanceID: args.instanceID,
      }),
    ) as Promise<JobStatus>
  }

  async tableLineage(args: { projectID: number; tableName: string; region?: string }) {
    const client = await this.acquireClient(args.region ?? "cn-hangzhou")
    return runOrFail(
      client.tableLineage({
        projectID: args.projectID,
        tableName: args.tableName,
      }),
    ) as Promise<Lineage>
  }

  async listTables(args: {
    projectID: number
    keyword?: string
    pageNumber: number
    pageSize: number
    projectName?: string
    region?: string
  }) {
    const client = await this.acquireClient(args.region ?? "cn-hangzhou")
    return runOrFail(
      client.listTables({
        projectID: args.projectID,
        pageNumber: args.pageNumber,
        pageSize: args.pageSize,
        ...(args.keyword !== undefined ? { keyword: args.keyword } : {}),
        ...(args.projectName !== undefined ? { projectName: args.projectName } : {}),
      }),
    ) as Promise<TablePage>
  }

  async describeTable(args: {
    projectID: number
    tableName: string
    projectName?: string
    region?: string
  }) {
    const client = await this.acquireClient(args.region ?? "cn-hangzhou")
    return runOrFail(
      client.describeTable({
        projectID: args.projectID,
        tableName: args.tableName,
        ...(args.projectName !== undefined ? { projectName: args.projectName } : {}),
      }),
    ) as Promise<TableDescription>
  }
}

// Factory — selects the right client based on env at request time.
export async function makeService(config: ServiceConfig): Promise<DataWorksService> {
  return new DataWorksServiceImpl(config)
}

export interface DataWorksWriteInput {
  readonly ticket: ConsumedWriteTicket
  readonly tool: string
  readonly args: Readonly<Record<string, unknown>>
  /** Live OpenAPI region (from DataConnection). Required outside dry-run. */
  readonly region?: string
  /** Credential resolver for live writes. Required outside dry-run. */
  readonly resolveCredentials?: (connectionID: string) => Promise<{
    accessKeyId: string
    accessKeySecret: string
  } | null>
  /** Optional OpenAPI cache; created when missing for live modes. */
  readonly openApiCache?: OpenApiClientCache
}

export type DataWorksWriteResult = {
  readonly status: "queued" | "ok"
  readonly dryRun?: boolean
  readonly requestId?: string
}

const WRITE_TOOLS = new Set([
  "dw_rerun_job",
  "dw_trigger_supplement",
  "dw_pause_schedule",
  "dw_alert_silence",
])

export async function executeDataWorksWrite(input: DataWorksWriteInput): Promise<DataWorksWriteResult> {
  if (input.ticket.timeConsumed <= 0) throw new DataWorksWriteDeniedError("ticket_not_consumed")
  if (input.ticket.tool !== input.tool) throw new DataWorksWriteDeniedError("ticket_tool_mismatch")
  if (input.ticket.argsHash !== hashAuditArgs(input.args)) throw new DataWorksWriteDeniedError("ticket_args_mismatch")
  if (!WRITE_TOOLS.has(input.tool)) throw new DataWorksWriteDeniedError("write_tool_not_supported")

  const mode = readModeFromEnv()
  if (mode === "dry-run") {
    return { status: "queued", dryRun: true }
  }

  // Live (staging/production): require credentials + region.
  // Connection write_enabled is enforced before ticket issue and again in HTTP runWriteExecute.
  // The staging *test suite* is separately gated by DWA_STAGING_WRITE_TEST (fail-closed when flag set without secrets).
  if (!input.resolveCredentials) {
    throw new DataWorksWriteDeniedError("live_write_adapter_not_configured")
  }
  const region = input.region?.trim()
  if (!region) throw new DataWorksWriteDeniedError("live_write_adapter_not_configured")

  const cache =
    input.openApiCache ??
    new OpenApiClientCache({ resolveCredentials: input.resolveCredentials })
  const client = await cache.acquire(input.ticket.connectionID, region)
  const writer = client as DataWorksClient & {
    executeWrite?: (
      tool: string,
      args: Readonly<Record<string, unknown>>,
    ) => Promise<DataWorksWriteResult>
  }
  if (typeof writer.executeWrite !== "function") {
    throw new DataWorksWriteDeniedError("live_write_adapter_not_configured")
  }
  return writer.executeWrite(input.tool, input.args)
}

export class DataWorksWriteDeniedError extends Error {
  constructor(
    readonly code:
      | "ticket_not_consumed"
      | "ticket_tool_mismatch"
      | "ticket_args_mismatch"
      | "write_tool_not_supported"
      | "live_write_adapter_not_configured",
  ) {
    super(code)
    this.name = "DataWorksWriteDeniedError"
  }
}

// Validation helpers reused by the HTTP layer.
export function parsePageSize(raw: string | null): number {
  const n = Number(raw ?? "10")
  if (!Number.isInteger(n)) throw Object.assign(new Error("invalid pageSize"), { _tag: "InvalidResponse" as const })
  if (n < 1 || n > 100) throw Object.assign(new Error("pageSize out of range"), { _tag: "InvalidResponse" as const })
  return n
}

export function parsePageNumber(raw: string | null): number {
  const n = Number(raw ?? "1")
  if (!Number.isInteger(n)) throw Object.assign(new Error("invalid pageNumber"), { _tag: "InvalidResponse" as const })
  if (n < 1) throw Object.assign(new Error("pageNumber out of range"), { _tag: "InvalidResponse" as const })
  return n
}

export function parseIntegerId(raw: string | null, field: string): number {
  if (raw === null || raw === "") {
    throw Object.assign(new Error(`${field} required`), { _tag: "InvalidResponse" as const })
  }
  const n = Number(raw)
  if (!Number.isInteger(n)) {
    throw Object.assign(new Error(`${field} must be integer`), { _tag: "InvalidResponse" as const })
  }
  return n
}

export { DataWorksError } from "@dataworks-agent/core"
export type { DataWorksClient, DataWorksError as DataWorksErrorType } from "@dataworks-agent/core"
export type {
  Project,
  ProjectPage,
  Job,
  JobPage,
  JobStatus,
  Lineage,
  Table,
  TablePage,
  TableDescription,
  TableColumn,
} from "@dataworks-agent/core"
