import { mkdirSync, writeFileSync, readFileSync, existsSync } from "fs"
import { join } from "path"
import type { Database } from "../database"
import { LlmConnectionRepo } from "../llm/repo"
import type { UserID } from "@dataworks-agent/core"

export interface OpenCodeProviderConfig {
  readonly baseURL: string
  readonly apiKey: string
  readonly allowedModels?: string[]
}

export interface ManagedOpencodeOptions {
  /** Absolute skill discovery roots (system + user SKILL.md trees). */
  readonly skillPaths?: readonly string[]
}

/**
 * Generate non-secret provider configuration for a worker's OpenCode setup.
 * The config contains only non-secret markers like "dwa-worker-token".
 * Real credentials are injected server-side by the LLM gateway.
 */
export function generateProviderConfig(
  userId: UserID,
  db: Database,
  controlPlaneOrigin: string,
): Record<string, OpenCodeProviderConfig> {
  const repo = new LlmConnectionRepo(db)
  const connections = repo.findEnabledByUserId(userId)

  const providers: Record<string, OpenCodeProviderConfig> = {}
  for (const conn of connections) {
    // Build internal gateway URL - never expose real upstream origin
    const baseURL = `${controlPlaneOrigin}/internal/llm/${conn.id}`

    providers[conn.id] = {
      baseURL,
      apiKey: "dwa-worker-token", // Non-secret marker consumed by gateway
      ...(conn.allowed_models.length > 0 ? { allowedModels: conn.allowed_models } : {}),
    }
  }

  return providers
}

function writeProvidersJson(opencodeDir: string, config: Record<string, OpenCodeProviderConfig>): void {
  mkdirSync(opencodeDir, { recursive: true })
  const configPath = join(opencodeDir, "providers.json")
  writeFileSync(configPath, JSON.stringify(config, null, 2))
}

/**
 * Write provider config under HOME/.config/opencode (non-XDG layout).
 * Prefer {@link writeWorkerProviderConfigDual} when XDG_CONFIG_HOME differs from HOME.
 */
export function writeWorkerProviderConfig(
  workerRoot: string,
  config: Record<string, OpenCodeProviderConfig>,
  opts?: ManagedOpencodeOptions,
): void {
  writeProvidersJson(join(workerRoot, ".config", "opencode"), config)

  // Managed OpenCode config loads the DataWorks plugin without patching
  // packages/opencode/src/tool/registry.ts.
  writeWorkerManagedOpencodeConfig(workerRoot, opts)
}

/**
 * Dual-write providers.json to HOME/.config/opencode and $XDG_CONFIG_HOME/opencode
 * so OpenCode finds config under either layout (same as plugin opencode.json dual-write).
 */
export function writeWorkerProviderConfigDual(
  workerRoot: string,
  xdgConfigHome: string,
  config: Record<string, OpenCodeProviderConfig>,
  opts?: ManagedOpencodeOptions,
): void {
  writeProvidersJson(join(workerRoot, ".config", "opencode"), config)
  writeProvidersJson(join(xdgConfigHome, "opencode"), config)
  writeWorkerManagedOpencodeConfig(workerRoot, opts)
  writeWorkerManagedOpencodeConfigDir(join(xdgConfigHome, "opencode"), opts)
}

/**
 * Write managed worker OpenCode config that registers the DataWorks plugin.
 * OpenCode loads plugins via config `plugin: [...]` using @opencode-ai/plugin.
 */
export function writeWorkerManagedOpencodeConfig(workerRoot: string, opts?: ManagedOpencodeOptions): void {
  writeWorkerManagedOpencodeConfigDir(join(workerRoot, ".config", "opencode"), opts)
}

/** Ensure opencode.json under an absolute OpenCode config directory includes the plugin. */
export function writeWorkerManagedOpencodeConfigDir(
  opencodeDir: string,
  opts?: ManagedOpencodeOptions,
): void {
  mkdirSync(opencodeDir, { recursive: true })
  const configPath = join(opencodeDir, "opencode.json")
  let existing: Record<string, unknown> = {}
  if (existsSync(configPath)) {
    try {
      existing = JSON.parse(readFileSync(configPath, "utf-8")) as Record<string, unknown>
    } catch {
      existing = {}
    }
  }
  const plugins = Array.isArray(existing.plugin) ? ([...existing.plugin] as unknown[]) : []
  if (!plugins.includes("@dataworks-agent/plugin")) {
    plugins.push("@dataworks-agent/plugin")
  }
  const next: Record<string, unknown> = { ...existing, plugin: plugins }
  if (opts?.skillPaths && opts.skillPaths.length > 0) {
    const prevSkills =
      existing.skills && typeof existing.skills === "object" && !Array.isArray(existing.skills)
        ? (existing.skills as Record<string, unknown>)
        : {}
    next.skills = {
      ...prevSkills,
      paths: [...opts.skillPaths],
    }
  }
  writeFileSync(configPath, JSON.stringify(next, null, 2))
}

/**
 * Read existing provider config from worker directory.
 */
export function readWorkerProviderConfig(workerRoot: string): Record<string, OpenCodeProviderConfig> | null {
  const configPath = join(workerRoot, ".config", "opencode", "providers.json")
  if (!existsSync(configPath)) return null
  try {
    return JSON.parse(readFileSync(configPath, "utf-8"))
  } catch {
    return null
  }
}

/**
 * Check if worker config contains real provider credentials.
 * Production startup should refuse to start if real credentials are present.
 * Scans managed provider/config files for common secret patterns.
 * Does not scan process env (callers must pass cleaned env separately).
 *
 * @param workerRoot HOME-style root (scans `.config/opencode/*`)
 * @param xdgConfigHome optional XDG_CONFIG_HOME (scans `opencode/*` under it)
 */
export function scanWorkerForRealCredentials(workerRoot: string, xdgConfigHome?: string): boolean {
  const suspicious =
    /sk-[A-Za-z0-9]{10,}|sk_[A-Za-z0-9]{10,}|api[_-]?key["']?\s*[:=]\s*["'][^"']{8,}/i
  const files = [
    join(workerRoot, ".config", "opencode", "providers.json"),
    join(workerRoot, ".config", "opencode", "opencode.json"),
  ]
  if (xdgConfigHome) {
    files.push(join(xdgConfigHome, "opencode", "providers.json"), join(xdgConfigHome, "opencode", "opencode.json"))
  }
  for (const file of files) {
    if (!existsSync(file)) continue
    try {
      const text = readFileSync(file, "utf-8")
      // Non-secret marker used by gateway is allowed
      const withoutMarker = text.replace(/dwa-worker-token/g, "")
      if (suspicious.test(withoutMarker)) return true
    } catch {
      // ignore unreadable
    }
  }
  return false
}
