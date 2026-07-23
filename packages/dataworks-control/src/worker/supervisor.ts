import type { UserID } from "@dataworks-agent/core"
import type { WorkerHandle } from "./backend"

export interface SupervisorStart {
  (userId: UserID): Promise<WorkerHandle>
}

export interface SupervisorStop {
  (handle: WorkerHandle): Promise<void>
}

export interface SupervisorOptions {
  idleMs?: number
  crashBackoffMs?: readonly [number, number, number]
  stop?: (handle: WorkerHandle) => Promise<void>
}

export interface WorkerSupervisor {
  acquire: (userId: UserID) => Promise<WorkerHandle>
  dispose: () => Promise<void>
}

interface Acquired {
  handle: WorkerHandle
  stop: () => Promise<void>
  refCount: number
  lastUsed: number
}

export function createSupervisor(start: SupervisorStart, opts: SupervisorOptions = {}): WorkerSupervisor {
  const handles = new Map<string, Acquired>()
  const idleMs = opts.idleMs ?? 900_000
  const backoff = opts.crashBackoffMs ?? [1_000, 2_000, 5_000]
  const crashes = new Map<string, number[]>()

  async function dispose() {
    for (const [, value] of handles) {
      try {
        await value.stop()
      } catch {
        // ignore
      }
    }
    handles.clear()
  }

  async function acquire(userId: UserID): Promise<WorkerHandle> {
    const key = userId
    const now = Date.now()
    const existing = handles.get(key)
    if (existing) {
      existing.refCount += 1
      existing.lastUsed = now
      return existing.handle
    }
    const recent = (crashes.get(key) ?? []).filter((t) => now - t < 60_000)
    if (recent.length >= 3) {
      const err = new Error("worker_unhealthy")
      ;(err as Error & { code?: string }).code = "WORKER_UNHEALTHY"
      throw err
    }
    const handle = await start(key)
    const stop = opts.stop
      ? async () => {
          try {
            await opts.stop!(handle)
          } catch {
            // ignore
          }
        }
      : async () => {
          // default: do nothing; supervisor only tracks lifetime
        }
    handles.set(key, { handle, stop, refCount: 1, lastUsed: now })
    return handle
  }

  return { acquire, dispose }
}
