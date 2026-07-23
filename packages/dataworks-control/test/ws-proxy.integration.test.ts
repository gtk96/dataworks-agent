import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { mkdtempSync, readFileSync, existsSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { makeApp, createUser } from "../src/http/server"

let app: Awaited<ReturnType<typeof makeApp>>
let baseUrl = ""
let publicOrigin = ""
let appDataRoot = ""

async function loginCookie(email: string, password: string): Promise<string> {
  const res = await fetch(`${baseUrl}/api/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json", Origin: publicOrigin },
    body: JSON.stringify({ email, password }),
  })
  if (res.status !== 204) {
    const text = await res.text()
    throw new Error(`login failed for ${email}: ${res.status} ${text}`)
  }
  const cookie = res.headers.get("set-cookie")
  if (!cookie) throw new Error("missing set-cookie")
  return cookie.split(";")[0]!
}

beforeAll(async () => {
  process.env.DATAWORKS_AGENT_MODE = "single-user-dev"
  process.env.NODE_ENV = "development"
  process.env.DATAWORKS_AGENT_ALLOW_TEST_ROUTES = "1"
  const tmp = mkdtempSync(join(tmpdir(), "dwa-ws-"))
  appDataRoot = tmp
  const masterKey = new Uint8Array(32).fill(17)
  publicOrigin = "http://127.0.0.1:0"
  app = await makeApp({
    dbPath: join(tmp, "control.sqlite"),
    publicOrigin,
    secretsRoot: join(tmp, "secrets"),
    masterKey,
    migrationsDir: join(import.meta.dir, "..", "migration"),
    worker: {
      appDataRoot: tmp,
      mode: "native",
      workerScript: join(import.meta.dir, "..", "..", "..", "scripts", "fake-opencode-worker.ts"),
      approvedProjectRoots: [],
    },
  } as never)
  publicOrigin = app.publicOrigin
  baseUrl = publicOrigin

  await createUser({ email: "ws@example.test", password: "correct-horse", role: "user" }, app.db)
})

afterAll(async () => {
  if (app?.server) app.server.stop()
  if (app?.workerSupervisor) {
    try {
      await app.workerSupervisor.dispose()
    } catch {
      // ignore
    }
  }
})

describe("opencode websocket proxy", () => {
  test("HTTP /opencode/env health works and managed plugin config is written", async () => {
    const cookie = await loginCookie("ws@example.test", "correct-horse")
    const health = await fetch(`${baseUrl}/opencode/env`, {
      headers: { cookie, Origin: publicOrigin },
    })
    expect(health.status).toBe(200)
    const body = (await health.json()) as Record<string, unknown>
    expect(body.HOME).toBeTruthy()

    const workerMeta = await fetch(`${baseUrl}/opencode/__test/worker`, {
      headers: { cookie, Origin: publicOrigin },
    })
    expect(workerMeta.status).toBe(200)
    const meta = (await workerMeta.json()) as {
      root: string
      env: Record<string, string | boolean>
      hasWorkerToken?: boolean
    }
    const rawText = JSON.stringify(meta)
    // Never leak raw worker tokens or passwords in the test meta endpoint.
    expect(rawText).not.toMatch(/DATAWORKS_WORKER_TOKEN":\s*"[^"]{8,}/)
    expect(meta.env).not.toHaveProperty("DATAWORKS_WORKER_TOKEN")
    expect(meta.env).not.toHaveProperty("WORKER_PASSWORD")
    expect(meta.env).not.toHaveProperty("OPENCODE_SERVER_PASSWORD")
    expect(meta.hasWorkerToken === true || meta.env.hasWorkerToken === true || meta.env.hasWorkerToken === "1").toBe(
      true,
    )

    const opencodeJson = join(meta.root, ".config", "opencode", "opencode.json")
    expect(existsSync(opencodeJson)).toBe(true)
    const cfg = JSON.parse(readFileSync(opencodeJson, "utf-8")) as { plugin?: string[] }
    expect(cfg.plugin).toContain("@dataworks-agent/plugin")

    // Dual-write: providers.json under HOME and XDG_CONFIG_HOME layouts
    const homeProviders = join(meta.root, ".config", "opencode", "providers.json")
    expect(existsSync(homeProviders)).toBe(true)
    const xdgConfig = String(meta.env.XDG_CONFIG_HOME ?? "")
    if (xdgConfig) {
      expect(existsSync(join(xdgConfig, "opencode", "providers.json"))).toBe(true)
      expect(existsSync(join(xdgConfig, "opencode", "opencode.json"))).toBe(true)
    }

    expect(meta.env.DATAWORKS_CONTROL_PLANE_URL).toBeTruthy()
    expect(meta.env.DATAWORKS_WORKER_ID).toBeTruthy()
    expect(meta.env.DWA_PRIVATE_PATHS).toBeTruthy()
    const privatePaths = JSON.parse(String(meta.env.DWA_PRIVATE_PATHS)) as string[]
    expect(Array.isArray(privatePaths)).toBe(true)
    expect(privatePaths.length).toBeGreaterThan(0)

    // NODE_PATH should help resolve @dataworks-agent/plugin
    expect(String(meta.env.NODE_PATH ?? "")).toContain("node_modules")
  })

  test("__test routes are gated without ALLOW flag", async () => {
    const prev = process.env.DATAWORKS_AGENT_ALLOW_TEST_ROUTES
    process.env.DATAWORKS_AGENT_ALLOW_TEST_ROUTES = "0"
    try {
      const cookie = await loginCookie("ws@example.test", "correct-horse")
      const res = await fetch(`${baseUrl}/opencode/__test/worker`, {
        headers: { cookie, Origin: publicOrigin },
      })
      expect(res.status).toBe(404)
    } finally {
      process.env.DATAWORKS_AGENT_ALLOW_TEST_ROUTES = prev ?? "1"
    }
  })

  test("WebSocket upgrade is not 501 and relays messages with Basic auth", async () => {
    const cookie = await loginCookie("ws@example.test", "correct-horse")

    await new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(`${baseUrl.replace(/^http/, "ws")}/opencode/ws-echo`, {
        headers: {
          cookie,
          Origin: publicOrigin,
        },
      } as never)

      const timer = setTimeout(() => {
        try {
          ws.close()
        } catch {
          // ignore
        }
        reject(new Error("ws_timeout"))
      }, 5000)

      ws.onopen = () => {
        ws.send("hello-proxy")
      }
      ws.onmessage = (ev) => {
        try {
          expect(String(ev.data)).toBe("echo:hello-proxy")
          clearTimeout(timer)
          ws.close()
          resolve()
        } catch (err) {
          clearTimeout(timer)
          reject(err)
        }
      }
      ws.onerror = () => {
        clearTimeout(timer)
        reject(new Error("ws_error"))
      }
    })
  })

  test("WebSocket with bad Origin is rejected", async () => {
    const cookie = await loginCookie("ws@example.test", "correct-horse")
    await new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(`${baseUrl.replace(/^http/, "ws")}/opencode/ws-echo`, {
        headers: {
          cookie,
          Origin: "http://evil.example",
        },
      } as never)
      const timer = setTimeout(() => {
        try {
          ws.close()
        } catch {
          // ignore
        }
        // Timed out without open is also a successful reject
        resolve()
      }, 1500)
      ws.onopen = () => {
        clearTimeout(timer)
        try {
          ws.close()
        } catch {
          // ignore
        }
        reject(new Error("expected origin rejection"))
      }
      ws.onerror = () => {
        clearTimeout(timer)
        resolve()
      }
      ws.onclose = () => {
        clearTimeout(timer)
        resolve()
      }
    })
  })
})
