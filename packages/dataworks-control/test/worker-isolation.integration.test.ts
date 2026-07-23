import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { mkdtempSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { makeApp, createUser } from "../src/http/server"
import { authenticate } from "../src/auth/session"

let app: Awaited<ReturnType<typeof makeApp>>
let baseUrl = ""
let publicOrigin = ""
let appDataRoot = ""
let userAId = ""
let userBId = ""

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
  const tmp = mkdtempSync(join(tmpdir(), "dwa-iso-"))
  appDataRoot = tmp
  const masterKey = new Uint8Array(32).fill(11)
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

  await createUser({ email: "a@example.test", password: "correct-horse", role: "user" }, app.db)
  await createUser({ email: "b@example.test", password: "correct-horse", role: "user" }, app.db)
  const a = await authenticate(
    new Request("http://x/", { headers: { cookie: await loginCookie("a@example.test", "correct-horse") } }),
    app.db,
  )
  const b = await authenticate(
    new Request("http://x/", { headers: { cookie: await loginCookie("b@example.test", "correct-horse") } }),
    app.db,
  )
  userAId = a!.id
  userBId = b!.id
})

afterAll(async () => {
  if (app && "stop" in app && typeof (app as never as { stop?: () => void }).stop === "function") {
    (app as never as { stop: () => void }).stop()
  }
})

describe("worker isolation (native single-user-dev)", () => {
  test("user A and user B have distinct private roots", async () => {
    const cookieA = await loginCookie("a@example.test", "correct-horse")
    const cookieB = await loginCookie("b@example.test", "correct-horse")
    const resA = await fetch(`${baseUrl}/opencode/__test/worker`, { headers: { cookie: cookieA, Origin: publicOrigin } })
    const resB = await fetch(`${baseUrl}/opencode/__test/worker`, { headers: { cookie: cookieB, Origin: publicOrigin } })
    expect(resA.status).toBe(200)
    expect(resB.status).toBe(200)
    const bodyA = (await resA.json()) as { root: string; url: string; env: Record<string, string> }
    const bodyB = (await resB.json()) as { root: string; url: string; env: Record<string, string> }
    const envA = bodyA.env
    const envB = bodyB.env
    expect(envA.HOME).toContain(userAId)
    expect(envB.HOME).toContain(userBId)
    expect(envA.HOME).not.toBe(envB.HOME)
    expect(envA.XDG_DATA_HOME).not.toBe(envB.XDG_DATA_HOME)
  })

  test("user A cannot read user B's /__test/user path", async () => {
    const cookieA = await loginCookie("a@example.test", "correct-horse")
    const res = await fetch(`${baseUrl}/opencode/__test/user/${userBId}`, { headers: { cookie: cookieA, Origin: publicOrigin } })
    expect(res.status).toBe(404)
  })
})

