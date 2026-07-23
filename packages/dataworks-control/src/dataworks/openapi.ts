import * as Eff from "effect/Effect"
import * as Redacted from "effect/Redacted"
import type {
  DataWorksClient,
  DataWorksError,
  JobPage,
  JobStatus,
  Lineage,
  Project,
  ProjectPage,
  Table,
  TableColumn,
  TableDescription,
  TablePage,
} from "@dataworks-agent/core"
import { DataWorksError as DataWorksErrorCtor } from "@dataworks-agent/core"
import Client from "@alicloud/dataworks-public20200518"
import type { Config as SdkConfig } from "@alicloud/openapi-client"

// Credentials loaded from DataConnectionRepo. No environment variable fallback.
// The brief requires caching clients per {connectionID, region} with 10-minute idle TTL.

export interface DataWorksCredentials {
  readonly accessKeyId: string
  readonly accessKeySecret: string
}

interface CachedClientEntry {
  readonly client: DataWorksClient
  readonly usedAt: number
}

export interface OpenApiClientConfig {
  readonly resolveCredentials: (connectionID: string) => Promise<DataWorksCredentials | null>
  readonly fetchImpl?: typeof fetch
}

const TEN_MINUTES_MS = 10 * 60 * 1000

function buildSdkConfig(credentials: DataWorksCredentials, region: string): SdkConfig {
  return {
    accessKeyId: credentials.accessKeyId,
    accessKeySecret: credentials.accessKeySecret,
    regionId: region,
    type: "access_key",
  } as unknown as SdkConfig
}

// Strips the client of any methods not used here to keep the surface minimal.
// Write surface is included so ticket-gated UI/plugin execute can call real OpenAPI.
type SdkClient = Pick<
  Client,
  | "listProjects"
  | "listNodes"
  | "listInstances"
  | "getInstance"
  | "getMetaTableLineage"
  | "searchMetaTables"
  | "getMetaTableBasicInfo"
  | "getMetaTableColumn"
  | "restartInstance"
  | "runCycleDagNodes"
  | "updateNodeRunMode"
  | "updateRemind"
>

function makeSdkClient(credentials: DataWorksCredentials, region: string): SdkClient {
  return new Client(buildSdkConfig(credentials, region)) as unknown as SdkClient
}

// Error type-guard helpers — used to translate raw SDK/network errors into
// the typed union without leaking credential material.
function isTeaErrorLike(err: unknown): err is { code?: string; message?: string; data?: unknown; statusCode?: number } {
  return !!err && typeof err === "object"
}

function classifyError(err: unknown): DataWorksError {
  if (err && typeof err === "object" && "_tag" in err && typeof (err as { _tag: unknown })._tag === "string") {
    return err as DataWorksError
  }
  if (!isTeaErrorLike(err)) {
    return DataWorksErrorCtor.UpstreamUnavailable("dataworks upstream unavailable")
  }
  const code = (err.code ?? "").toUpperCase()
  const message = typeof err.message === "string" ? err.message : ""
  if (code === "UNAUTHORIZED" || code === "AUTHFAILURE" || code === "INVALIDACCESSKEYID") {
    return DataWorksErrorCtor.Unauthorized("dataworks credentials rejected")
  }
  if (code === "FORBIDDEN" || code === "FORBIDDEN.USER" || code === "ACCESSDENIED") {
    return DataWorksErrorCtor.Forbidden("dataworks access forbidden")
  }
  if (code === "THROTTLING" || code === "THROTTLING.USER" || code === "QUOTAEXCEEDED") {
    return DataWorksErrorCtor.RateLimited(60_000, "dataworks rate limited")
  }
  if (code === "NOTFOUND" || code === "INSTANCE.NOTFOUND" || code === "PROJECT.NOTFOUND") {
    return DataWorksErrorCtor.NotFound("dataworks resource not found")
  }
  if (code === "INVALIDPARAMETER" || code === "MALFORMEDRESPONSE") {
    return DataWorksErrorCtor.InvalidResponse("dataworks invalid response")
  }
  // Network errors and everything else → upstream unavailable. Never echo the
  // raw message which can include the AK/endpoint or upstream stack traces.
  void message
  return DataWorksErrorCtor.UpstreamUnavailable("dataworks upstream unavailable")
}

function sanitizeProject(p: { projectId?: number; projectName?: string; projectIdentifier?: string }): Project {
  return {
    id: typeof p.projectId === "number" ? p.projectId : 0,
    name: typeof p.projectName === "string" ? p.projectName : (typeof p.projectIdentifier === "string" ? p.projectIdentifier : ""),
    envType: "DEV",
    region: "",
  }
}

export class OpenApiDataWorksClient implements DataWorksClient {
  private readonly sdk: SdkClient
  private readonly connectionID: string
  private readonly region: string

  constructor(sdk: SdkClient, connectionID: string, region: string) {
    this.sdk = sdk
    this.connectionID = connectionID
    this.region = region
  }

  // Internal accessor so the cache key can be reconstructed from an acquired client.
  get cacheKey(): { connectionID: string; region: string } {
    return { connectionID: this.connectionID, region: this.region }
  }

  listProjects(input: { region: string; pageNumber: number; pageSize: number }) {
    const sdkCall = async () => {
      const request = { pageNumber: input.pageNumber, pageSize: input.pageSize }
      const resp = await (this.sdk.listProjects as unknown as (r: typeof request) => Promise<{
        body?: { pageResult?: { projectList?: Array<{ projectId?: number; projectName?: string; projectIdentifier?: string }>; pageNumber?: number; pageSize?: number; totalCount?: number } }
      }>)(request)
      const pageResult = resp?.body?.pageResult
      const rawList = Array.isArray(pageResult?.projectList) ? pageResult!.projectList! : []
      const items: ReadonlyArray<Project> = rawList.map(sanitizeProject)
      const page: ProjectPage = {
        items,
        total: typeof pageResult?.totalCount === "number" ? pageResult.totalCount : items.length,
        pageNumber: typeof pageResult?.pageNumber === "number" ? pageResult.pageNumber : input.pageNumber,
        pageSize: typeof pageResult?.pageSize === "number" ? pageResult.pageSize : input.pageSize,
      }
      return page
    }
    return Eff.tryPromise({ try: sdkCall, catch: classifyError }) as ReturnType<DataWorksClient["listProjects"]>
  }

  listJobs(input: { projectID: number; pageNumber: number; pageSize: number }) {
    // Prefer ListInstances so rows carry instanceId (required by restartInstance / dw_rerun_job).
    // ListNodes only yields node ids and must never be used as restartInstance targets.
    const sdkCall = async () => {
      const request = {
        projectId: input.projectID,
        projectEnv: "PROD",
        pageNumber: input.pageNumber,
        pageSize: input.pageSize,
      }
      const resp = await (this.sdk.listInstances as unknown as (r: typeof request) => Promise<{
        body?: {
          data?: {
            instances?: Array<{
              instanceId?: number
              nodeId?: number
              nodeName?: string
              status?: string
            }>
            pageNumber?: number
            pageSize?: number
            totalCount?: number
          }
        }
      }>)(request)
      const data = resp?.body?.data
      const rawList = Array.isArray(data?.instances) ? data!.instances! : []
      const items = rawList.map((row) => {
        const instanceId = typeof row.instanceId === "number" ? row.instanceId : 0
        const nodeId = typeof row.nodeId === "number" ? row.nodeId : undefined
        return {
          id: instanceId,
          name: typeof row.nodeName === "string" ? row.nodeName : "",
          projectId: input.projectID,
          status: typeof row.status === "string" ? row.status : "UNKNOWN",
          ...(instanceId > 0 ? { instanceId } : {}),
          ...(nodeId !== undefined ? { nodeId } : {}),
        }
      })
      const page: JobPage = {
        items,
        total: typeof data?.totalCount === "number" ? data.totalCount : items.length,
        pageNumber: typeof data?.pageNumber === "number" ? data.pageNumber : input.pageNumber,
        pageSize: typeof data?.pageSize === "number" ? data.pageSize : input.pageSize,
      }
      return page
    }
    return Eff.tryPromise({ try: sdkCall, catch: classifyError }) as ReturnType<DataWorksClient["listJobs"]>
  }

  getJobStatus(input: { projectID: number; instanceID: number }) {
    const sdkCall = async () => {
      const request = { instanceId: input.instanceID, projectEnv: "PROD" }
      const resp = await (this.sdk.getInstance as unknown as (r: typeof request) => Promise<{
        body?: { data?: { instanceId?: number; status?: string; beginRunningTime?: number } }
      }>)(request)
      const data = resp?.body?.data
      if (!data) {
        throw { code: "NOTFOUND" }
      }
      const status: JobStatus = {
        id: typeof data.instanceId === "number" ? data.instanceId : input.instanceID,
        status: typeof data.status === "string" ? data.status : "UNKNOWN",
        ...(typeof data.beginRunningTime === "number" ? { lastRunTime: data.beginRunningTime } : {}),
      }
      return status
    }
    return Eff.tryPromise({ try: sdkCall, catch: classifyError }) as ReturnType<DataWorksClient["getJobStatus"]>
  }

  tableLineage(input: { projectID: number; tableName: string }) {
    const sdkCall = async () => {
      const request = { tableName: input.tableName, direction: "up", pageSize: 100 }
      void input.projectID
      const resp = await (this.sdk.getMetaTableLineage as unknown as (r: typeof request) => Promise<{
        body?: { data?: { dataEntityList?: Array<{ tableName?: string; databaseName?: string }>; hasNext?: boolean } }
      }>)(request)
      const data = resp?.body?.data
      const upstream: ReadonlyArray<{ name: string; type: string }> = Array.isArray(data?.dataEntityList)
        ? data!.dataEntityList!.map((e) => ({
            name: typeof e.tableName === "string" ? e.tableName : "",
            type: typeof e.databaseName === "string" ? e.databaseName : "table",
          }))
        : []
      const lineage: Lineage = { tableName: input.tableName, upstream, downstream: [] }
      return lineage
    }
    return Eff.tryPromise({ try: sdkCall, catch: classifyError }) as ReturnType<DataWorksClient["tableLineage"]>
  }

  listTables(input: {
    projectID: number
    keyword?: string
    pageNumber: number
    pageSize: number
    projectName?: string
  }) {
    const sdkCall = async () => {
      const projectName = input.projectName?.trim()
      // SearchMetaTables requires `keyword` (Aliyun DataWorks OpenAPI). Prefer the
      // caller's search string; when empty, scope with project name rather than a
      // blind "*" wildcard (which can be rejected or match too broadly).
      // Documented fallback order: user keyword → projectName → "" (API-required field).
      const trimmedKeyword = input.keyword?.trim()
      const keyword =
        trimmedKeyword && trimmedKeyword.length > 0
          ? trimmedKeyword
          : projectName && projectName.length > 0
            ? projectName
            : ""
      const request: {
        keyword: string
        pageNumber: number
        pageSize: number
        dataSourceType: string
        appGuid?: string
      } = {
        keyword,
        pageNumber: input.pageNumber,
        pageSize: input.pageSize,
        dataSourceType: "odps",
      }
      // appGuid scopes the search to MaxCompute project: odps.<projectName>
      if (projectName) request.appGuid = `odps.${projectName}`
      void input.projectID
      const resp = await (this.sdk.searchMetaTables as unknown as (r: typeof request) => Promise<{
        body?: {
          data?: {
            dataEntityList?: Array<{
              tableName?: string
              schema?: string
              projectId?: number
              projectName?: string
              tableGuid?: string
              entityType?: number
            }>
            pageNumber?: number
            pageSize?: number
            totalCount?: number
          }
        }
      }>)(request)
      const data = resp?.body?.data
      const rawList = Array.isArray(data?.dataEntityList) ? data!.dataEntityList! : []
      const items: ReadonlyArray<Table> = rawList.map((row) => {
        const name = typeof row.tableName === "string" ? row.tableName : ""
        const schema = typeof row.schema === "string" ? row.schema : undefined
        const entityType = row.entityType === 1 ? "view" : "table"
        const resolvedProjectName =
          (typeof row.projectName === "string" && row.projectName) || projectName || undefined
        // Prefer SDK tableGuid; otherwise construct odps.<projectName>.<table> when name is known.
        const tableGuid =
          typeof row.tableGuid === "string" && row.tableGuid
            ? row.tableGuid
            : resolvedProjectName && name
              ? `odps.${resolvedProjectName}.${name}`
              : undefined
        const table: Table = {
          name,
          type: entityType,
          ...(schema ? { schema } : {}),
          ...(typeof row.projectId === "number" ? { projectId: row.projectId } : {}),
          ...(resolvedProjectName ? { projectName: resolvedProjectName } : {}),
          ...(tableGuid ? { tableGuid } : {}),
        }
        return table
      })
      const page: TablePage = {
        items,
        total: typeof data?.totalCount === "number" ? data.totalCount : items.length,
        pageNumber: typeof data?.pageNumber === "number" ? data.pageNumber : input.pageNumber,
        pageSize: typeof data?.pageSize === "number" ? data.pageSize : input.pageSize,
      }
      return page
    }
    return Eff.tryPromise({ try: sdkCall, catch: classifyError }) as ReturnType<DataWorksClient["listTables"]>
  }

  describeTable(input: { projectID: number; tableName: string; projectName?: string }) {
    const sdkCall = async () => {
      const projectName = input.projectName?.trim()
      // tableGuid for MaxCompute meta APIs is odps.<projectName>.<tableName>.
      // Without a MaxCompute project name the GUID is invalid — fail clearly rather than
      // calling OpenAPI with `odps.<tableName>` (numeric project id is not a substitute).
      if (!projectName) {
        throw Object.assign(new Error("projectName required for describeTable (use MaxCompute project name, not numeric project id)"), {
          code: "INVALIDPARAMETER",
        })
      }
      const tableGuid = `odps.${projectName}.${input.tableName}`
      void input.projectID

      const basicReq = { tableGuid, dataSourceType: "odps", extension: false }
      const basicResp = await (this.sdk.getMetaTableBasicInfo as unknown as (r: typeof basicReq) => Promise<{
        body?: {
          data?: {
            tableName?: string
            tableGuid?: string
            comment?: string
            isPartitionTable?: boolean
            databaseName?: string
            caption?: string
            projectName?: string
          }
        }
      }>)(basicReq)
      const basic = basicResp?.body?.data
      if (!basic) {
        throw { code: "NOTFOUND" }
      }

      const colReq = { tableGuid, pageNum: 1, pageSize: 100 }
      const colResp = await (this.sdk.getMetaTableColumn as unknown as (r: typeof colReq) => Promise<{
        body?: {
          data?: {
            columnList?: Array<{
              columnName?: string
              columnType?: string
              comment?: string
              isPartitionColumn?: boolean
              isPrimaryKey?: boolean
            }>
          }
        }
      }>)(colReq)
      const columnList = Array.isArray(colResp?.body?.data?.columnList)
        ? colResp!.body!.data!.columnList!
        : []
      const columns: ReadonlyArray<TableColumn> = columnList.map((c) => ({
        name: typeof c.columnName === "string" ? c.columnName : "",
        type: typeof c.columnType === "string" ? c.columnType : "",
        ...(typeof c.comment === "string" ? { comment: c.comment } : {}),
        ...(typeof c.isPartitionColumn === "boolean" ? { isPartition: c.isPartitionColumn } : {}),
        ...(typeof c.isPrimaryKey === "boolean" ? { isPrimaryKey: c.isPrimaryKey } : {}),
      }))
      const partitionCols = columns.filter((c) => c.isPartition).map((c) => c.name)
      const desc: TableDescription = {
        name: typeof basic.tableName === "string" && basic.tableName ? basic.tableName : input.tableName,
        columns,
        ...(typeof basic.tableGuid === "string" ? { tableGuid: basic.tableGuid } : { tableGuid }),
        ...(typeof basic.comment === "string" ? { comment: basic.comment } : {}),
        ...(typeof basic.isPartitionTable === "boolean" ? { isPartitionTable: basic.isPartitionTable } : {}),
        ...(typeof basic.databaseName === "string" ? { schema: basic.databaseName } : {}),
        projectName:
          (typeof basic.projectName === "string" && basic.projectName) || projectName,
        ...(partitionCols.length > 0 ? { partition: partitionCols.join(",") } : {}),
      }
      return desc
    }
    return Eff.tryPromise({ try: sdkCall, catch: classifyError }) as ReturnType<DataWorksClient["describeTable"]>
  }

  /**
   * Ticket-gated write operations. Invoked only after WriteTicketService.consume.
   * Never logs args that may contain business identifiers beyond the SDK call.
   */
  async executeWrite(
    tool: string,
    args: Readonly<Record<string, unknown>>,
  ): Promise<{ status: "queued" | "ok"; requestId?: string }> {
    try {
      switch (tool) {
        case "dw_rerun_job":
          return await this.writeRerunJob(args)
        case "dw_trigger_supplement":
          return await this.writeTriggerSupplement(args)
        case "dw_pause_schedule":
          return await this.writePauseSchedule(args)
        case "dw_alert_silence":
          return await this.writeAlertSilence(args)
        default:
          throw Object.assign(new Error("write_tool_not_supported"), { code: "INVALIDPARAMETER" })
      }
    } catch (err) {
      throw classifyError(err)
    }
  }

  private async writeRerunJob(args: Readonly<Record<string, unknown>>) {
    const instanceId = requireInt(args.instanceID ?? args.instanceId, "instanceID")
    const projectEnv = typeof args.projectEnv === "string" && args.projectEnv ? args.projectEnv : "PROD"
    const resp = await (this.sdk.restartInstance as unknown as (r: {
      instanceId: number
      projectEnv: string
    }) => Promise<{ body?: { requestId?: string; data?: boolean } }>)({
      instanceId,
      projectEnv,
    })
    return { status: "ok" as const, ...(resp?.body?.requestId ? { requestId: resp.body.requestId } : {}) }
  }

  private async writeTriggerSupplement(args: Readonly<Record<string, unknown>>) {
    const nodeID = requireInt(args.nodeID ?? args.nodeId, "nodeID")
    const bizDate = requireString(args.bizDate, "bizDate")
    // API expects yyyy-MM-dd 00:00:00; accept yyyy-MM-dd and normalize.
    const day = bizDate.length === 10 ? `${bizDate} 00:00:00` : bizDate
    const projectEnv = typeof args.projectEnv === "string" && args.projectEnv ? args.projectEnv : "PROD"
    const name =
      (typeof args.name === "string" && args.name.trim()) ||
      `dwa_supplement_${nodeID}_${bizDate.replace(/[^0-9]/g, "").slice(0, 8)}`
    const resp = await (this.sdk.runCycleDagNodes as unknown as (r: {
      includeNodeIds: string
      rootNodeId: number
      name: string
      startBizDate: string
      endBizDate: string
      projectEnv: string
      parallelism: boolean
    }) => Promise<{ body?: { requestId?: string } }>)({
      includeNodeIds: String(nodeID),
      rootNodeId: nodeID,
      name,
      startBizDate: day,
      endBizDate: day,
      projectEnv,
      parallelism: false,
    })
    return { status: "queued" as const, ...(resp?.body?.requestId ? { requestId: resp.body.requestId } : {}) }
  }

  private async writePauseSchedule(args: Readonly<Record<string, unknown>>) {
    const nodeId = requireInt(args.scheduleID ?? args.scheduleId ?? args.nodeID ?? args.nodeId, "scheduleID")
    const paused = args.paused === true || args.paused === "true" || args.paused === 1
    // UpdateNodeRunMode: 2 = freeze (pause), 0 = unfreeze (resume)
    const schedulerType = paused ? 2 : 0
    const projectEnv = typeof args.projectEnv === "string" && args.projectEnv ? args.projectEnv : "PROD"
    const resp = await (this.sdk.updateNodeRunMode as unknown as (r: {
      nodeId: number
      projectEnv: string
      schedulerType: number
    }) => Promise<{ body?: { requestId?: string } }>)({
      nodeId,
      projectEnv,
      schedulerType,
    })
    return { status: "ok" as const, ...(resp?.body?.requestId ? { requestId: resp.body.requestId } : {}) }
  }

  private async writeAlertSilence(args: Readonly<Record<string, unknown>>) {
    // Custom alert rules (Remind): useFlag=false silences; restore with useFlag=true.
    const alertRaw = args.alertID ?? args.alertId ?? args.remindId
    const remindId =
      typeof alertRaw === "number"
        ? alertRaw
        : typeof alertRaw === "string" && /^\d+$/.test(alertRaw)
          ? Number(alertRaw)
          : null
    if (remindId === null || !Number.isInteger(remindId)) {
      throw Object.assign(new Error("alertID must be integer remind id"), { code: "INVALIDPARAMETER" })
    }
    const silence = args.silence !== false && args.useFlag !== true
    const resp = await (this.sdk.updateRemind as unknown as (r: {
      remindId: number
      useFlag: boolean
    }) => Promise<{ body?: { requestId?: string } }>)({
      remindId,
      useFlag: !silence,
    })
    return { status: "ok" as const, ...(resp?.body?.requestId ? { requestId: resp.body.requestId } : {}) }
  }
}

function requireInt(value: unknown, field: string): number {
  const n = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN
  if (!Number.isInteger(n)) {
    throw Object.assign(new Error(`${field} must be integer`), { code: "INVALIDPARAMETER" })
  }
  return n
}

function requireString(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw Object.assign(new Error(`${field} required`), { code: "INVALIDPARAMETER" })
  }
  return value.trim()
}

// Cache: {connectionID|region} → entry; entry expires after 10 minutes idle.
export class OpenApiClientCache {
  private readonly entries = new Map<string, CachedClientEntry>()
  private readonly config: OpenApiClientConfig

  constructor(config: OpenApiClientConfig) {
    this.config = config
  }

  async acquire(connectionID: string, region: string): Promise<DataWorksClient> {
    const key = `${connectionID}|${region}`
    const now = Date.now()
    const existing = this.entries.get(key)
    if (existing && now - existing.usedAt <= TEN_MINUTES_MS) {
      this.entries.set(key, { client: existing.client, usedAt: now })
      return existing.client
    }

    const creds = await this.config.resolveCredentials(connectionID)
    if (!creds) {
      throw new Error(`no credentials resolved for connection ${connectionID}`)
    }
    const sdk = makeSdkClient(creds, region)
    const client = new OpenApiDataWorksClient(sdk, connectionID, region)
    this.entries.set(key, { client, usedAt: now })
    return client
  }

  invalidate(connectionID: string, region?: string): void {
    if (region) {
      this.entries.delete(`${connectionID}|${region}`)
      return
    }
    for (const key of this.entries.keys()) {
      if (key.startsWith(`${connectionID}|`)) this.entries.delete(key)
    }
  }

  pruneIdle(): void {
    const now = Date.now()
    for (const [key, entry] of this.entries) {
      if (now - entry.usedAt > TEN_MINUTES_MS) this.entries.delete(key)
    }
  }
}

// Type guards for safe mapping of typed errors to HTTP status codes.
export function dataWorksErrorStatus(error: DataWorksError): number {
  switch (error._tag) {
    case "Unauthorized":
      return 401
    case "Forbidden":
      return 403
    case "NotFound":
      return 404
    case "RateLimited":
      return 429
    case "UpstreamUnavailable":
      return 502
    case "InvalidResponse":
      return 502
  }
}

// Suppress unused declarations used by the type contract signature check.
export type { JobPage, JobStatus, Lineage, ProjectPage }
void Redacted
