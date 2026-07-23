import { Hono } from "hono"
import { join } from "path"
import type { Database } from "../database"
import { makeDatabase } from "../database"
import { makeSecretStore, SecretStore } from "../secret/store"
import { loadOrCreateMasterKey, type SystemKeyringBackend } from "../secret/keyring"
import { handleLogin, handleLogout, handleMe } from "./auth-api"
import { handleDataConnectionsRoute } from "./data-connection-api"
import { handleDataWorksRoute } from "./dataworks-api"
import {
  handleAuditRoute,
  handleBrowserWriteExecuteRoute,
  handleBrowserWriteRejectRoute,
  handleInternalConnectionMetaRoute,
  handleInternalDataWorksExecuteRoute,
  handleInternalWriteRejectAuditRoute,
  handleInternalWriteTicketRoute,
  handleWriteTicketRoute,
} from "./audit-api"
import { handleLlmConnectionsRoute } from "./llm-connection-api"
import { handleLlmGatewayRoute } from "./llm-gateway-api"
import { handleSkillsRoute } from "./skill-api"
import { handleInternalKnowledgeSearchRoute, handleKnowledgeRoute } from "./knowledge-api"
import { createUser as createUserImpl, authenticate as authenticateImpl } from "../auth/session"
import { createWorkerBackend, type WorkerBackend } from "../worker/backend"
import { createSupervisor, type WorkerSupervisor } from "../worker/supervisor"
import { deriveWorkerTokenSecret } from "../worker/token"
import {
  proxyWorkerHttp,
  handleEgressTest,
  isWebSocketUpgrade,
  type ProxyContext,
} from "../proxy/http"
import {
  proxyWorkerWebSocket,
  workerWebSocketHandlers,
  type WorkerWsProxyData,
} from "../proxy/websocket"
import type { UserID } from "@dataworks-agent/core"

export interface WorkerConfig {
  appDataRoot: string
  mode: "native" | "oci"
  workerScript?: string
  ociImage?: string
  approvedProjectRoots?: string[]
  allowedEgressHostnames?: string[]
}

export interface AppConfig {
  dbPath: string
  publicOrigin: string
  migrationsDir?: string
  secretsRoot?: string
  masterKey?: Uint8Array
  workerTokenSecret?: Uint8Array
  keyringBackend?: SystemKeyringBackend
  worker?: WorkerConfig
  /** App-data root for system/user skills. */
  appDataRoot?: string
  startServer?: boolean
  /** Bind host when startServer is enabled. Defaults to all interfaces / Bun default. */
  host?: string
  /** Bind port when startServer is enabled. Defaults to 0 (ephemeral, for tests). */
  port?: number
}

export interface AppHandle {
  readonly app: Hono
  readonly db: Database
  readonly secrets: SecretStore
  readonly workerBackend?: WorkerBackend
  readonly workerSupervisor?: WorkerSupervisor
  readonly server: { port: number; stop: () => void } | null
  readonly publicOrigin: string
}

interface ProxyState {
  backend: WorkerBackend
  supervisor: WorkerSupervisor
  allowedHostnames?: Set<string> | undefined
  publicOrigin: string
  db: Database
}

async function buildProxy(
  req: Request,
  state: ProxyState,
): Promise<{ userId: UserID; ctx: ProxyContext } | null> {
  const user = await authenticateImpl(req, state.db)
  if (!user) return null
  const handle = await state.supervisor.acquire(user.id)
  const ctx: ProxyContext = {
    workerUrl: handle.url,
    workerAuth: handle.authorization,
    publicOrigin: state.publicOrigin,
  }
  if (state.allowedHostnames) ctx.allowedHostnames = state.allowedHostnames
  return {
    userId: user.id,
    ctx,
  }
}

export async function makeApp(config: AppConfig): Promise<AppHandle> {
  const migrationsDir = config.migrationsDir ?? join(import.meta.dir, "..", "..", "migration")
  const secretsRoot = config.secretsRoot ?? join(import.meta.dir, "..", "..", ".secrets")
  const db = await makeDatabase({ dbPath: config.dbPath, migrationsDir })

  const masterKey =
    config.masterKey ??
    (await loadOrCreateMasterKey(config.keyringBackend ? { backend: config.keyringBackend } : {}))
  const workerTokenSecret = config.workerTokenSecret ?? deriveWorkerTokenSecret(masterKey)
  const secrets = await makeSecretStore({ root: secretsRoot, masterKey })

  const app = new Hono()

  const originHolder: { value: string } = { value: config.publicOrigin }
  const effectivePublicOrigin = () => originHolder.value

  app.post("/api/auth/login", async (c) => handleLogin(c.req.raw, db, effectivePublicOrigin()))
  app.post("/api/auth/logout", async (c) => handleLogout(c.req.raw, db, effectivePublicOrigin()))
  app.get("/api/auth/me", async (c) => handleMe(c.req.raw, db, effectivePublicOrigin()))

  app.all("/api/data-connections", async (c) =>
    handleDataConnectionsRoute(c.req.raw, db, effectivePublicOrigin(), secrets),
  )
  app.all("/api/data-connections/:id", async (c) =>
    handleDataConnectionsRoute(c.req.raw, db, effectivePublicOrigin(), secrets),
  )
  app.all("/api/dataworks/projects", async (c) =>
    handleDataWorksRoute(c.req.raw, db, secrets, effectivePublicOrigin()),
  )
  app.all("/api/dataworks/jobs", async (c) =>
    handleDataWorksRoute(c.req.raw, db, secrets, effectivePublicOrigin()),
  )
  app.all("/api/dataworks/jobs/:id", async (c) =>
    handleDataWorksRoute(c.req.raw, db, secrets, effectivePublicOrigin()),
  )
  app.all("/api/dataworks/tables", async (c) =>
    handleDataWorksRoute(c.req.raw, db, secrets, effectivePublicOrigin()),
  )
  app.all("/api/dataworks/tables/:name", async (c) =>
    handleDataWorksRoute(c.req.raw, db, secrets, effectivePublicOrigin()),
  )
  app.all("/api/dataworks/sql", async (c) =>
    handleDataWorksRoute(c.req.raw, db, secrets, effectivePublicOrigin()),
  )
  app.all("/api/write-tickets", async (c) => handleWriteTicketRoute(c.req.raw, db, effectivePublicOrigin()))
  app.all("/api/dataworks/write", async (c) =>
    handleBrowserWriteExecuteRoute(c.req.raw, db, effectivePublicOrigin(), secrets),
  )
  app.all("/api/audit/write-reject", async (c) =>
    handleBrowserWriteRejectRoute(c.req.raw, db, effectivePublicOrigin()),
  )
  app.all("/api/audit", async (c) => handleAuditRoute(c.req.raw, db, effectivePublicOrigin()))
  app.all("/internal/dataworks/execute", async (c) =>
    handleInternalDataWorksExecuteRoute(c.req.raw, db, workerTokenSecret, secrets),
  )
  app.all("/internal/dataworks/write-tickets", async (c) =>
    handleInternalWriteTicketRoute(c.req.raw, db, workerTokenSecret),
  )
  app.all("/internal/dataworks/write-reject", async (c) =>
    handleInternalWriteRejectAuditRoute(c.req.raw, db, workerTokenSecret),
  )
  app.get("/internal/dataworks/connections/:id", async (c) =>
    handleInternalConnectionMetaRoute(c.req.raw, db, workerTokenSecret, c.req.param("id")),
  )
  app.all("/api/llm-connections", async (c) =>
    handleLlmConnectionsRoute(c.req.raw, db, effectivePublicOrigin(), secrets),
  )
  app.all("/api/llm-connections/:id", async (c) =>
    handleLlmConnectionsRoute(c.req.raw, db, effectivePublicOrigin(), secrets),
  )
  const skillsAppDataRoot =
    config.appDataRoot ??
    config.worker?.appDataRoot ??
    config.secretsRoot ??
    join(import.meta.dir, "..", "..", ".app-data")

  app.all("/api/skills", async (c) =>
    handleSkillsRoute(c.req.raw, db, effectivePublicOrigin(), { appDataRoot: skillsAppDataRoot }),
  )
  app.all("/api/skills/system/:name", async (c) =>
    handleSkillsRoute(c.req.raw, db, effectivePublicOrigin(), { appDataRoot: skillsAppDataRoot }),
  )
  app.all("/api/skills/:name", async (c) =>
    handleSkillsRoute(c.req.raw, db, effectivePublicOrigin(), { appDataRoot: skillsAppDataRoot }),
  )

  const knowledgeAppDataRoot = skillsAppDataRoot
  app.all("/api/knowledge/*", async (c) =>
    handleKnowledgeRoute(c.req.raw, db, effectivePublicOrigin(), { appDataRoot: knowledgeAppDataRoot }),
  )
  app.all("/api/knowledge", async (c) =>
    handleKnowledgeRoute(c.req.raw, db, effectivePublicOrigin(), { appDataRoot: knowledgeAppDataRoot }),
  )
  app.post("/internal/knowledge/search", async (c) =>
    handleInternalKnowledgeSearchRoute(c.req.raw, db, workerTokenSecret, {
      appDataRoot: knowledgeAppDataRoot,
    }),
  )

  // Internal LLM gateway - only accepts worker token, not browser cookie
  app.all("/internal/llm/:connectionID/*", async (c) => handleLlmGatewayRoute(c.req.raw, db, secrets))

  let workerBackend: WorkerBackend | undefined
  let workerSupervisor: WorkerSupervisor | undefined
  let publicOrigin = config.publicOrigin
  let proxyState: ProxyState | undefined

  const rebuildWorker = (origin: string) => {
    if (!config.worker) return
    const w = config.worker
    const enabledRow = db.get<{ count: number }>("SELECT COUNT(*) as count FROM dwa_user WHERE disabled = 0")
    const enabledUserCount = enabledRow?.count ?? 0
    const isLoopback = /127\.0\.0\.1|localhost/.test(origin)
    workerBackend = createWorkerBackend({
      appDataRoot: w.appDataRoot,
      mode: w.mode,
      ...(w.workerScript !== undefined ? { workerScript: w.workerScript } : {}),
      ...(w.ociImage !== undefined ? { ociImage: w.ociImage } : {}),
      ...(w.approvedProjectRoots !== undefined ? { approvedProjectRoots: w.approvedProjectRoots } : {}),
      ...(w.allowedEgressHostnames !== undefined ? { allowedEgressHostnames: w.allowedEgressHostnames } : {}),
      enabledUserCount,
      isLoopback,
      controlPlaneUrl: origin,
      workerTokenSecret,
    })
    workerSupervisor = createSupervisor((userId) => workerBackend!.start(userId), {
      stop: (handle) => workerBackend!.stop(handle),
    })
    const allowedHostnames = w.allowedEgressHostnames ? new Set(w.allowedEgressHostnames) : undefined
    if (proxyState) {
      proxyState.backend = workerBackend
      proxyState.supervisor = workerSupervisor
      proxyState.publicOrigin = origin
      proxyState.allowedHostnames = allowedHostnames
    } else {
      proxyState = {
        backend: workerBackend,
        supervisor: workerSupervisor,
        allowedHostnames,
        publicOrigin: origin,
        db,
      }
    }
  }

  if (config.worker) {
    rebuildWorker(publicOrigin)

    /**
     * Test-only routes under /opencode/__test/* require explicit opt-in via
     * DATAWORKS_AGENT_ALLOW_TEST_ROUTES=1. Never return raw worker tokens/passwords.
     */
    const testRoutesAllowed = () => process.env.DATAWORKS_AGENT_ALLOW_TEST_ROUTES === "1"

    app.all("/opencode/__test/worker", async (c) => {
      if (!testRoutesAllowed()) return new Response(null, { status: 404 })
      const user = await authenticateImpl(c.req.raw, db)
      if (!user) return new Response(null, { status: 401 })
      const origin = c.req.header("origin")
      if (origin && origin !== originHolder.value) return new Response(null, { status: 403 })
      try {
        if (proxyState) proxyState.publicOrigin = originHolder.value
        const handle = await workerSupervisor!.acquire(user.id)
        const rawEnv = handle.env ?? {}
        // Redact secrets: never expose DATAWORKS_WORKER_TOKEN or passwords in JSON.
        const safeEnv: Record<string, string | boolean> = {}
        for (const [k, v] of Object.entries(rawEnv)) {
          if (k === "DATAWORKS_WORKER_TOKEN") continue
          if (k === "WORKER_PASSWORD" || k === "OPENCODE_SERVER_PASSWORD") continue
          if (k === "password") continue
          safeEnv[k] = v
        }
        const hasWorkerToken =
          rawEnv.hasWorkerToken === "1" ||
          rawEnv.hasWorkerToken === "true" ||
          Boolean(rawEnv.DATAWORKS_WORKER_TOKEN)
        safeEnv.hasWorkerToken = hasWorkerToken
        return new Response(
          JSON.stringify({
            root: handle.root,
            url: handle.url,
            username: handle.username,
            env: safeEnv,
            hasWorkerToken,
            containerId: handle.containerId ?? null,
            workerId: handle.workerId ?? null,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        )
      } catch (err) {
        const msg = err instanceof Error ? err.message : "unknown"
        if (msg.includes("only supports at most one") || msg.includes("NativeWorkerMultiUserDenied")) {
          return new Response(null, { status: 409 })
        }
        if (msg.includes("unhealthy")) {
          return new Response(null, { status: 503 })
        }
        if (msg.includes("real credentials") || msg.includes("WorkerRealCredentials")) {
          return new Response(msg, { status: 500 })
        }
        return new Response(msg, { status: 500 })
      }
    })

    app.all("/opencode/__test/egress", async (c) => {
      if (!testRoutesAllowed()) return new Response(null, { status: 404 })
      if (proxyState) proxyState.publicOrigin = originHolder.value
      const built = await buildProxy(c.req.raw, proxyState!)
      if (!built) return new Response(null, { status: 401 })
      return handleEgressTest(c.req.raw, built.ctx)
    })

    app.all("/opencode/__test/user/:userId", async (c) => {
      if (!testRoutesAllowed()) return new Response(null, { status: 404 })
      if (proxyState) proxyState.publicOrigin = originHolder.value
      const built = await buildProxy(c.req.raw, proxyState!)
      if (!built) return new Response(null, { status: 401 })
      return new Response(null, { status: 404 })
    })

    app.all("/opencode/*", async (c) => {
      if (proxyState) proxyState.publicOrigin = originHolder.value
      const built = await buildProxy(c.req.raw, proxyState!)
      if (!built) return new Response(null, { status: 401 })
      if (isWebSocketUpgrade(c.req.raw)) {
        return new Response("websocket_upgrade_requires_bun_serve", { status: 426 })
      }
      return proxyWorkerHttp(new URL(c.req.url), c.req.method, c.req.raw, built.ctx)
    })
  }

  let server: { port: number; stop: () => void } | null = null
  if (config.startServer !== false) {
    const bindPort = config.port ?? 0
    const bindHost = config.host

    const fetchHandler = async (
      req: Request,
      bunServer: { upgrade: (req: Request, opts?: { data?: WorkerWsProxyData }) => boolean },
    ) => {
      if (proxyState && isWebSocketUpgrade(req)) {
        const url = new URL(req.url)
        if (url.pathname === "/opencode" || url.pathname.startsWith("/opencode/")) {
          if (!url.pathname.startsWith("/opencode/__test/")) {
            proxyState.publicOrigin = originHolder.value
            try {
              const built = await buildProxy(req, proxyState)
              if (!built) return new Response(null, { status: 401 })
              const result = proxyWorkerWebSocket(req, bunServer, built.ctx)
              if (result === undefined) return undefined as never
              return result
            } catch (err) {
              const msg = err instanceof Error ? err.message : "proxy_error"
              return new Response(msg, { status: 500 })
            }
          }
        }
      }
      return app.fetch(req)
    }

    const serveOpts: {
      port: number
      hostname?: string
      fetch: typeof fetchHandler
      websocket: typeof workerWebSocketHandlers
    } = {
      port: bindPort,
      fetch: fetchHandler,
      websocket: workerWebSocketHandlers,
    }
    if (bindHost !== undefined) serveOpts.hostname = bindHost

    const srv = Bun.serve(serveOpts as never) as {
      port: number
      stop: (close?: boolean) => void
    }
    server = { port: srv.port, stop: () => srv.stop(true) }
    if (publicOrigin === "http://127.0.0.1:0" || publicOrigin === "http://localhost:0") {
      const hostPart = bindHost && bindHost !== "0.0.0.0" ? bindHost : "127.0.0.1"
      const resolved = `http://${hostPart}:${srv.port}`
      originHolder.value = resolved
      publicOrigin = resolved
      if (config.worker) rebuildWorker(resolved)
    } else if (proxyState) {
      proxyState.publicOrigin = publicOrigin
    }
  }

  return {
    app,
    db,
    secrets,
    workerBackend,
    workerSupervisor,
    server: server ?? null,
    publicOrigin,
  } as AppHandle
}

export { createUserImpl as createUser }
