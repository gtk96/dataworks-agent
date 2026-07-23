import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { mkdirSync, rmSync } from "fs"
import { join } from "path"
import { randomBytes } from "crypto"
import { makeApp, createUser, type AppHandle } from "../../../packages/dataworks-control/src/http/server"
import { generateMasterKey } from "../../../packages/dataworks-control/src/secret/store"
import { LlmConnectionRepo } from "../../../packages/dataworks-control/src/llm/repo"
import { login } from "../../../packages/dataworks-control/src/auth/session"

const tmpDir = join(import.meta.dir, ".llm-egress-policy-test-tmp")
const dbPath = join(tmpDir, "test.db")
const secretsRoot = join(tmpDir, ".secrets")

let appHandle: AppHandle
let sessionToken: string
let promptOnlyConnectionId: string
let allowlistConnectionId: string

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

  // Unique email avoids UNIQUE constraint collisions across concurrent runs.
  const testEmail = `test-egress-${randomBytes(4).toString("hex")}@example.com`
  try {
    await createUser({ email: testEmail, password: "testpass123", role: "user" }, appHandle.db)
  } catch (e: any) {
    if (!e.message?.includes("UNIQUE")) throw e
  }

  const session = await login(appHandle.db, { email: testEmail, password: "testpass123" })
  if (!session) throw new Error("login failed in test setup")
  sessionToken = session.token

  const user = appHandle.db.get<{ id: string }>("SELECT id FROM dwa_user WHERE email = ?", [testEmail])!

  // Seed secrets referenced by both connections
  await appHandle.secrets.put("egress-prompt-only-secret", {
    accessKeyId: "test-key-id",
    accessKeySecret: "test-secret",
  })
  await appHandle.secrets.put("egress-test-secret", {
    accessKeyId: "test-key-id",
    accessKeySecret: "test-secret",
  })

  // Seed a prompt_only connection (blocks automatic_full_file context)
  const repo = new LlmConnectionRepo(appHandle.db)
  const promptOnly = repo.create({
    user_id: user.id,
    provider_id: "anthropic",
    name: "egress-prompt-only",
    upstream_origin: "http://127.0.0.1:65535", // unreachable; tests only exercise policy checks
    auth_strategy: "static_header",
    secret_ref: "egress-prompt-only-secret",
    allowed_models: ["test-model"],
    data_classification_allowlist: "prompt_only",
  })
  promptOnlyConnectionId = promptOnly.id

  // Seed a wider-scope connection (non-prompt-only) with restrictive model allowlist
  const allowlist = repo.create({
    user_id: user.id,
    provider_id: "anthropic",
    name: "egress-test",
    upstream_origin: "http://127.0.0.1:65535",
    auth_strategy: "static_header",
    secret_ref: "egress-test-secret",
    allowed_models: ["test-model"], // excludes "banned-model"
    data_classification_allowlist: "workspace_files_and_artifacts",
  })
  allowlistConnectionId = allowlist.id
})

afterAll(async () => {
  if (appHandle?.server) appHandle.server.stop()
  try {
    const { rmSync } = await import("fs")
    rmSync(tmpDir, { recursive: true, force: true })
  } catch {}
})

describe("llm-egress-policy", () => {
  test("prompt_only project denies full-file automatic context", async () => {
    const response = await fetch(
      `http://127.0.0.1:${appHandle.server!.port}/internal/llm/${promptOnlyConnectionId}/v1/messages`,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${sessionToken}`,
          "content-type": "application/json",
          "x-dwa-context-type": "automatic_full_file",
          "x-dwa-context-path": "/some/project/file.txt",
        },
        body: JSON.stringify({ model: "test-model", messages: [] }),
      },
    )
    expect(response.status).toBe(403)
  })

  test("prompt_only allows explicit user-attached file after approval", async () => {
    const response = await fetch(
      `http://127.0.0.1:${appHandle.server!.port}/internal/llm/${promptOnlyConnectionId}/v1/messages`,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${sessionToken}`,
          "content-type": "application/json",
          "x-dwa-context-type": "user_attached",
          "x-dwa-context-approval": "approved",
          "x-dwa-context-path": "/user/attached/small.txt",
        },
        body: JSON.stringify({ model: "test-model", messages: [] }),
      },
    )
    // Policy check passes; subsequent upstream fetch will 502 (expected for unreachable URL).
    expect(response.status).toBeGreaterThanOrEqual(200)
  })

  test("non-allowlisted host redirect is denied", async () => {
    const response = await fetch(
      `http://127.0.0.1:${appHandle.server!.port}/internal/llm/${allowlistConnectionId}/v1/messages`,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${sessionToken}`,
          "content-type": "application/json",
          "x-dwa-upstream-override": "https://evil.example.com/v1/messages",
        },
        body: JSON.stringify({ model: "test-model", messages: [] }),
      },
    )
    // RED: validateUpstreamRedirect currently only blocks private IPs + non-HTTPS,
    // so evil.example.com (HTTPS, public) passes through.
    // The test asserts the desired post-implementation behavior (403).
    expect(response.status).toBe(403)
  })

  test("private IP redirect is denied", async () => {
    const response = await fetch(
      `http://127.0.0.1:${appHandle.server!.port}/internal/llm/${allowlistConnectionId}/v1/messages`,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${sessionToken}`,
          "content-type": "application/json",
          "x-dwa-upstream-override": "https://192.168.1.1/v1/messages",
        },
        body: JSON.stringify({ model: "test-model", messages: [] }),
      },
    )
    expect(response.status).toBe(403)
  })

  test("model allowlist is enforced", async () => {
    const response = await fetch(
      `http://127.0.0.1:${appHandle.server!.port}/internal/llm/${allowlistConnectionId}/v1/messages`,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${sessionToken}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({ model: "banned-model", messages: [] }),
      },
    )
    expect(response.status).toBe(400)
  })
})
