import type { Database } from "../database"
import type { SecretStore } from "../secret/store"
import type { UserID } from "@dataworks-agent/core"
import { Redacted } from "effect"
import { authenticate } from "../auth/session"
import { checkOrigin } from "./csrf"
import { getDataConnection, resolveCredential } from "../data-connection/repo"
import { dataWorksErrorStatus, OpenApiClientCache } from "../dataworks/openapi"
import {
  makeService,
  parsePageNumber,
  parsePageSize,
  parseIntegerId,
  readModeFromEnv,
} from "../dataworks/service"
import type { DataWorksService } from "../dataworks/service"
import {
  OdpsPolicyError,
  OdpsSidecarError,
} from "../odps/service"
import {
  getSharedOdpsService,
  odpsEndpointForRegion,
  setOdpsServiceForTests,
} from "../odps/shared"
import type { QueryResult } from "../odps/protocol"

// Re-export test inject hook so existing tests can keep importing from dataworks-api.
export { setOdpsServiceForTests }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

function rejectIfForbidden(request: Request, publicOrigin: string): Response | null {
  if (!checkOrigin(request, publicOrigin)) return new Response(null, { status: 403 })
  return null
}

async function requireUser(request: Request, db: Database, publicOrigin: string) {
  const forbidden = rejectIfForbidden(request, publicOrigin)
  if (forbidden) return { response: forbidden, user: null }
  const user = await authenticate(request, db)
  if (!user) return { response: new Response(null, { status: 401 }), user: null }
  return { response: null, user }
}

function toErrorResponse(error: unknown): Response {
  if (error instanceof OdpsPolicyError) {
    return jsonResponse(
      { error: { _tag: "SqlPolicyDenied", code: error.code, message: error.message, token: error.token } },
      400,
    )
  }
  if (error instanceof OdpsSidecarError) {
    const status = error.code === "TIMEOUT" ? 504 : error.retryable ? 502 : 500
    return jsonResponse({ error: { _tag: "OdpsError", code: error.code, message: error.message } }, status)
  }
  if (
    error &&
    typeof error === "object" &&
    "_tag" in error &&
    typeof (error as { _tag: unknown })._tag === "string"
  ) {
    const status = dataWorksErrorStatus(error as Parameters<typeof dataWorksErrorStatus>[0])
    // Never include raw SDK response bodies — only sanitized message.
    const message = (error as { message?: string }).message ?? "dataworks error"
    return jsonResponse({ error: { _tag: (error as { _tag: string })._tag, message } }, status)
  }
  if (error instanceof Error) {
    // Treat validation errors as 400.
    if (error.message.includes("invalid") || error.message.includes("required")) {
      return jsonResponse({ error: { message: error.message } }, 400)
    }
  }
  return jsonResponse({ error: { message: "internal" } }, 500)
}

/** Param aliasing: accept both connectionID/connectionId and projectID/projectId. */
function paramConnectionID(url: URL): string | null {
  return url.searchParams.get("connectionID") ?? url.searchParams.get("connectionId")
}

function paramProjectID(url: URL): string | null {
  return url.searchParams.get("projectID") ?? url.searchParams.get("projectId")
}

function paramKeyword(url: URL): string | null {
  return url.searchParams.get("keyword")
}

async function buildService(
  mode: ReturnType<typeof readModeFromEnv>,
  db: Database,
  secrets: SecretStore,
  userID: UserID,
  connectionID: string | null,
): Promise<DataWorksService> {
  const openApiCache =
    mode === "dry-run"
      ? undefined
      : new OpenApiClientCache({
          resolveCredentials: async (id) => {
            const redacted = await resolveCredential(db, secrets, userID, id)
            if (!redacted) return null
            return {
              accessKeyId: Redacted.value(redacted.accessKeyId),
              accessKeySecret: Redacted.value(redacted.accessKeySecret),
            }
          },
        })
  return makeService({
    mode,
    ...(openApiCache ? { openApiCache } : {}),
    ...(connectionID ? { connectionID } : {}),
  })
}

export async function handleDataWorksRoute(
  request: Request,
  db: Database,
  secrets: SecretStore,
  publicOrigin: string,
): Promise<Response> {
  const url = new URL(request.url)
  const segments = url.pathname.split("/").filter(Boolean)
  // /api/dataworks/projects  → segments ["api", "dataworks", "projects"]
  // /api/dataworks/jobs      → segments ["api", "dataworks", "jobs"]
  // /api/dataworks/jobs/:id  → segments ["api", "dataworks", "jobs", "<id>"]
  // /api/dataworks/tables    → segments ["api", "dataworks", "tables"]
  // /api/dataworks/tables/:n → segments ["api", "dataworks", "tables", "<name>"]
  // /api/dataworks/sql       → segments ["api", "dataworks", "sql"]
  const kind = segments[2] ?? ""

  if (kind === "sql") {
    if (request.method !== "POST") return new Response(null, { status: 405 })
  } else if (request.method !== "GET") {
    return new Response(null, { status: 405 })
  }

  const auth = await requireUser(request, db, publicOrigin)
  if (auth.response || !auth.user) return auth.response ?? new Response(null, { status: 401 })
  const user = auth.user

  const mode = readModeFromEnv()
  const connectionID = paramConnectionID(url)

  // SQL body carries connectionId; for GET paths require connection up front in live modes.
  if (kind !== "sql" && mode !== "dry-run" && !connectionID) {
    return jsonResponse({ error: { message: "connectionID required" } }, 400)
  }

  try {
    if (kind === "projects") {
      if (!connectionID) return jsonResponse({ error: { message: "connectionID required" } }, 400)
      const cred = await resolveCredential(db, secrets, user.id, connectionID)
      if (!cred) return new Response(null, { status: 404 })

      const service = await buildService(mode, db, secrets, user.id, connectionID)
      const region = url.searchParams.get("region") ?? "cn-hangzhou"
      const pageNumber = parsePageNumber(url.searchParams.get("pageNumber"))
      const pageSize = parsePageSize(url.searchParams.get("pageSize"))
      const result = await service.listProjects({ region, pageNumber, pageSize })
      return jsonResponse(result.items)
    }

    if (kind === "jobs") {
      if (!connectionID) return jsonResponse({ error: { message: "connectionID required" } }, 400)
      const cred = await resolveCredential(db, secrets, user.id, connectionID)
      if (!cred) return new Response(null, { status: 404 })

      const service = await buildService(mode, db, secrets, user.id, connectionID)
      const connMeta = getDataConnection(db, connectionID, user.id)
      const region = url.searchParams.get("region") ?? connMeta?.region ?? "cn-hangzhou"
      const jobIdRaw = segments[3]
      if (!jobIdRaw) {
        const projectID = parseIntegerId(paramProjectID(url), "projectID")
        const pageNumber = parsePageNumber(url.searchParams.get("pageNumber"))
        const pageSize = parsePageSize(url.searchParams.get("pageSize"))
        const result = await service.listJobs({ projectID, pageNumber, pageSize, region })
        return jsonResponse(result.items)
      }

      const instanceID = parseIntegerId(jobIdRaw, "instanceID")
      const projectID = parseIntegerId(paramProjectID(url), "projectID")
      const result = await service.getJobStatus({ projectID, instanceID, region })
      return jsonResponse(result)
    }

    if (kind === "tables") {
      if (!connectionID) return jsonResponse({ error: { message: "connectionID required" } }, 400)
      const cred = await resolveCredential(db, secrets, user.id, connectionID)
      if (!cred) return new Response(null, { status: 404 })

      const service = await buildService(mode, db, secrets, user.id, connectionID)
      const connMeta = getDataConnection(db, connectionID, user.id)
      const region = url.searchParams.get("region") ?? connMeta?.region ?? "cn-hangzhou"
      const projectID = parseIntegerId(paramProjectID(url), "projectID")
      const projectName = url.searchParams.get("projectName")?.trim() || undefined
      const tableNameRaw = segments[3]

      if (!tableNameRaw) {
        const keyword = paramKeyword(url) ?? undefined
        const pageNumber = parsePageNumber(url.searchParams.get("pageNumber"))
        const pageSize = parsePageSize(url.searchParams.get("pageSize") ?? "50")
        const result = await service.listTables({
          projectID,
          pageNumber,
          pageSize,
          region,
          ...(keyword !== undefined ? { keyword } : {}),
          ...(projectName !== undefined ? { projectName } : {}),
        })
        return jsonResponse(result.items)
      }

      const tableName = decodeURIComponent(tableNameRaw)
      // Live describe needs MaxCompute project name to build tableGuid odps.<name>.<table>.
      if (mode !== "dry-run" && !projectName) {
        return jsonResponse(
          {
            error: {
              message:
                "projectName required for describeTable (MaxCompute project name from listProjects, not numeric project id)",
            },
          },
          400,
        )
      }
      const result = await service.describeTable({
        projectID,
        tableName,
        region,
        ...(projectName !== undefined ? { projectName } : {}),
      })
      return jsonResponse(result)
    }

    if (kind === "sql") {
      // Body: { connectionId|connectionID, projectId|projectID, sql, projectName?, maxRows?, timeoutMs? }
      let body: Record<string, unknown>
      try {
        body = (await request.json()) as Record<string, unknown>
      } catch {
        return jsonResponse({ error: { message: "invalid json body" } }, 400)
      }

      const bodyConnectionID =
        (typeof body.connectionID === "string" && body.connectionID) ||
        (typeof body.connectionId === "string" && body.connectionId) ||
        connectionID
      if (!bodyConnectionID) return jsonResponse({ error: { message: "connectionID required" } }, 400)

      const projectRaw =
        body.projectID !== undefined
          ? body.projectID
          : body.projectId !== undefined
            ? body.projectId
            : paramProjectID(url)
      const projectID = parseIntegerId(
        projectRaw === null || projectRaw === undefined ? null : String(projectRaw),
        "projectID",
      )

      const sql = typeof body.sql === "string" ? body.sql : ""
      if (!sql.trim()) return jsonResponse({ error: { message: "sql required" } }, 400)

      const cred = await resolveCredential(db, secrets, user.id, bodyConnectionID)
      if (!cred) return new Response(null, { status: 404 })

      const connMeta = getDataConnection(db, bodyConnectionID, user.id)
      const region = (typeof body.region === "string" && body.region) || connMeta?.region || "cn-hangzhou"
      // Live SQL requires a MaxCompute project *name* (not numeric DataWorks project id).
      // Prefer explicit body, then ODPS staging env; never silently fall back to String(projectID)
      // in live modes — that produces invalid ODPS project identifiers.
      const explicitProjectName =
        (typeof body.projectName === "string" && body.projectName.trim()) ||
        (typeof body.project === "string" && body.project.trim()) ||
        ""
      const stagingProject = process.env.DATAWORKS_ODPS_STAGING_PROJECT?.trim() || ""
      let projectName = explicitProjectName || stagingProject
      if (!projectName) {
        if (mode === "dry-run") {
          projectName = String(projectID)
        } else {
          return jsonResponse(
            {
              error: {
                message:
                  "projectName required for live SQL (MaxCompute project name from listProjects, not numeric project id)",
              },
            },
            400,
          )
        }
      }

      const maxRows =
        typeof body.maxRows === "number" && Number.isFinite(body.maxRows)
          ? Math.min(Math.max(1, Math.floor(body.maxRows)), 10_000)
          : 1_000
      const timeoutMs =
        typeof body.timeoutMs === "number" && Number.isFinite(body.timeoutMs)
          ? Math.min(Math.max(1_000, Math.floor(body.timeoutMs)), 300_000)
          : 30_000

      const odps = getSharedOdpsService()
      const result: QueryResult = await odps.query({
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

      return jsonResponse({
        columns: result.columns,
        rows: result.rows,
        truncated: result.truncated,
        instanceId: result.instance_id,
        durationMs: result.duration_ms,
      })
    }

    return new Response(null, { status: 404 })
  } catch (e) {
    return toErrorResponse(e)
  }
}

// Suppress unused parameter by exporting helpers for symmetry with sibling api modules.
export const _helpers = { toErrorResponse }

function _ensureUserID(): UserID {
  // Reference is required so eslint/tsc doesn't flag unused-import in environments that strip typeonly.
  return undefined as never as UserID
}
_ensureUserID()
