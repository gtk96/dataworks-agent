import { hashAuditArgs, type UserID } from "@dataworks-agent/core"
import type { Database } from "../database"
import type { SecretStore } from "../secret/store"
import { AuditRepo } from "../audit/repo"
import { resolveCredential } from "../data-connection/repo"
import { executeDataWorksWrite, makeService, readModeFromEnv } from "../dataworks/service"
import { dataWorksErrorStatus, OpenApiClientCache } from "../dataworks/openapi"
import { Redacted } from "effect"
import { verifyWorkerToken } from "../worker/token"
import { WriteTicketDeniedError, WriteTicketService } from "../write-ticket/service"
import {
  OdpsPolicyError,
  OdpsSidecarError,
} from "../odps/service"
import { getSharedOdpsService, odpsEndpointForRegion } from "../odps/shared"

interface IssueTicketBody {
  connectionID: string
  sessionID?: string | null
  tool: string
  argsHash: string
  reason: string
}

interface ExecuteBody {
  ticket?: string
  connectionID: string
  sessionID?: string | null
  tool: string
  args: Readonly<Record<string, unknown>>
}

// Read-only tool names served by the internal execute endpoint. These do not
// require a write ticket — only a valid worker token. Adding a tool here is
// the only place the control plane needs to know about new read endpoints.
const READ_TOOLS = new Set<string>([
  "dw_list_projects",
  "dw_list_tables",
  "dw_describe_table",
  "dw_table_lineage",
  "dw_list_jobs",
  "dw_get_job_status",
  "dw_alert_list",
  "dw_mcp_call",
  // Read-only query path (no write ticket). Full ODPS execution is Task-scoped;
  // until wired, the control plane returns an empty result set.
  "dw_run_sql",
])

export async function handleWriteTicketRoute(
  request: Request,
  db: Database,
  publicOrigin: string,
): Promise<Response> {
  if (request.method !== "POST") return new Response(null, { status: 405 })
  if (!checkOrigin(request, publicOrigin)) return new Response(null, { status: 403 })
  const user = await authenticate(request, db)
  if (!user) return new Response(null, { status: 401 })
  const body = await parseJson<IssueTicketBody>(request)
  if (!body || !isIssueTicketBody(body)) return json({ error: "invalid_request" }, 400)
  if (!body.reason.trim()) return json({ error: "reason_required" }, 400)

  try {
    const issued = new WriteTicketService(db).issue({
      userID: user.id,
      connectionID: body.connectionID,
      sessionID: body.sessionID ?? null,
      tool: body.tool,
      argsHash: body.argsHash,
      reason: body.reason,
    })
    return json(issued, 201)
  } catch (error) {
    if (error instanceof WriteTicketDeniedError) {
      if (error.code === "reason_required") return json({ error: error.code }, 400)
      return json({ error: error.code }, 403)
    }
    throw error
  }
}

/**
 * Browser cookie-session write execute: reason already embedded in ticket;
 * consume ticket + OpenAPI/dry-run write + audit (same security as worker path).
 */
export async function handleBrowserWriteExecuteRoute(
  request: Request,
  db: Database,
  publicOrigin: string,
  secrets: SecretStore,
): Promise<Response> {
  if (request.method !== "POST") return new Response(null, { status: 405 })
  if (!checkOrigin(request, publicOrigin)) return new Response(null, { status: 403 })
  const user = await authenticate(request, db)
  if (!user) return new Response(null, { status: 401 })

  const body = await parseJson<ExecuteBody>(request)
  if (!body || !isExecuteBody(body) || !body.ticket) {
    return json({ error: "invalid_request" }, 400)
  }

  return runWriteExecute({
    db,
    secrets,
    userID: user.id,
    body,
  })
}

/** Browser reject audit (cookie session) — mirrors internal write-reject. */
export async function handleBrowserWriteRejectRoute(
  request: Request,
  db: Database,
  publicOrigin: string,
): Promise<Response> {
  if (request.method !== "POST") return new Response(null, { status: 405 })
  if (!checkOrigin(request, publicOrigin)) return new Response(null, { status: 403 })
  const user = await authenticate(request, db)
  if (!user) return new Response(null, { status: 401 })

  const body = await parseJson<{
    connectionID: string
    sessionID?: string | null
    tool: string
    argsHash: string
  }>(request)
  if (
    !body
    || typeof body.connectionID !== "string"
    || typeof body.tool !== "string"
    || typeof body.argsHash !== "string"
  ) {
    return json({ error: "invalid_request" }, 400)
  }

  new AuditRepo(db).append({
    userID: user.id,
    connectionID: body.connectionID,
    sessionID: body.sessionID ?? null,
    tool: body.tool,
    permission: "write",
    argsHash: body.argsHash,
    reason: null,
    outcome: "denied",
    errorCode: "rejected",
    durationMs: 0,
  })
  return json({ ok: true })
}

export async function handleAuditRoute(
  request: Request,
  db: Database,
  publicOrigin: string,
): Promise<Response> {
  if (request.method !== "GET") return new Response(null, { status: 405 })
  if (!checkOrigin(request, publicOrigin)) return new Response(null, { status: 403 })
  const user = await authenticate(request, db)
  if (!user) return new Response(null, { status: 401 })
  const url = new URL(request.url)
  const limit = Number(url.searchParams.get("limit") ?? "100")
  if (!Number.isInteger(limit) || limit < 1) return json({ error: "invalid_limit" }, 400)
  return json(new AuditRepo(db).list({
    userID: user.id,
    ...(url.searchParams.get("connectionID")
      ? { connectionID: url.searchParams.get("connectionID")! }
      : {}),
    limit,
  }))
}

export async function handleInternalDataWorksExecuteRoute(
  request: Request,
  db: Database,
  workerTokenSecret: Uint8Array,
  secrets: SecretStore,
): Promise<Response> {
  if (request.headers.has("cookie")) return new Response(null, { status: 403 })
  if (request.method !== "POST") return new Response(null, { status: 405 })
  const authorization = request.headers.get("authorization")
  const workerID = request.headers.get("x-dataworks-worker-id")
  if (!authorization?.startsWith("Bearer ") || !workerID) return new Response(null, { status: 401 })
  const worker = verifyWorkerToken(workerTokenSecret, authorization.slice(7), workerID)
  if (!worker) return new Response(null, { status: 401 })

  const body = await parseJson<ExecuteBody>(request)
  if (!body || !isExecuteBody(body)) return json({ error: "invalid_request" }, 400)

  if (READ_TOOLS.has(body.tool)) {
    return handleReadTool(request, db, secrets, worker, body)
  }

  if (!body.ticket) return json({ error: "write_ticket_required" }, 403)
  return handleWriteTool(db, body, worker, secrets)
}

/** Worker-facing write ticket issue (after PermissionV1 approve + reason). */
export async function handleInternalWriteTicketRoute(
  request: Request,
  db: Database,
  workerTokenSecret: Uint8Array,
): Promise<Response> {
  if (request.headers.has("cookie")) return new Response(null, { status: 403 })
  if (request.method !== "POST") return new Response(null, { status: 405 })
  const authorization = request.headers.get("authorization")
  const workerID = request.headers.get("x-dataworks-worker-id")
  if (!authorization?.startsWith("Bearer ") || !workerID) return new Response(null, { status: 401 })
  const worker = verifyWorkerToken(workerTokenSecret, authorization.slice(7), workerID)
  if (!worker) return new Response(null, { status: 401 })

  const body = await parseJson<IssueTicketBody>(request)
  if (!body || !isIssueTicketBody(body)) return json({ error: "invalid_request" }, 400)
  if (!body.reason.trim()) return json({ error: "reason_required" }, 400)

  try {
    const issued = new WriteTicketService(db).issue({
      userID: worker.userID as UserID,
      connectionID: body.connectionID,
      sessionID: body.sessionID ?? null,
      tool: body.tool,
      argsHash: body.argsHash,
      reason: body.reason,
    })
    return json(issued, 201)
  } catch (error) {
    if (error instanceof WriteTicketDeniedError) {
      if (error.code === "reason_required") return json({ error: error.code }, 400)
      return json({ error: error.code }, 403)
    }
    throw error
  }
}

/** Worker-facing connection metadata (writeEnabled flag only). */
export async function handleInternalConnectionMetaRoute(
  request: Request,
  db: Database,
  workerTokenSecret: Uint8Array,
  connectionID: string,
): Promise<Response> {
  if (request.headers.has("cookie")) return new Response(null, { status: 403 })
  if (request.method !== "GET") return new Response(null, { status: 405 })
  const authorization = request.headers.get("authorization")
  const workerID = request.headers.get("x-dataworks-worker-id")
  if (!authorization?.startsWith("Bearer ") || !workerID) return new Response(null, { status: 401 })
  const worker = verifyWorkerToken(workerTokenSecret, authorization.slice(7), workerID)
  if (!worker) return new Response(null, { status: 401 })

  const row = db.get<{ write_enabled: number }>(
    "SELECT write_enabled FROM dwa_data_connection WHERE id = ? AND user_id = ?",
    [connectionID, worker.userID],
  )
  if (!row) return json({ error: "connection_not_found" }, 404)
  return json({ writeEnabled: row.write_enabled === 1 })
}

/** Record a rejected write permission (no ticket, no execute). */
export async function handleInternalWriteRejectAuditRoute(
  request: Request,
  db: Database,
  workerTokenSecret: Uint8Array,
): Promise<Response> {
  if (request.headers.has("cookie")) return new Response(null, { status: 403 })
  if (request.method !== "POST") return new Response(null, { status: 405 })
  const authorization = request.headers.get("authorization")
  const workerID = request.headers.get("x-dataworks-worker-id")
  if (!authorization?.startsWith("Bearer ") || !workerID) return new Response(null, { status: 401 })
  const worker = verifyWorkerToken(workerTokenSecret, authorization.slice(7), workerID)
  if (!worker) return new Response(null, { status: 401 })

  const body = await parseJson<{
    connectionID: string
    sessionID?: string | null
    tool: string
    argsHash: string
  }>(request)
  if (
    !body
    || typeof body.connectionID !== "string"
    || typeof body.tool !== "string"
    || typeof body.argsHash !== "string"
  ) {
    return json({ error: "invalid_request" }, 400)
  }

  new AuditRepo(db).append({
    userID: worker.userID as UserID,
    connectionID: body.connectionID,
    sessionID: body.sessionID ?? null,
    tool: body.tool,
    permission: "write",
    argsHash: body.argsHash,
    reason: null,
    outcome: "denied",
    errorCode: "rejected",
    durationMs: 0,
  })
  return json({ ok: true })
}

async function handleReadTool(
  request: Request,
  db: Database,
  secrets: SecretStore,
  worker: { userID: string },
  body: ExecuteBody,
): Promise<Response> {
  const args = body.args as Record<string, unknown>
  const connectionID = body.connectionID
  if (typeof args.region !== "string" && !["dw_list_jobs", "dw_get_job_status", "dw_list_tables", "dw_describe_table", "dw_table_lineage", "dw_alert_list", "dw_run_sql"].includes(body.tool)) {
    args.region = "cn-hangzhou"
  }

  const cred = await resolveCredential(db, secrets, worker.userID as UserID, connectionID)
  if (!cred) return json({ error: "connection_not_found" }, 404)

  const mode = readModeFromEnv()
  try {
    if (body.tool === "dw_run_sql") {
      const sql = typeof args.sql === "string" ? args.sql : ""
      const projectID = Number(args.projectID)
      const region = typeof args.region === "string" ? args.region : "cn-hangzhou"
      const explicitProjectName =
        (typeof args.projectName === "string" && args.projectName.trim()) ||
        (typeof args.project === "string" && args.project.trim()) ||
        ""
      const stagingProject = process.env.DATAWORKS_ODPS_STAGING_PROJECT?.trim() || ""
      let projectName = explicitProjectName || stagingProject
      if (!projectName) {
        if (mode === "dry-run") {
          projectName = Number.isFinite(projectID) ? String(projectID) : "dry-run"
        } else {
          return json(
            {
              error: {
                message:
                  "projectName required for live SQL (MaxCompute project name, not numeric project id)",
              },
            },
            400,
          )
        }
      }
      const maxRows =
        typeof args.maxRows === "number" && Number.isFinite(args.maxRows)
          ? Math.min(Math.max(1, Math.floor(args.maxRows)), 10_000)
          : 1_000
      const timeoutMs =
        typeof args.timeoutMs === "number" && Number.isFinite(args.timeoutMs)
          ? Math.min(Math.max(1_000, Math.floor(args.timeoutMs)), 300_000)
          : 30_000
      const odps = getSharedOdpsService()
      const result = await odps.query({
        credential: {
          accessKeyId: Redacted.value(cred.accessKeyId),
          accessKeySecret: Redacted.value(cred.accessKeySecret),
        },
        endpoint: odpsEndpointForRegion(region),
        project: projectName,
        sql,
        maxRows,
        timeoutMs,
        maxBytes: 10 * 1024 * 1024,
      })
      return json({
        columns: result.columns,
        rows: result.rows,
        truncated: result.truncated,
        instanceId: result.instance_id,
        durationMs: result.duration_ms,
      })
    }

    const openApiCache =
      mode === "dry-run"
        ? undefined
        : new OpenApiClientCache({
            resolveCredentials: async (id) => {
              const redacted = await resolveCredential(db, secrets, worker.userID as UserID, id)
              if (!redacted) return null
              return {
                accessKeyId: Redacted.value(redacted.accessKeyId),
                accessKeySecret: Redacted.value(redacted.accessKeySecret),
              }
            },
          })
    const service = await makeService({
      mode,
      ...(openApiCache ? { openApiCache } : {}),
      connectionID,
    })
    const result = await dispatchRead(body.tool, service, args)
    return json(result)
  } catch (error) {
    if (error instanceof OdpsPolicyError) {
      return json(
        { error: { _tag: "SqlPolicyDenied", code: error.code, message: error.message, token: error.token } },
        400,
      )
    }
    if (error instanceof OdpsSidecarError) {
      const status = error.code === "TIMEOUT" ? 504 : error.retryable ? 502 : 500
      return json({ error: { _tag: "OdpsError", code: error.code, message: error.message } }, status)
    }
    if (error && typeof error === "object" && "_tag" in error) {
      const status = dataWorksErrorStatus(error as Parameters<typeof dataWorksErrorStatus>[0])
      return json({ error: { _tag: (error as { _tag: string })._tag, message: (error as { message?: string }).message ?? "dataworks error" } }, status)
    }
    return json({ error: "dataworks_read_failed" }, 500)
  }
  void request
}

async function dispatchRead(
  tool: string,
  service: Awaited<ReturnType<typeof makeService>>,
  args: Record<string, unknown>,
): Promise<unknown> {
  switch (tool) {
    case "dw_list_projects":
      return service.listProjects({
        region: (args.region as string) ?? "cn-hangzhou",
        pageNumber: (args.page as number) ?? 1,
        pageSize: (args.pageSize as number) ?? 10,
      })
    case "dw_list_jobs":
      return service.listJobs({
        projectID: args.projectID as number,
        pageNumber: (args.page as number) ?? 1,
        pageSize: (args.pageSize as number) ?? 10,
        region: (args.region as string) ?? "cn-hangzhou",
      })
    case "dw_get_job_status":
      return service.getJobStatus({
        projectID: args.projectID as number,
        instanceID: args.instanceID as number,
        region: (args.region as string) ?? "cn-hangzhou",
      })
    case "dw_table_lineage":
      return service.tableLineage({
        projectID: args.projectID as number,
        tableName: args.tableName as string,
        region: (args.region as string) ?? "cn-hangzhou",
      })
    case "dw_list_tables":
      return service.listTables({
        projectID: args.projectID as number,
        pageNumber: (args.page as number) ?? 1,
        pageSize: (args.pageSize as number) ?? 50,
        region: (args.region as string) ?? "cn-hangzhou",
        ...(typeof args.keyword === "string" ? { keyword: args.keyword } : {}),
        ...(typeof args.projectName === "string" ? { projectName: args.projectName } : {}),
      })
    case "dw_describe_table":
      return service.describeTable({
        projectID: args.projectID as number,
        tableName: args.tableName as string,
        region: (args.region as string) ?? "cn-hangzhou",
        ...(typeof args.projectName === "string" ? { projectName: args.projectName } : {}),
      })
    default:
      return { items: [] }
  }
}

async function handleWriteTool(
  db: Database,
  body: ExecuteBody,
  worker: { userID: string },
  secrets: SecretStore,
): Promise<Response> {
  return runWriteExecute({
    db,
    secrets,
    userID: worker.userID as UserID,
    body,
  })
}

async function runWriteExecute(input: {
  db: Database
  secrets: SecretStore
  userID: UserID
  body: ExecuteBody
}): Promise<Response> {
  const { db, secrets, userID, body } = input
  const argsHash = hashAuditArgs(body.args)
  const consumed = new WriteTicketService(db).consume({
    ticket: body.ticket!,
    userID,
    connectionID: body.connectionID,
    sessionID: body.sessionID ?? null,
    tool: body.tool,
    argsHash,
  })
  if (!consumed) return json({ error: "write_ticket_invalid_or_consumed" }, 409)

  const connMeta = db.get<{ region: string; write_enabled: number }>(
    "SELECT region, write_enabled FROM dwa_data_connection WHERE id = ? AND user_id = ?",
    [body.connectionID, userID],
  )
  if (!connMeta) {
    new AuditRepo(db).append({
      userID: consumed.userID,
      connectionID: consumed.connectionID,
      sessionID: consumed.sessionID,
      tool: consumed.tool,
      permission: "write",
      argsHash: consumed.argsHash,
      reason: consumed.reason,
      outcome: "denied",
      errorCode: "connection_not_found",
      durationMs: 0,
    })
    return json({ error: "connection_not_found" }, 404)
  }
  if (!connMeta.write_enabled) {
    new AuditRepo(db).append({
      userID: consumed.userID,
      connectionID: consumed.connectionID,
      sessionID: consumed.sessionID,
      tool: consumed.tool,
      permission: "write",
      argsHash: consumed.argsHash,
      reason: consumed.reason,
      outcome: "denied",
      errorCode: "write_disabled",
      durationMs: 0,
    })
    return json({ error: "write_disabled" }, 403)
  }

  const started = performance.now()
  try {
    const result = await executeDataWorksWrite({
      ticket: consumed,
      tool: body.tool,
      args: body.args,
      region: connMeta.region,
      resolveCredentials: async (id) => {
        const redacted = await resolveCredential(db, secrets, userID, id)
        if (!redacted) return null
        return {
          accessKeyId: Redacted.value(redacted.accessKeyId),
          accessKeySecret: Redacted.value(redacted.accessKeySecret),
        }
      },
    })
    new AuditRepo(db).append({
      userID: consumed.userID,
      connectionID: consumed.connectionID,
      sessionID: consumed.sessionID,
      tool: consumed.tool,
      permission: "write",
      argsHash: consumed.argsHash,
      reason: consumed.reason,
      outcome: "success",
      errorCode: null,
      durationMs: Math.max(0, Math.round(performance.now() - started)),
    })
    return json(result)
  } catch (error) {
    const errorCode =
      error instanceof Error
        ? ("code" in error && typeof (error as { code?: unknown }).code === "string"
            ? String((error as { code: string }).code)
            : error.name)
        : "unknown_error"
    new AuditRepo(db).append({
      userID: consumed.userID,
      connectionID: consumed.connectionID,
      sessionID: consumed.sessionID,
      tool: consumed.tool,
      permission: "write",
      argsHash: consumed.argsHash,
      reason: consumed.reason,
      outcome: "error",
      errorCode,
      durationMs: Math.max(0, Math.round(performance.now() - started)),
    })
    if (error instanceof Error && error.name === "DataWorksWriteDeniedError") {
      return json({ error: error.message }, 403)
    }
    if (error && typeof error === "object" && "_tag" in error) {
      const status = dataWorksErrorStatus(error as Parameters<typeof dataWorksErrorStatus>[0])
      return json(
        {
          error: {
            _tag: (error as { _tag: string })._tag,
            message: (error as { message?: string }).message ?? "dataworks write failed",
          },
        },
        status,
      )
    }
    return json({ error: "dataworks_write_failed" }, 500)
  }
}

function json(body: unknown, status = 200) {
  return Response.json(body, { status })
}

function parseJson<T>(request: Request): Promise<T | null> {
  return request.json().then((body) => body as T, () => null)
}

function isIssueTicketBody(body: IssueTicketBody) {
  return typeof body.connectionID === "string"
    && typeof body.tool === "string"
    && typeof body.argsHash === "string"
    && typeof body.reason === "string"
    && (body.sessionID === undefined || body.sessionID === null || typeof body.sessionID === "string")
}

function isExecuteBody(body: ExecuteBody) {
  return typeof body.connectionID === "string"
    && typeof body.tool === "string"
    && typeof body.args === "object"
    && body.args !== null
    && !Array.isArray(body.args)
    && (body.ticket === undefined || typeof body.ticket === "string")
    && (body.sessionID === undefined || body.sessionID === null || typeof body.sessionID === "string")
}

function checkOrigin(request: Request, publicOrigin: string): boolean {
  const origin = request.headers.get("origin")
  if (!origin) return true
  return origin === publicOrigin
}

async function authenticate(request: Request, db: Database) {
  const { authenticate: auth } = await import("../auth/session")
  return auth(request, db)
}