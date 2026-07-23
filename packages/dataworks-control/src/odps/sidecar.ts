// Supervisor that owns a single Python sidecar process and brokers NDJSON
// requests with bounded concurrency, backoff-restart, and signal-aware
// cancellation. The supervisor is the only place where credentials and SQL
// literals pass through; the rest of the codebase handles redacted values.

import { spawn, type ChildProcess } from "node:child_process"
import { dirname, join, resolve } from "node:path"
import { randomUUID } from "node:crypto"
import { EventEmitter } from "node:events"

import {
  ERROR_CODES,
  MAX_CONCURRENT_QUERIES,
  MAX_LINE_BYTES,
  type QueryParams,
  type QueryResult,
  type SidecarError,
  type SidecarMethod,
  type SidecarRequest,
  isFailure,
  isSuccess,
} from "./protocol"

const BACKOFF_MS = [1000, 2000, 5000] as const

export interface SidecarSupervisorOptions {
  /** Absolute path to the sidecar `pyproject.toml` directory. */
  readonly projectPath: string
  /** Override the python executable. Defaults to `python` from PATH (resolved by uv). */
  readonly pythonBin?: string
  /** Force a manual dry-run. When unset the supervisor reads DWA_PYODPS_DRY_RUN. */
  readonly dryRun?: boolean
  /** Optional test hook that mints controlled request IDs. */
  readonly idFactory?: () => string
  /** Optional test hook for the spawner; defaults to `uv run ... python -m dwa_pyodps`. */
  readonly spawn?: (cmd: string, args: string[]) => ChildProcess
  /** stderr is captured silently unless this is set. */
  readonly stderr?: (line: string) => void
}

interface Pending {
  resolve: (value: QueryResult) => void
  reject: (reason: SidecarError) => void
  signal?: AbortSignal
  cancelled?: boolean
  method: SidecarMethod
}

interface SpawnHandle {
  child: ChildProcess
  buffer: string
  pending: Map<string, Pending>
}

/**
 * Owns a single sidecar child process. Restarts it with 1s / 2s / 5s backoff
 * after an unexpected exit and rejects every pending query with
 * UPSTREAM_ERROR.
 */
export class OdpsSidecarSupervisor extends EventEmitter {
  private readonly opts: SidecarSupervisorOptions
  private handle: SpawnHandle | null = null
  private starting: Promise<void> | null = null
  private attempt = 0
  private closed = false
  private restartTimer: ReturnType<typeof setTimeout> | null = null
  private readonly writeQueue: string[] = []
  private draining = false

  constructor(opts: SidecarSupervisorOptions) {
    super()
    this.opts = opts
  }

  /** Whether the supervisor currently holds a child process. */
  get running(): boolean {
    return this.handle !== null
  }

  /** Test-only accessor for the current child PID. Returns 0 when idle. */
  get pid(): number {
    return this.handle?.child.pid ?? 0
  }

  /** Test-only accessor for the live pending map (size). */
  get inflightCount(): number {
    return this.handle?.pending.size ?? 0
  }

  async start(): Promise<void> {
    if (this.closed) throw new Error("supervisor closed")
    if (this.handle) return
    if (this.starting) return this.starting
    this.starting = this.spawnOnce().finally(() => {
      this.starting = null
    })
    await this.starting
  }

  async stop(): Promise<void> {
    this.closed = true
    if (this.restartTimer) {
      clearTimeout(this.restartTimer)
      this.restartTimer = null
    }
    if (this.handle) {
      const handle = this.handle
      this.handle = null
      this.rejectAllPending(handle, {
        code: ERROR_CODES.UPSTREAM_ERROR,
        message: "supervisor stopped",
        retryable: false,
      })
      try {
        handle.child.kill("SIGKILL")
      } catch {
        // Child may already be dead; ignore.
      }
    }
  }

  /** Issue a query through the sidecar. Honours `signal` via a cancel message. */
  async query(input: QueryParams & { signal?: AbortSignal }): Promise<QueryResult> {
    if (!this.handle) await this.start()
    return this.sendQuery(input)
  }

  /** Send a `health` request and resolve with the parsed result. */
  async health(): Promise<{ ok: boolean; version: string; dry_run: boolean }> {
    if (!this.handle) await this.start()
    return this.sendHealth()
  }

  /**
   * Test-only: kill the child process. The supervisor will respawn on the
   * next call to query/health. Acceptable as a backdoor for the restart
   * integration test.
   */
  killChild(signal: NodeJS.Signals = "SIGKILL"): boolean {
    if (!this.handle) return false
    try {
      this.handle.child.kill(signal)
      return true
    } catch {
      return false
    }
  }

  // -----------------------------------------------------------------------
  // Internals
  // -----------------------------------------------------------------------

  private get projectPath(): string {
    return resolve(this.opts.projectPath)
  }

  private get dryRun(): boolean {
    if (typeof this.opts.dryRun === "boolean") return this.opts.dryRun
    const env = process.env.DWA_PYODPS_DRY_RUN
    return !!env && /^(1|true|yes)$/i.test(env)
  }

  private buildArgs(): { cmd: string; args: string[] } {
    const cmd = this.opts.spawn ? this.opts.pythonBin ?? "ignored" : "uv"
    const args: string[] = []
    if (!this.opts.spawn) {
      args.push("run", "--project", this.projectPath)
      // Insert `--` so that `--dry-run` and the python args are forwarded to
      // the sidecar process rather than interpreted by `uv` itself.
      args.push("--")
    }
    args.push(this.opts.pythonBin ?? "python", "-m", "dwa_pyodps")
    if (this.dryRun) {
      args.push("--dry-run")
    }
    return { cmd, args }
  }

  private spawnOnce(): Promise<void> {
    return new Promise((resolve, reject) => {
      const { cmd, args } = this.buildArgs()
      const child = (this.opts.spawn ? this.opts.spawn(cmd, args) : spawn(cmd, args, {
        stdio: ["pipe", "pipe", "pipe"],
        env: {
          ...process.env,
          ...(this.dryRun ? { DWA_PYODPS_DRY_RUN: "1" } : {}),
          PYTHONUNBUFFERED: "1",
        },
      })) as ChildProcess
      const handle: SpawnHandle = {
        child,
        buffer: "",
        pending: new Map(),
      }
      this.handle = handle

      const onExit = (code: number | null) => {
        if (this.handle !== handle) return
        this.handle = null
        const wasUnexpected = code !== 0 && code !== null
        this.rejectAllPending(handle, {
          code: ERROR_CODES.UPSTREAM_ERROR,
          message: wasUnexpected
            ? `sidecar exited with code ${code}`
            : "sidecar exited",
          retryable: wasUnexpected,
        })
        if (!this.closed) this.scheduleRestart()
      }

      child.once("spawn", () => {
        resolve()
        this.emit("spawn", { pid: child.pid ?? 0, attempt: this.attempt })
      })
      child.once("error", (err) => {
        if (!this.handle) {
          reject(err)
          return
        }
        this.handle = null
        this.rejectAllPending(handle, {
          code: ERROR_CODES.UPSTREAM_ERROR,
          message: `sidecar failed to spawn: ${err.message}`,
          retryable: true,
        })
        if (!this.closed) this.scheduleRestart()
      })
      child.on("exit", onExit)

      // Configure I/O.
      child.stdout?.setEncoding("utf8")
      child.stdout?.on("data", (chunk: string) => this.handleStdout(handle, chunk))
      child.stderr?.setEncoding("utf8")
      child.stderr?.on("data", (chunk: string) => {
        const sink = this.opts.stderr
        if (!sink) return
        const trimmed = chunk.endsWith("\n") ? chunk : `${chunk}\n`
        for (const line of trimmed.split("\n")) {
          if (line.trim()) sink(line)
        }
      })
      child.stdin?.on("error", () => {
        // stdin EOF — the handle will emit 'exit' momentarily.
      })
    })
  }

  private scheduleRestart(): void {
    const delay = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)]
    this.attempt++
    if (this.restartTimer) clearTimeout(this.restartTimer)
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null
      if (this.closed) return
      void this.start().catch(() => {
        // Spawn errors are handled by scheduleRestart via the 'error' branch.
      })
    }, delay)
  }

  private rejectAllPending(handle: SpawnHandle, error: SidecarError): void {
    if (handle.pending.size === 0) return
    const pendingList = Array.from(handle.pending.values())
    handle.pending.clear()
    for (const pending of pendingList) {
      pending.reject(error)
    }
  }

  private handleStdout(handle: SpawnHandle, chunk: string): void {
    handle.buffer += chunk
    let nl = handle.buffer.indexOf("\n")
    while (nl >= 0) {
      const raw = handle.buffer.slice(0, nl)
      handle.buffer = handle.buffer.slice(nl + 1)
      if (raw.length > MAX_LINE_BYTES) {
        this.rejectAllPending(handle, {
          code: ERROR_CODES.LINE_TOO_LONG,
          message: `stdout line exceeds ${MAX_LINE_BYTES} bytes`,
          retryable: true,
        })
        try {
          handle.child.kill("SIGKILL")
        } catch {
          // ignore
        }
        return
      }
      this.handleStdoutLine(handle, raw)
      nl = handle.buffer.indexOf("\n")
    }
  }

  private handleStdoutLine(handle: SpawnHandle, raw: string): void {
    const text = raw.trim()
    if (!text) return
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(text)
    } catch {
      // One bad line should not crash the supervisor. Reject pending with
      // protocol error.
      this.rejectAllPending(handle, {
        code: ERROR_CODES.INVALID_JSON,
        message: "sidecar produced non-JSON stdout",
        retryable: true,
      })
      return
    }
    const id = typeof parsed.id === "string" ? parsed.id : null
    if (!id) return
    const pending = handle.pending.get(id)
    if (!pending) return
    if (isSuccess(parsed)) {
      handle.pending.delete(id)
      pending.resolve(parsed.result as QueryResult)
      return
    }
    if (isFailure(parsed)) {
      handle.pending.delete(id)
      const err = (parsed.error ?? {}) as SidecarError
      pending.reject(err)
      return
    }
    // Unknown response shape — reject that single request.
    handle.pending.delete(id)
    pending.reject({
      code: ERROR_CODES.INVALID_SHAPE,
      message: "sidecar produced an unrecognised response",
      retryable: false,
    })
  }

  private enqueueSend(payload: SidecarRequest): Promise<QueryResult> {
    return new Promise((resolve, reject) => {
      if (!this.handle) {
        reject({
          code: ERROR_CODES.UPSTREAM_ERROR,
          message: "sidecar not running",
          retryable: true,
        } satisfies SidecarError)
        return
      }
      if (this.handle.pending.size >= MAX_CONCURRENT_QUERIES && payload.method === "query") {
        reject({
          code: ERROR_CODES.BUSY,
          message: `max ${MAX_CONCURRENT_QUERIES} concurrent queries in flight`,
          retryable: true,
        } satisfies SidecarError)
        return
      }
      const pending: Pending = {
        resolve,
        reject,
        method: payload.method,
      }
      this.handle.pending.set(payload.id, pending)
      const onSignal = () => {
        if (pending.cancelled) return
        pending.cancelled = true
        this.sendCancel(payload.id)
      }
      if (payload.method === "query") {
        // pending was constructed without `signal`; attach now.
        const params = payload.params as { signal?: AbortSignal } | undefined
        if (params?.signal) {
          pending.signal = params.signal
          if (params.signal.aborted) {
            onSignal()
          } else {
            params.signal.addEventListener("abort", onSignal, { once: true })
          }
        }
      }
      this.writeLine(this.handle, JSON.stringify(payload))
    })
  }

  private async writeLine(handle: SpawnHandle, line: string): Promise<void> {
    const stdin = handle.child.stdin
    if (!stdin || stdin.destroyed) {
      handle.pending.forEach((pending) => {
        pending.reject({
          code: ERROR_CODES.UPSTREAM_ERROR,
          message: "sidecar stdin is closed",
          retryable: true,
        } satisfies SidecarError)
      })
      handle.pending.clear()
      return
    }
    this.writeQueue.push(line + "\n")
    if (this.draining) return
    this.draining = true
    try {
      while (this.writeQueue.length > 0) {
        const next = this.writeQueue.shift()!
        const ok = stdin.write(next)
        if (!ok) {
          await new Promise<void>((res) => stdin.once("drain", () => res()))
        }
      }
    } finally {
      this.draining = false
    }
  }

  private async sendHealth(): Promise<{ ok: boolean; version: string; dry_run: boolean }> {
    return new Promise((resolve, reject) => {
      if (!this.handle) {
        reject({
          code: ERROR_CODES.UPSTREAM_ERROR,
          message: "sidecar not running",
          retryable: true,
        } satisfies SidecarError)
        return
      }
      const id = this.nextId("health")
      this.handle.pending.set(id, {
        resolve: (value) => resolve(value as unknown as { ok: boolean; version: string; dry_run: boolean }),
        reject: (err) => reject(err),
        method: "health",
      })
      this.writeLine(this.handle, JSON.stringify({ id, method: "health" }))
    })
  }

  private async sendQuery(input: QueryParams & { signal?: AbortSignal }): Promise<QueryResult> {
    const id = this.nextId("q")
    const payload: SidecarRequest<QueryParams> = {
      id,
      method: "query",
      params: input,
    }
    // The pending ctor in enqueueSend takes care of registering signal
    // handlers; we surface QueryResult to the caller.
    return this.enqueueSend(payload)
  }

  private sendCancel(targetId: string): void {
    if (!this.handle) return
    const id = this.nextId("c")
    const payload: SidecarRequest<{ id: string }> = {
      id,
      method: "cancel",
      params: { id: targetId },
    }
    this.handle.pending.set(id, {
      resolve: () => {
        // no-op; the original query will reject asynchronously.
      },
      reject: () => {
        // cancel ack failures are not propagated as query failures.
      },
      method: "cancel",
    })
    this.writeLine(this.handle, JSON.stringify(payload))
  }

  private nextId(prefix: string): string {
    const factory = this.opts.idFactory ?? (() => randomUUID())
    return `${prefix}_${factory()}`
  }
}

/**
 * Resolve the path to the bundled sidecar project (`sidecars/pyodps`)
 * relative to a workspace package. Used by the service layer so the caller
 * does not have to know the absolute on-disk path.
 */
export function resolveSidecarPath(workspaceRoot: string): string {
  return resolve(workspaceRoot, "..", "sidecars", "pyodps")
}

void dirname
void join
