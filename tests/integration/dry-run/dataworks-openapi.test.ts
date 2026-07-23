import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { mkdirSync, rmSync } from "fs"
import { join } from "path"
import { randomBytes } from "crypto"
import { makeApp, createUser, type AppHandle } from "../../../packages/dataworks-control/src/http/server"
import { generateMasterKey } from "../../../packages/dataworks-control/src/secret/store"
import { createDataConnection } from "../../../packages/dataworks-control/src/data-connection/repo"
import { login } from "../../../packages/dataworks-control/src/auth/session"

const tmpDir = join(import.meta.dir, ".dataworks-openapi-test-tmp")
const dbPath = join(tmpDir, "test.db")
const secretsRoot = join(tmpDir, ".secrets")

let appHandle: AppHandle
let sessionToken: string
let connection: { id: string; name: string; region: string }

beforeAll(async () => {
  rmSync(tmpDir, { recursive: true, force: true })
  mkdirSync(tmpDir, { recursive: true })
  const masterKey = generateMasterKey()
  appHandle = await makeApp({
    dbPath,
    secretsRoot,
    publicOrigin: "http://127.0.0.1:0",
    masterKey,
    startServer: true,
  })

  const testEmail = `test-dataworks-${randomBytes(4).toString("hex")}@example.com`
  try {
    await createUser({ email: testEmail, password: "testpass123", role: "user" }, appHandle.db)
  } catch (e: any) {
    if (!e.message?.includes("UNIQUE")) throw e
  }

  const session = await login(appHandle.db, { email: testEmail, password: "testpass123" })
  if (!session) throw new Error("login failed in test setup")
  sessionToken = session.token

  const user = appHandle.db.get<{ id: string }>("SELECT id FROM dwa_user WHERE email = ?", [testEmail])!

  connection = await createDataConnection(appHandle.db, appHandle.secrets, {
    user_id: user.id,
    name: "dwa-staging-conn",
    region: "cn-hangzhou",
    access_key_id: "STAGING_AK_FAKE_NOT_REAL_1234",
    access_key_secret: "STAGING_SK_FAKE_NOT_REAL_SECRET_DO_NOT_USE",
    write_enabled: false,
  })
})

afterAll(async () => {
  if (appHandle?.server) appHandle.server.stop()
  try {
    const { rmSync } = await import("fs")
    rmSync(tmpDir, { recursive: true, force: true })
  } catch {}
})

function cookieHeader(token: string): string {
  return `dwa_session=${encodeURIComponent(token)}`
}

describe("dataworks openapi dry-run integration", () => {
  test("returns sanitized fixture projects for the selected connection", async () => {
    const origin = appHandle.publicOrigin
    const response = await fetch(
      `${origin}/api/dataworks/projects?connectionID=${connection.id}`,
      {
        method: "GET",
        headers: {
          cookie: cookieHeader(sessionToken),
          origin,
          "content-type": "application/json",
        },
      },
    )
    expect(response.status).toBe(200)
    expect(await response.json()).toEqual([
      { id: 10001, name: "dwa_staging", envType: "DEV", region: "cn-hangzhou" },
    ])
  })
})
