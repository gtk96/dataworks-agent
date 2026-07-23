import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { mkdirSync, rmSync } from "fs"
import { join } from "path"
import { randomBytes } from "crypto"
import { makeApp, createUser, type AppHandle } from "../../../packages/dataworks-control/src/http/server"
import { generateMasterKey } from "../../../packages/dataworks-control/src/secret/store"
import { createDataConnection } from "../../../packages/dataworks-control/src/data-connection/repo"
import { login } from "../../../packages/dataworks-control/src/auth/session"
import { setOdpsServiceForTests } from "../../../packages/dataworks-control/src/http/dataworks-api"
import type { OdpsService, OdpsQueryInput } from "../../../packages/dataworks-control/src/odps/service"
import type { QueryResult } from "../../../packages/dataworks-control/src/odps/protocol"
import { evaluateSql } from "../../../packages/dataworks-control/src/odps/sql-policy"
import { OdpsPolicyError } from "../../../packages/dataworks-control/src/odps/service"

const tmpDir = join(import.meta.dir, ".dataworks-tables-sql-test-tmp")
const dbPath = join(tmpDir, "test.db")
const secretsRoot = join(tmpDir, ".secrets")

let appHandle: AppHandle
let sessionToken: string
let connection: { id: string; name: string; region: string }

function cookieHeader(token: string): string {
  return `dwa_session=${encodeURIComponent(token)}`
}

function makeFakeOdps(opts?: {
  onQuery?: (input: OdpsQueryInput) => void
  result?: QueryResult
}): OdpsService {
  return {
    async query(input) {
      const policy = evaluateSql(input.sql)
      if (!policy.ok) throw new OdpsPolicyError(policy.error!)
      opts?.onQuery?.(input)
      return (
        opts?.result ?? {
          columns: [{ name: "_c0", type: "BIGINT" }],
          rows: [[1]],
          truncated: false,
          instance_id: "dry-run",
          duration_ms: 1,
        }
      )
    },
    async health() {
      return { ok: true, version: "test", dry_run: true }
    },
    async stop() {},
  }
}

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

  const testEmail = `test-tables-sql-${randomBytes(4).toString("hex")}@example.com`
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
    name: "dwa-tables-sql-conn",
    region: "cn-hangzhou",
    access_key_id: "STAGING_AK_FAKE_NOT_REAL_1234",
    access_key_secret: "STAGING_SK_FAKE_NOT_REAL_SECRET_DO_NOT_USE",
    write_enabled: false,
  })

  setOdpsServiceForTests(makeFakeOdps())
})

afterAll(async () => {
  setOdpsServiceForTests(null)
  if (appHandle?.server) appHandle.server.stop()
  try {
    rmSync(tmpDir, { recursive: true, force: true })
  } catch {}
})

describe("dataworks tables + sql browser APIs (dry-run)", () => {
  test("GET /api/dataworks/tables returns fixture tables for connection+project", async () => {
    const origin = appHandle.publicOrigin
    const response = await fetch(
      `${origin}/api/dataworks/tables?connectionID=${connection.id}&projectID=10001`,
      {
        method: "GET",
        headers: {
          cookie: cookieHeader(sessionToken),
          origin,
        },
      },
    )
    expect(response.status).toBe(200)
    const body = (await response.json()) as Array<{ name: string }>
    expect(Array.isArray(body)).toBe(true)
    expect(body.length).toBeGreaterThan(0)
    expect(body.some((t) => t.name === "test_table")).toBe(true)
  })

  test("GET /api/dataworks/tables supports keyword filter", async () => {
    const origin = appHandle.publicOrigin
    const response = await fetch(
      `${origin}/api/dataworks/tables?connectionID=${connection.id}&projectID=10001&keyword=raw`,
      {
        method: "GET",
        headers: {
          cookie: cookieHeader(sessionToken),
          origin,
        },
      },
    )
    expect(response.status).toBe(200)
    const body = (await response.json()) as Array<{ name: string }>
    expect(body.every((t) => t.name.toLowerCase().includes("raw"))).toBe(true)
  })

  test("GET /api/dataworks/tables/:name describes a fixture table", async () => {
    const origin = appHandle.publicOrigin
    const response = await fetch(
      `${origin}/api/dataworks/tables/test_table?connectionID=${connection.id}&projectID=10001`,
      {
        method: "GET",
        headers: {
          cookie: cookieHeader(sessionToken),
          origin,
        },
      },
    )
    expect(response.status).toBe(200)
    const body = (await response.json()) as { name: string; columns: unknown[] }
    expect(body.name).toBe("test_table")
    expect(Array.isArray(body.columns)).toBe(true)
    expect(body.columns.length).toBeGreaterThan(0)
  })

  test("POST /api/dataworks/sql accepts SELECT and returns bounded result", async () => {
    const origin = appHandle.publicOrigin
    const response = await fetch(`${origin}/api/dataworks/sql`, {
      method: "POST",
      headers: {
        cookie: cookieHeader(sessionToken),
        origin,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        connectionID: connection.id,
        projectID: 10001,
        projectName: "dwa_staging",
        sql: "SELECT 1",
      }),
    })
    expect(response.status).toBe(200)
    const body = (await response.json()) as {
      columns: unknown[]
      rows: unknown[][]
      truncated: boolean
    }
    expect(Array.isArray(body.columns)).toBe(true)
    expect(body.rows).toEqual([[1]])
    expect(body.truncated).toBe(false)
  })

  test("POST /api/dataworks/sql rejects DML via SQL policy (400)", async () => {
    const origin = appHandle.publicOrigin
    const response = await fetch(`${origin}/api/dataworks/sql`, {
      method: "POST",
      headers: {
        cookie: cookieHeader(sessionToken),
        origin,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        connectionID: connection.id,
        projectID: 10001,
        sql: "DELETE FROM test_table WHERE 1=1",
      }),
    })
    expect(response.status).toBe(400)
    const body = (await response.json()) as { error: { _tag?: string; code?: string; message?: string } }
    expect(body.error?._tag === "SqlPolicyDenied" || body.error?.code === "BANNED_TOKEN" || typeof body.error?.message === "string").toBe(
      true,
    )
  })

  test("POST /api/dataworks/sql rejects multi-statement", async () => {
    const origin = appHandle.publicOrigin
    const response = await fetch(`${origin}/api/dataworks/sql`, {
      method: "POST",
      headers: {
        cookie: cookieHeader(sessionToken),
        origin,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        connectionID: connection.id,
        projectID: 10001,
        sql: "SELECT 1; DROP TABLE x",
      }),
    })
    expect(response.status).toBe(400)
  })
})
