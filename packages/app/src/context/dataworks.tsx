import {
  type Accessor,
  createEffect,
  createMemo,
  createSignal,
  onCleanup,
  type ParentProps,
} from "solid-js"
import { createStore } from "solid-js/store"
import { createSimpleContext } from "@opencode-ai/ui/context"
import type { DataWorksUser } from "@/pages/dataworks/route"
import { Persist, persisted } from "@/utils/persist"

export type ListState = "idle" | "loading" | "ready" | "empty" | "partial" | "rate_limit" | "error"

export type DataConnection = {
  id: string
  userId: string
  name: string
  region: string
  accessKeyDisplay: string
  writeEnabled: boolean
  timeCreated: number
  timeUpdated: number
}

export type AuditEvent = {
  id: string
  userID: string
  connectionID: string
  sessionID: string | null
  tool: string
  permission: "read" | "write"
  argsHash: string
  reason: string | null
  outcome: "success" | "error" | "denied"
  errorCode: string | null
  durationMs: number
  timeCreated: number
}

export type DataWorksProject = {
  projectId: number | string
  projectName?: string
  name?: string
  id?: number | string
  region?: string
  envType?: string
  [key: string]: unknown
}

function normalizeProjectList(raw: unknown): DataWorksProject[] {
  const list = Array.isArray(raw) ? raw : []
  const out: DataWorksProject[] = []
  for (const item of list) {
    if (!item || typeof item !== "object") continue
    const record = item as Record<string, unknown>
    const idRaw = record.projectId ?? record.projectID ?? record.id
    if (idRaw === undefined || idRaw === null || idRaw === "") continue
    const projectId = typeof idRaw === "number" || typeof idRaw === "string" ? idRaw : String(idRaw)
    const nameRaw = record.projectName ?? record.name ?? record.projectIdentifier
    const projectName = typeof nameRaw === "string" && nameRaw.trim() ? nameRaw : String(projectId)
    out.push({
      ...record,
      projectId,
      projectName,
      name: projectName,
      id: projectId,
      ...(typeof record.region === "string" ? { region: record.region } : {}),
      ...(typeof record.envType === "string" ? { envType: record.envType } : {}),
    })
  }
  return out
}

export type DataWorksJob = {
  /** Primary list identity; for instance rows this is the instance id. */
  id?: number | string
  /** Required for dw_rerun_job / restartInstance — never substitute nodeId. */
  instanceId?: number | string
  /** Node id for supplement / pause (ListInstances includes this when available). */
  nodeId?: number | string
  jobId?: number | string
  scheduleId?: number | string
  status?: string
  name?: string
  projectId?: number | string
  [key: string]: unknown
}

export type DataWorksTable = {
  name: string
  schema?: string
  partition?: string
  projectId?: number | string
  projectName?: string
  tableGuid?: string
  type?: string
  [key: string]: unknown
}

export type DataWorksTableColumn = {
  name: string
  type: string
  comment?: string
  isPartition?: boolean
  isPrimaryKey?: boolean
}

export type DataWorksTableDescription = {
  name: string
  schema?: string
  projectName?: string
  tableGuid?: string
  comment?: string
  isPartitionTable?: boolean
  partition?: string
  columns: DataWorksTableColumn[]
  [key: string]: unknown
}

export type DataWorksSqlResult = {
  columns: Array<{ name: string; type: string } | string>
  rows: unknown[][]
  truncated: boolean
  instanceId?: string | null
  durationMs?: number
}

export function validConnectionID(saved: string | undefined, connections: Array<Pick<DataConnection, "id">>) {
  if (saved && connections.some((item) => item.id === saved)) return saved
  return connections[0]?.id
}

export function validProjectID(
  saved: string | undefined,
  projects: Array<Pick<DataWorksProject, "projectId" | "id">>,
) {
  if (saved && projects.some((item) => String(item.projectId ?? item.id) === saved)) return saved
  const first = projects[0]
  return first ? String(first.projectId ?? first.id) : undefined
}

export function projectRequestIsCurrent(
  connectionID: string,
  selectedConnectionID: string | undefined,
  requestID: number,
  currentRequestID: number,
) {
  return connectionID === selectedConnectionID && requestID === currentRequestID
}

export type KnowledgeDocument = {
  id: string
  name: string
  status: "pending" | "uploading" | "ready" | "error" | string
  progress?: number
  error?: string
}

export type FetchResult<T> =
  | { ok: true; data: T; status: number; partial?: boolean }
  | { ok: false; status: number; error: string; retryAfter?: number }

type ApiInit = RequestInit & { parse?: "json" | "void" }

async function controlFetch<T>(path: string, init: ApiInit = {}): Promise<FetchResult<T>> {
  const headers = new Headers(init.headers)
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json")
  }
  // Same-origin cookie session only — never localStorage tokens.
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers,
  })

  if (response.status === 429) {
    const retryAfter = Number(response.headers.get("retry-after") ?? "0")
    return {
      ok: false,
      status: 429,
      error: "rate_limit",
      retryAfter: Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined,
    }
  }

  if (!response.ok) {
    let error = `http_${response.status}`
    try {
      const body = (await response.json()) as { error?: string | { message?: string } }
      if (typeof body.error === "string") error = body.error
      else if (body.error && typeof body.error.message === "string") error = body.error.message
    } catch {
      // keep status-based message
    }
    return { ok: false, status: response.status, error }
  }

  if (init.parse === "void" || response.status === 204) {
    return { ok: true, data: undefined as T, status: response.status }
  }

  const data = (await response.json()) as T
  return { ok: true, data, status: response.status }
}

export const { use: useDataWorks, provider: DataWorksProvider } = createSimpleContext({
  name: "DataWorks",
  gate: false,
  init: () => {
    const [user, setUser] = createSignal<DataWorksUser | null | undefined>(undefined)
    const [connections, setConnections] = createSignal<DataConnection[]>([])
    const [connectionState, setConnectionState] = createSignal<ListState>("idle")
    const [selectedConnectionID, setSelectedConnectionID] = createSignal<string | undefined>()
    const [authError, setAuthError] = createSignal<string | undefined>()
    const [bootstrapState, setBootstrapState] = createSignal<ListState>("loading")
    const [projects, setProjects] = createSignal<DataWorksProject[]>([])
    const [projectState, setProjectState] = createSignal<ListState>("idle")
    const [selectedProjectID, setSelectedProjectID] = createSignal<string | undefined>()
    let projectRequest = 0
    const [savedScope, setSavedScope, , scopeReady] = persisted(
      Persist.window("dataworks.scope"),
      createStore<{ connectionID?: string; projectID?: string }>({}),
    )

    const selectedConnection = createMemo(() => {
      const id = selectedConnectionID()
      if (!id) return undefined
      return connections().find((item) => item.id === id)
    })

    const selectedProject = createMemo(() => {
      const id = selectedProjectID()
      if (!id) return undefined
      return projects().find((project) => {
        const keys = [project.projectId, project.id]
        return keys.some((key) => key !== undefined && key !== null && String(key) === id)
      })
    })

    async function refreshMe() {
      const result = await controlFetch<DataWorksUser>("/api/auth/me")
      if (!result.ok) {
        if (result.status === 401 || result.status === 403) {
          setUser(null)
          setBootstrapState("ready")
          return result
        }
        setAuthError(result.error)
        setBootstrapState("error")
        return result
      }
      setUser(result.data)
      setAuthError(undefined)
      setBootstrapState("ready")
      return result
    }

    async function login(email: string, password: string) {
      const result = await controlFetch<void>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
        parse: "void",
      })
      if (result.ok) await refreshMe()
      return result
    }

    async function logout() {
      await controlFetch<void>("/api/auth/logout", { method: "POST", parse: "void" })
      setUser(null)
      setConnections([])
      setSelectedConnectionID(undefined)
      setProjects([])
      setSelectedProjectID(undefined)
      setProjectState("idle")
    }

    async function refreshConnections() {
      setConnectionState("loading")
      const result = await controlFetch<DataConnection[]>("/api/data-connections")
      if (!result.ok) {
        setConnectionState(result.status === 429 ? "rate_limit" : "error")
        return result
      }
      setConnections(result.data)
      if (result.data.length === 0) {
        setConnectionState("empty")
        setSelectedConnectionID(undefined)
      } else {
        setConnectionState("ready")
        if (scopeReady.promise) await scopeReady.promise
        setSelectedConnectionID(validConnectionID(selectedConnectionID() ?? savedScope.connectionID, result.data))
      }
      await refreshProjects()
      return result
    }

    async function refreshProjects() {
      const requestID = ++projectRequest
      const connectionID = selectedConnectionID()
      if (!connectionID) {
        setProjects([])
        setSelectedProjectID(undefined)
        setProjectState("empty")
        return
      }
      setProjectState("loading")
      const result = await listProjects(connectionID, selectedConnection()?.region)
      if (!projectRequestIsCurrent(connectionID, selectedConnectionID(), requestID, projectRequest)) return result
      if (!result.ok) {
        setProjects([])
        setSelectedProjectID(undefined)
        setProjectState(result.status === 429 ? "rate_limit" : "error")
        return result
      }
      const items = result.data
      if (scopeReady.promise) await scopeReady.promise
      if (!projectRequestIsCurrent(connectionID, selectedConnectionID(), requestID, projectRequest)) return result
      const savedProjectID = savedScope.connectionID === connectionID ? savedScope.projectID : undefined
      setProjects(items)
      setProjectState(items.length ? "ready" : "empty")
      setSelectedProjectID(validProjectID(selectedProjectID() ?? savedProjectID, items))
      return result
    }

    function selectConnectionID(id: string | undefined) {
      if (id === selectedConnectionID()) return
      setSelectedConnectionID(id)
      setProjects([])
      setSelectedProjectID(undefined)
      setProjectState(id ? "loading" : "empty")
      if (id) void refreshProjects()
    }

    async function createConnection(input: {
      name: string
      region: string
      accessKeyId: string
      accessKeySecret: string
      writeEnabled: boolean
    }) {
      const result = await controlFetch<DataConnection>("/api/data-connections", {
        method: "POST",
        body: JSON.stringify(input),
      })
      if (result.ok) await refreshConnections()
      return result
    }

    async function removeConnection(id: string) {
      const result = await controlFetch<void>(`/api/data-connections/${encodeURIComponent(id)}`, {
        method: "DELETE",
        parse: "void",
      })
      if (result.ok) await refreshConnections()
      return result
    }

    async function listProjects(connectionID: string, region?: string) {
      const params = new URLSearchParams({ connectionID })
      if (region) params.set("region", region)
      const result = await controlFetch<unknown>(`/api/dataworks/projects?${params}`)
      if (!result.ok) return result
      return {
        ok: true as const,
        data: normalizeProjectList(result.data),
        status: result.status,
        partial: result.partial,
      }
    }

    async function listJobs(connectionID: string, projectID: string | number) {
      const params = new URLSearchParams({
        connectionID,
        projectID: String(projectID),
      })
      return controlFetch<DataWorksJob[]>(`/api/dataworks/jobs?${params}`)
    }

    async function getJobStatus(connectionID: string, projectID: string | number, instanceID: string | number) {
      const params = new URLSearchParams({
        connectionID,
        projectID: String(projectID),
      })
      return controlFetch<DataWorksJob>(
        `/api/dataworks/jobs/${encodeURIComponent(String(instanceID))}?${params}`,
      )
    }

    async function listTables(
      connectionID: string,
      projectID: string | number,
      input?: { keyword?: string; projectName?: string; region?: string },
    ) {
      const params = new URLSearchParams({
        connectionID,
        projectID: String(projectID),
      })
      if (input?.keyword) params.set("keyword", input.keyword)
      if (input?.projectName) params.set("projectName", input.projectName)
      if (input?.region) params.set("region", input.region)
      return controlFetch<DataWorksTable[]>(`/api/dataworks/tables?${params}`)
    }

    async function describeTable(
      connectionID: string,
      projectID: string | number,
      tableName: string,
      input?: { projectName?: string; region?: string },
    ) {
      const params = new URLSearchParams({
        connectionID,
        projectID: String(projectID),
      })
      if (input?.projectName) params.set("projectName", input.projectName)
      if (input?.region) params.set("region", input.region)
      return controlFetch<DataWorksTableDescription>(
        `/api/dataworks/tables/${encodeURIComponent(tableName)}?${params}`,
      )
    }

    async function runSql(input: {
      connectionID: string
      projectID: string | number
      sql: string
      projectName?: string
      region?: string
      maxRows?: number
      timeoutMs?: number
    }) {
      return controlFetch<DataWorksSqlResult>("/api/dataworks/sql", {
        method: "POST",
        body: JSON.stringify({
          connectionID: input.connectionID,
          projectID: input.projectID,
          sql: input.sql,
          ...(input.projectName ? { projectName: input.projectName } : {}),
          ...(input.region ? { region: input.region } : {}),
          ...(input.maxRows !== undefined ? { maxRows: input.maxRows } : {}),
          ...(input.timeoutMs !== undefined ? { timeoutMs: input.timeoutMs } : {}),
        }),
      })
    }

    async function listAudit(input?: { connectionID?: string; limit?: number; userID?: string }) {
      const params = new URLSearchParams()
      if (input?.connectionID) params.set("connectionID", input.connectionID)
      if (input?.limit) params.set("limit", String(input.limit))
      if (input?.userID) params.set("userID", input.userID)
      const query = params.toString()
      return controlFetch<AuditEvent[]>(`/api/audit${query ? `?${query}` : ""}`)
    }

    /**
     * Issue a write ticket after the user supplies a reason (control plane cookie session).
     * OpenCode permission reply remains separate and travels under `/opencode`.
     */
    async function issueWriteTicket(input: {
      connectionID: string
      sessionID?: string | null
      tool: string
      argsHash: string
      reason: string
    }) {
      return controlFetch<{ ticket: string; timeExpires?: number; expiresAt?: number }>("/api/write-tickets", {
        method: "POST",
        body: JSON.stringify(input),
      })
    }

    /**
     * Browser write path: ticket + execute + audit (same control-plane security as plugin tools).
     * `args` must match the ticket argsHash (canonical JSON).
     */
    async function executeWrite(input: {
      ticket: string
      connectionID: string
      sessionID?: string | null
      tool: string
      args: Record<string, unknown>
    }) {
      return controlFetch<{ status: string; dryRun?: boolean; requestId?: string }>("/api/dataworks/write", {
        method: "POST",
        body: JSON.stringify({
          ticket: input.ticket,
          connectionID: input.connectionID,
          sessionID: input.sessionID ?? null,
          tool: input.tool,
          args: input.args,
        }),
      })
    }

    async function recordWriteRejection(input: {
      connectionID: string
      sessionID?: string | null
      tool: string
      argsHash: string
    }) {
      const result = await controlFetch<unknown>("/api/audit/write-reject", {
        method: "POST",
        body: JSON.stringify({
          connectionID: input.connectionID,
          sessionID: input.sessionID ?? null,
          tool: input.tool,
          argsHash: input.argsHash,
        }),
      })
      if (result.ok || result.status === 404 || result.status === 405) {
        return { ok: true as const, data: undefined, status: result.ok ? result.status : 204 }
      }
      return result
    }

    // Initial session bootstrap — cookie only.
    void refreshMe().then((result) => {
      if (result.ok) void refreshConnections()
    })

    // Never write credentials/tokens into localStorage.
    createEffect(() => {
      // Touch user so HMR doesn't drop the signal, but do not persist it.
      void user()
    })

    createEffect(() => {
      if (!scopeReady()) return
      if (connectionState() !== "ready" && connectionState() !== "empty") return
      if (projectState() !== "ready" && projectState() !== "empty") return
      const connectionID = selectedConnectionID()
      const projectID = selectedProjectID()
      if (connectionID !== validConnectionID(connectionID, connections())) return
      if (projectID !== validProjectID(projectID, projects())) return
      setSavedScope({ connectionID, projectID })
    })

    onCleanup(() => {
      // no timers by default
    })

    return {
      user: user as Accessor<DataWorksUser | null | undefined>,
      authError,
      bootstrapState,
      connections,
      connectionState,
      selectedConnectionID,
      selectedConnection,
      setSelectedConnectionID: selectConnectionID,
      projects,
      projectState,
      selectedProjectID,
      selectedProject,
      setSelectedProjectID,
      refreshProjects,
      refreshMe,
      login,
      logout,
      refreshConnections,
      createConnection,
      removeConnection,
      listProjects,
      listJobs,
      getJobStatus,
      listTables,
      describeTable,
      runSql,
      listAudit,
      issueWriteTicket,
      executeWrite,
      recordWriteRejection,
      controlFetch,
    }
  },
})

export function DataWorksOptional(props: ParentProps) {
  return <DataWorksProvider>{props.children}</DataWorksProvider>
}
