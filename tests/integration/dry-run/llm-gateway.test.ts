import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { mkdirSync, rmSync } from "fs"
import { join } from "path"
import { randomBytes } from "crypto"
import { makeApp, createUser, type AppHandle } from "../../../packages/dataworks-control/src/http/server"
import { generateMasterKey } from "../../../packages/dataworks-control/src/secret/store"
import { LlmConnectionRepo } from "../../../packages/dataworks-control/src/llm/repo"
import { login } from "../../../packages/dataworks-control/src/auth/session"

const tmpDir = join(import.meta.dir, ".llm-gateway-test-tmp")
const dbPath = join(tmpDir, "test.db")
const secretsRoot = join(tmpDir, ".secrets")

// Fake LLM provider state
let fakeProvider: {
  server: { hostname: string; port: number; stop: () => void }
  last: { headers: Headers; body: string }
}

async function startFakeProvider(): Promise<typeof fakeProvider> {
  let recordedHeaders: Headers | null = null
  let recordedBody = ""
  const server = Bun.serve({
    port: 0, // OS-assigned to avoid conflicts with concurrent tests
    hostname: "127.0.0.1",
    async fetch(req) {
      recordedHeaders = req.headers
      recordedBody = await req.text()
      const body = [
        "data: chunk1\n\n",
        "data: chunk2\n\n",
        "data: chunk3\n\n",
        "data: [DONE]\n\n",
      ].join("")
      return new Response(body, {
        status: 200,
        headers: {
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
        },
      })
    },
  })
  return {
    server,
    get last() {
      return { headers: recordedHeaders!, body: recordedBody }
    },
  }
}

let appHandle: AppHandle
let sessionToken: string
let testConnectionId: string
const PROVIDER_SECRET = "provider-secret"
const SECRET_REF = "llm-gw-test-secret-ref"

beforeAll(async () => {
  // Wipe any prior-run state so we don't trip NativeWorkerMultiUserDenied
  // when stale users from a previous run still exist in test.db.
  rmSync(tmpDir, { recursive: true, force: true })
  mkdirSync(tmpDir, { recursive: true })
  const masterKey = generateMasterKey()
  appHandle = await makeApp({
    dbPath,
    secretsRoot,
    publicOrigin: "http://127.0.0.1:0",
    masterKey,
    startServer: true,
    worker: {
      appDataRoot: tmpDir,
      mode: "native",
      workerScript: join(import.meta.dir, "..", "..", "..", "scripts", "fake-opencode-worker.ts"),
    },
  })

  // Create a test user — use a unique email to avoid UNIQUE constraint
  // collisions when tests run concurrently or a previous DB was not cleaned up.
  const testEmail = `test-gateway-${randomBytes(4).toString("hex")}@example.com`
  try {
    await createUser({ email: testEmail, password: "testpass123", role: "user" }, appHandle.db)
  } catch (e: any) {
    if (!e.message?.includes("UNIQUE")) throw e
  }

  // Login to obtain a browser session token.
  // The LLM gateway validates via BrowserSessionTable (Bearer token → SHA-256 → session lookup),
  // NOT via the worker's Basic auth token.
  const session = await login(appHandle.db, { email: testEmail, password: "testpass123" })
  if (!session) throw new Error("login failed in test setup")
  sessionToken = session.token

  const user = appHandle.db.get<{ id: string }>("SELECT id FROM dwa_user WHERE email = ?", [testEmail])!

  // Start the fake upstream LLM provider BEFORE seeding the connection so the port is known
  fakeProvider = await startFakeProvider()

  // Seed a secret that the gateway will inject into the upstream request
  await appHandle.secrets.put(SECRET_REF, {
    accessKeyId: "test-key-id",
    accessKeySecret: PROVIDER_SECRET,
  })

  // Seed an LLM connection pointing at the fake provider
  const repo = new LlmConnectionRepo(appHandle.db)
  const conn = repo.create({
    user_id: user.id,
    provider_id: "anthropic",
    name: "gateway-integration-test",
    upstream_origin: `http://127.0.0.1:${fakeProvider.server.port}`,
    auth_strategy: "static_header",
    secret_ref: SECRET_REF,
    allowed_models: ["fake-model"],
    data_classification_allowlist: "workspace_files",
  })
  testConnectionId = conn.id
})

afterAll(async () => {
  fakeProvider?.server?.stop()
  if (appHandle?.server) appHandle.server.stop()
  try {
    const { rmSync } = await import("fs")
    rmSync(tmpDir, { recursive: true, force: true })
  } catch {}
})

describe("llm-gateway streaming integration", () => {
  test("gateway proxies streaming response and injects credential", async () => {
    const response = await fetch(`http://127.0.0.1:${appHandle.server!.port}/internal/llm/${testConnectionId}/v1/messages`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${sessionToken}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ model: "fake-model", messages: [{ role: "user", content: "hello" }] }),
    })
    expect(response.status).toBeGreaterThanOrEqual(200)
    expect(response.headers.get("content-type")).toContain("text/event-stream")
    const body = await response.text()
    expect(body).toContain("data: [DONE]")
    // static_header + bearer scheme → the injector sets Authorization: Bearer <secret>
    expect(fakeProvider.last.headers.get("authorization")).toBe(`Bearer ${PROVIDER_SECRET}`)
    // The worker/session token must NOT leak to the upstream provider
    expect(fakeProvider.last.headers.get("authorization")).not.toContain(sessionToken)
  })

  test("gateway rejects requests without worker token", async () => {
    const response = await fetch(`http://127.0.0.1:${appHandle.server!.port}/internal/llm/${testConnectionId}/v1/messages`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ model: "fake-model", messages: [] }),
    })
    expect(response.status).toBe(401)
  })

  test("gateway rejects unknown connection ID", async () => {
    const response = await fetch(`http://127.0.0.1:${appHandle.server!.port}/internal/llm/nonexistent-conn/v1/messages`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${sessionToken}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ model: "fake-model", messages: [] }),
    })
    expect(response.status).toBe(404)
  })
})
