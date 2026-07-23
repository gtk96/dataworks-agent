import { NativeWorkerMultiUserDenied, startNativeWorker, stopNativeWorker, type NativeWorkerHandle } from "./native"
import { userPrivateRoots, ensurePaths } from "./paths"
import type { UserID } from "@dataworks-agent/core"

export interface WorkerBackendConfig {
  appDataRoot: string
  mode: "native" | "oci"
  opencodeBinary?: string
  workerScript?: string
  ociImage?: string
  approvedProjectRoots?: string[]
  enabledUserCount: number
  isLoopback: boolean
  allowedEgressHostnames?: string[]
  /** Public origin of the control plane (injected as DATAWORKS_CONTROL_PLANE_URL). */
  controlPlaneUrl?: string
  /** HMAC secret for worker tokens. */
  workerTokenSecret?: Uint8Array
}

export interface WorkerHandle {
  userId: UserID
  url: string
  authorization: string
  root: string
  env: Record<string, string>
  containerId?: string
  username: string
  password: string
  workerId?: string
}

export interface WorkerBackend {
  mode: "native" | "oci"
  start: (userId: UserID) => Promise<WorkerHandle>
  stop: (handle: WorkerHandle) => Promise<void>
  listApprovedProjectRoots: () => string[]
}

export function createWorkerBackend(cfg: WorkerBackendConfig): WorkerBackend {
  if (cfg.mode === "native") {
    if (!cfg.isLoopback) {
      throw new Error("NativeWorker requires loopback public origin")
    }
    if (cfg.enabledUserCount > 1) {
      throw new NativeWorkerMultiUserDenied()
    }
    if (process.env.NODE_ENV === "production") {
      throw new Error("NativeWorker denied in production")
    }
    if (!cfg.workerScript) {
      throw new Error("native_requires_workerScript")
    }
  }
  const approvedRoots = cfg.approvedProjectRoots ?? []

  if (cfg.mode === "native") {
    return {
      mode: "native",
      listApprovedProjectRoots: () => approvedRoots,
      async start(userId) {
        const roots = userPrivateRoots(cfg.appDataRoot, userId)
        ensurePaths(roots)
        const privatePaths = [
          roots.home,
          roots.data,
          roots.config,
          roots.cache,
          cfg.appDataRoot,
        ]
        const internal = await startNativeWorker({
          appDataRoot: cfg.appDataRoot,
          userId,
          workerScript: cfg.workerScript!,
          ...(cfg.controlPlaneUrl !== undefined ? { controlPlaneUrl: cfg.controlPlaneUrl } : {}),
          ...(cfg.workerTokenSecret !== undefined ? { workerTokenSecret: cfg.workerTokenSecret } : {}),
          privatePaths,
        })
        const external: WorkerHandle = {
          userId,
          url: internal.url,
          authorization: internal.authorization,
          root: internal.root,
          env: internal.env,
          username: internal.username,
          password: internal.password,
          workerId: internal.workerId,
        }
        ;(external as WorkerHandle & { stop: () => Promise<void> }).stop = () => stopNativeWorker(internal)
        return external
      },
      async stop(handle) {
        const h = handle as WorkerHandle & { stop?: () => Promise<void> }
        if (typeof h.stop === "function") {
          await h.stop()
        }
      },
    }
  }

  // OCI path is intentionally not implemented yet — fail with an actionable message.
  const image = cfg.ociImage ? ` (image=${cfg.ociImage})` : ""
  throw new Error(
    `OCI worker backend is not implemented yet${image}. ` +
      `Use DWA_WORKER_MODE=native on loopback for single-user development, ` +
      `or wait for the dockerode-based OCI backend. ` +
      `Previous dry-run stub (oci_not_implemented_in_dry_run) has been removed.`,
  )
}
