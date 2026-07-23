#!/usr/bin/env bun
import { join } from "path"
import { mkdirSync, existsSync } from "fs"
import { makeApp } from "../http/server"
import { DryRunForbiddenError, readProductMode, type ProductMode } from "../mode"

function envMap(): Record<string, string | undefined> {
  return process.env as Record<string, string | undefined>
}

function resolveAppDataRoot(env: Record<string, string | undefined>): string {
  if (env.DWA_APP_DATA_ROOT) return env.DWA_APP_DATA_ROOT
  if (process.platform === "win32") {
    const base = env.APPDATA ?? join(env.USERPROFILE ?? ".", "AppData", "Roaming")
    return join(base, "dataworks-agent")
  }
  if (process.platform === "darwin") {
    const home = env.HOME ?? "."
    return join(home, "Library", "Application Support", "dataworks-agent")
  }
  const home = env.HOME ?? "."
  const xdg = env.XDG_DATA_HOME ?? join(home, ".local", "share")
  return join(xdg, "dataworks-agent")
}

function resolveHostPort(env: Record<string, string | undefined>): { host: string; port: number } {
  const host = env.HOST ?? "127.0.0.1"
  const port = Number(env.PORT ?? 8084)
  if (!Number.isFinite(port) || port <= 0 || port > 65535) {
    throw new Error(`Invalid PORT: ${env.PORT}`)
  }
  return { host, port }
}

function resolveWorkerScript(env: Record<string, string | undefined>, mode: ProductMode): string | undefined {
  if (env.DWA_WORKER_SCRIPT) return env.DWA_WORKER_SCRIPT
  // Prefer real opencode entry when present; fall back to fake worker only if forced (not default).
  const repoRoot = join(import.meta.dir, "..", "..", "..", "..")
  const opencode = join(repoRoot, "packages", "opencode", "src", "index.ts")
  if (existsSync(opencode)) return opencode
  if (mode === "development" && env.DWA_ALLOW_FAKE_WORKER === "1") {
    const fake = join(repoRoot, "scripts", "fake-opencode-worker.ts")
    if (existsSync(fake)) return fake
  }
  return undefined
}

async function main() {
  const env = envMap()
  const isDevFlag = process.argv.includes("--dev")

  let mode: ProductMode
  try {
    mode = readProductMode(env)
  } catch (err) {
    if (err instanceof DryRunForbiddenError) {
      console.error(err.message)
      process.exit(2)
    }
    throw err
  }

  if (isDevFlag && mode === "production") {
    mode = "development"
  }

  const { host, port } = resolveHostPort(env)
  const appDataRoot = resolveAppDataRoot(env)
  mkdirSync(appDataRoot, { recursive: true })

  const dbPath = env.DWA_CONTROL_DB ?? join(appDataRoot, "control.sqlite")
  const secretsRoot = env.DWA_SECRETS_ROOT ?? join(appDataRoot, "secrets")
  mkdirSync(secretsRoot, { recursive: true })

  const migrationsDir = join(import.meta.dir, "..", "..", "migration")
  const publicOrigin = env.DWA_PUBLIC_ORIGIN ?? `http://${host === "0.0.0.0" ? "127.0.0.1" : host}:${port}`

  const workerScript = resolveWorkerScript(env, mode)
  const workerMode = (env.DWA_WORKER_MODE as "native" | "oci" | undefined) ?? "native"

  // Native workers only for loopback single-user product boot.
  const isLoopback = /127\.0\.0\.1|localhost/.test(publicOrigin)
  const worker =
    workerScript && isLoopback && workerMode === "native"
      ? {
          appDataRoot,
          mode: "native" as const,
          workerScript,
          approvedProjectRoots: env.DWA_APPROVED_PROJECT_ROOTS
            ? env.DWA_APPROVED_PROJECT_ROOTS.split(pathSep()).filter(Boolean)
            : [],
        }
      : undefined

  if (!worker) {
    console.warn(
      "worker: not configured (need loopback origin + worker script). Control plane will start without /opencode proxy.",
    )
  }

  // Never enable fixtures by default in product start.
  if (env.DATAWORKS_AGENT_ALLOW_FIXTURES === "1") {
    console.warn(
      "DATAWORKS_AGENT_ALLOW_FIXTURES=1 is set; fixtures are intended for unit tests only, not product start.",
    )
  }

  const handle = await makeApp({
    dbPath,
    publicOrigin,
    migrationsDir,
    secretsRoot,
    host,
    port,
    startServer: true,
    ...(worker ? { worker } : {}),
  })

  const boundPort = handle.server?.port ?? port
  console.log(`dataworks-control listening on ${handle.publicOrigin} (mode=${mode}, port=${boundPort})`)
  console.log(`app data: ${appDataRoot}`)
  // Intentionally no secrets, master keys, or tokens in logs.
}

function pathSep(): string {
  return process.platform === "win32" ? ";" : ":"
}

main().catch((err) => {
  if (err instanceof DryRunForbiddenError) {
    console.error(err.message)
    process.exit(2)
  }
  console.error(err instanceof Error ? err.message : String(err))
  process.exit(1)
})
