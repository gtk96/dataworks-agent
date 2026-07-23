import { spawn, type Subprocess } from "bun"
import { randomBytes } from "crypto"
import { join, resolve } from "path"
import { mkdirSync, existsSync } from "fs"
import {
  writeWorkerProviderConfigDual,
  scanWorkerForRealCredentials,
  writeWorkerManagedOpencodeConfigDir,
} from "./provider-config"
import { userPrivateRoots, ensurePaths } from "./paths"
import { signWorkerToken, generateWorkerToken, DEFAULT_WORKER_TOKEN_TTL_MS } from "./token"

export interface NativeWorkerOptions {
  appDataRoot: string
  userId: string
  workerScript: string
  /** Control-plane public origin for plugin callbacks (DATAWORKS_CONTROL_PLANE_URL). */
  controlPlaneUrl?: string
  /** HMAC secret for signing worker tokens. When set, injects DATAWORKS_WORKER_TOKEN. */
  workerTokenSecret?: Uint8Array
  /** Absolute private roots to inject as DWA_PRIVATE_PATHS (JSON array). */
  privatePaths?: string[]
  /** Extra env vars merged into the worker process. */
  extraEnv?: Record<string, string>
}

export interface NativeWorkerHandle {
  url: string
  authorization: string
  root: string
  env: Record<string, string>
  proc: Subprocess
  username: string
  password: string
  containerId?: string
  workerId: string
}

export class NativeWorkerMultiUserDenied extends Error {
  constructor() {
    super("NativeWorker mode only supports at most one enabled user")
  }
}

export class WorkerRealCredentialsError extends Error {
  constructor(message = "Worker config contains real credentials; refusing start") {
    super(message)
    this.name = "WorkerRealCredentialsError"
  }
}

function pickPort(host: string): Promise<number> {
  return new Promise((resolvePort, reject) => {
    const net = require("net") as typeof import("net")
    const srv = net.createServer()
    srv.unref()
    srv.on("error", reject)
    srv.listen(0, host, () => {
      const addr = srv.address()
      if (!addr || typeof addr === "string") {
        srv.close()
        reject(new Error("no_port"))
        return
      }
      const port = addr.port
      srv.close(() => resolvePort(port))
    })
  })
}

/**
 * Build NODE_PATH so Bun/Node can resolve `@dataworks-agent/plugin` from the monorepo
 * checkout when OpenCode loads the managed plugin.
 *
 * Prefer:
 * 1. packages/ (parent of dataworks-plugin) for `require('@dataworks-agent/plugin')` style
 *    if a symlink packages/@dataworks-agent/plugin existed — we also include
 *    packages/dataworks-plugin and ensure node_modules/@dataworks-agent/plugin is on path
 *    via repo root node_modules + package-local node_modules.
 * 2. Repo root node_modules
 * 3. Existing NODE_PATH
 */
function buildPluginNodePath(repoRoot: string): string {
  const pluginPkg = resolve(repoRoot, "packages", "dataworks-plugin")
  const packagesDir = resolve(repoRoot, "packages")
  const rootNodeModules = resolve(repoRoot, "node_modules")
  const pluginNodeModules = resolve(pluginPkg, "node_modules")
  const controlNodeModules = resolve(repoRoot, "packages", "dataworks-control", "node_modules")

  // Scoped package resolution: node_modules/@dataworks-agent/plugin
  // Ensure a symlink exists under root node_modules when missing (dev monorepo).
  ensureScopedPluginLink(rootNodeModules, pluginPkg)

  const parts = [
    rootNodeModules,
    controlNodeModules,
    pluginNodeModules,
    // Allow resolving the package directory itself if OpenCode uses file paths
    packagesDir,
    pluginPkg,
  ]
  if (process.env.NODE_PATH) parts.push(process.env.NODE_PATH)
  const sep = process.platform === "win32" ? ";" : ":"
  // Deduplicate while preserving order
  const seen = new Set<string>()
  const unique: string[] = []
  for (const p of parts) {
    const key = p.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    unique.push(p)
  }
  return unique.join(sep)
}

function ensureScopedPluginLink(rootNodeModules: string, pluginPkg: string): void {
  try {
    const scopeDir = join(rootNodeModules, "@dataworks-agent")
    const linkPath = join(scopeDir, "plugin")
    if (existsSync(linkPath)) return
    mkdirSync(scopeDir, { recursive: true })
    // Prefer symlink; fall back to no-op if unsupported (caller still has NODE_PATH).
    try {
      const { symlinkSync, lstatSync } = require("fs") as typeof import("fs")
      try {
        lstatSync(linkPath)
      } catch {
        symlinkSync(pluginPkg, linkPath, process.platform === "win32" ? "junction" : "dir")
      }
    } catch {
      // ignore link failures
    }
  } catch {
    // ignore
  }
}

/** Redacted env snapshot for control-plane APIs / tests — never raw token or password. */
export function redactWorkerPublicEnv(env: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(env)) {
    if (k === "DATAWORKS_WORKER_TOKEN") continue
    if (k === "WORKER_PASSWORD" || k === "OPENCODE_SERVER_PASSWORD") continue
    out[k] = v
  }
  out.hasWorkerToken = env.DATAWORKS_WORKER_TOKEN ? "1" : "0"
  return out
}

export async function startNativeWorker(opts: NativeWorkerOptions): Promise<NativeWorkerHandle> {
  const username = "dwa-worker"
  const password = Buffer.from(randomBytes(32)).toString("base64")
  const userHome = join(opts.appDataRoot, "users", opts.userId, "home")
  const userData = join(opts.appDataRoot, "users", opts.userId, "data")
  const userConfig = join(opts.appDataRoot, "users", opts.userId, "config")
  const userCache = join(opts.appDataRoot, "users", opts.userId, "cache")
  mkdirSync(userHome, { recursive: true })
  mkdirSync(userData, { recursive: true })
  mkdirSync(userConfig, { recursive: true })
  mkdirSync(userCache, { recursive: true })

  // Tenant skill roots (system + this user only) for plugin SkillContext and OpenCode skills.paths.
  const systemSkills = join(opts.appDataRoot, "skills", "system")
  const userSkills = join(opts.appDataRoot, "users", opts.userId, "skills")
  mkdirSync(systemSkills, { recursive: true })
  mkdirSync(userSkills, { recursive: true })
  const skillRoots = [systemSkills, userSkills]

  // Dual-write providers.json + plugin opencode.json under HOME and XDG_CONFIG_HOME layouts.
  // skills.paths points OpenCode skill discovery at control-plane system + user SKILL.md roots.
  writeWorkerProviderConfigDual(userHome, userConfig, {}, {
    skillPaths: skillRoots,
  })
  // Ensure XDG layout plugin entry even if dual-write path changes.
  writeWorkerManagedOpencodeConfigDir(join(userConfig, "opencode"), {
    skillPaths: skillRoots,
  })

  // Refuse start if managed configs look like they contain real provider secrets.
  if (scanWorkerForRealCredentials(userHome, userConfig)) {
    throw new WorkerRealCredentialsError(
      "Worker managed config appears to contain real provider credentials " +
        "(sk-*/api_key patterns). Remove secrets from providers.json/opencode.json under " +
        "HOME/.config/opencode and $XDG_CONFIG_HOME/opencode, then retry.",
    )
  }

  const workerId = `native-${opts.userId.slice(0, 8)}-${generateWorkerToken().slice(0, 8)}`
  const privatePaths =
    opts.privatePaths ??
    (() => {
      try {
        const roots = userPrivateRoots(opts.appDataRoot, opts.userId)
        ensurePaths(roots)
        return [roots.home, roots.data, roots.config, roots.cache, opts.appDataRoot]
      } catch {
        return [userHome, userData, userConfig, userCache, opts.appDataRoot]
      }
    })()

  const controlEnv: Record<string, string> = {
    DATAWORKS_WORKER_ID: workerId,
    DWA_PRIVATE_PATHS: JSON.stringify(privatePaths),
    DWA_APP_DATA_ROOT: opts.appDataRoot,
    DWA_USER_ID: opts.userId,
    DWA_SKILL_ROOTS: JSON.stringify(skillRoots),
  }
  if (opts.controlPlaneUrl) {
    controlEnv.DATAWORKS_CONTROL_PLANE_URL = opts.controlPlaneUrl
  }
  if (opts.workerTokenSecret) {
    // Process-lifetime token: TTL ≥ worker idle (default 900s). Re-issued on each native start.
    controlEnv.DATAWORKS_WORKER_TOKEN = signWorkerToken(opts.workerTokenSecret, {
      userID: opts.userId,
      workerID: workerId,
      expires: Date.now() + DEFAULT_WORKER_TOKEN_TTL_MS,
    })
  } else {
    // Dev / fake-worker: non-empty token so plugin client can construct.
    controlEnv.DATAWORKS_WORKER_TOKEN = generateWorkerToken()
  }

  // Help OpenCode resolve workspace plugin package from monorepo checkout.
  // native.ts lives at packages/dataworks-control/src/worker → 4 levels up = repo root
  const repoRoot = resolve(import.meta.dir, "..", "..", "..", "..")
  controlEnv.NODE_PATH = buildPluginNodePath(repoRoot)

  let lastErr: unknown
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const port = await pickPort("127.0.0.1").catch(() => 0)
    if (port === 0) continue
    const env: Record<string, string> = {
      ...(process.env as Record<string, string>),
      HOME: userHome,
      USERPROFILE: userHome,
      XDG_DATA_HOME: userData,
      XDG_CONFIG_HOME: userConfig,
      XDG_CACHE_HOME: userCache,
      PORT: String(port),
      WORKER_USERNAME: username,
      WORKER_PASSWORD: password,
      OPENCODE_SERVER_USERNAME: username,
      OPENCODE_SERVER_PASSWORD: password,
      ...controlEnv,
      ...(opts.extraEnv ?? {}),
    }
    const proc = spawn({
      cmd: ["bun", "run", opts.workerScript],
      env,
      stdout: "ignore",
      stderr: "ignore",
    })
    const url = `http://127.0.0.1:${port}`
    const start = Date.now()
    while (Date.now() - start < 5000) {
      try {
        const res = await fetch(url + "/env", {
          headers: { authorization: "Basic " + Buffer.from(`${username}:${password}`).toString("base64") },
        })
        if (res.ok) {
          // Public env never includes raw worker token or password.
          const publicEnv: Record<string, string> = {
            HOME: userHome,
            XDG_DATA_HOME: userData,
            XDG_CONFIG_HOME: userConfig,
            XDG_CACHE_HOME: userCache,
            DATAWORKS_CONTROL_PLANE_URL: controlEnv.DATAWORKS_CONTROL_PLANE_URL ?? "",
            DATAWORKS_WORKER_ID: controlEnv.DATAWORKS_WORKER_ID ?? "",
            DWA_PRIVATE_PATHS: controlEnv.DWA_PRIVATE_PATHS ?? "",
            DWA_APP_DATA_ROOT: controlEnv.DWA_APP_DATA_ROOT ?? "",
            DWA_USER_ID: controlEnv.DWA_USER_ID ?? "",
            DWA_SKILL_ROOTS: controlEnv.DWA_SKILL_ROOTS ?? "",
            hasWorkerToken: controlEnv.DATAWORKS_WORKER_TOKEN ? "1" : "0",
            NODE_PATH: controlEnv.NODE_PATH ?? "",
          }
          return {
            url,
            authorization: "Basic " + Buffer.from(`${username}:${password}`).toString("base64"),
            root: userHome,
            env: publicEnv,
            proc,
            username,
            password,
            workerId,
          }
        }
      } catch {
        // retry
      }
      await new Promise((r) => setTimeout(r, 100))
    }
    try {
      proc.kill()
    } catch {
      // ignore
    }
    lastErr = new Error("startup_timeout")
  }
  throw lastErr ?? new Error("native_worker_failed")
}

export async function stopNativeWorker(handle: NativeWorkerHandle): Promise<void> {
  try {
    handle.proc.kill()
  } catch {
    // ignore
  }
}
