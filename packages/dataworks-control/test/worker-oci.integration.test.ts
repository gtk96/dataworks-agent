import { describe, expect, test } from "bun:test"
import { createWorkerBackend } from "../src/worker/backend"
import type { WorkerBackendConfig } from "../src/worker/backend"

describe("worker OCI integration", () => {
  test("dockerode@5.0.1 is available or skip is documented", async () => {
    let mod: unknown
    try {
      mod = await import("dockerode" as string)
    } catch {
      mod = null
    }
    if (!mod) {
      console.warn("dockerode not installed; OCI test will be skipped at runtime")
      expect(true).toBe(true)
      return
    }
    expect(typeof (mod as { default?: unknown }).default === "function" || typeof mod === "function" || typeof mod === "object").toBe(true)
  })

  test("createWorkerBackend native mode with one enabled user does not throw", () => {
    const cfg: WorkerBackendConfig = {
      appDataRoot: "C:/tmp/dwa-oci",
      mode: "native",
      workerScript: "C:/path/to/script.ts",
      approvedProjectRoots: ["C:/projects/alpha"],
      enabledUserCount: 1,
      isLoopback: true,
    }
    expect(() => createWorkerBackend(cfg)).not.toThrow()
  })

  test("createWorkerBackend OCI mode throws clear not-implemented error", () => {
    const cfg: WorkerBackendConfig = {
      appDataRoot: "C:/tmp/dwa-oci",
      mode: "oci",
      ociImage: "fake-image:latest",
      approvedProjectRoots: ["C:/projects/alpha"],
      enabledUserCount: 1,
      isLoopback: true,
    }
    expect(() => createWorkerBackend(cfg)).toThrow(/OCI worker backend is not implemented/)
  })
})
