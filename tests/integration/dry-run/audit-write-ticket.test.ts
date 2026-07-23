import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { randomBytes } from "crypto"
import { copyFileSync, mkdirSync, rmSync } from "fs"
import { join } from "path"
import { hashAuditArgs } from "../../../packages/dataworks-core/src/audit"
import { login } from "../../../packages/dataworks-control/src/auth/session"
import { makeDatabase } from "../../../packages/dataworks-control/src/database"
import { createDataConnection } from "../../../packages/dataworks-control/src/data-connection/repo"
import { AuditRepo } from "../../../packages/dataworks-control/src/audit/repo"
import { makeApp, createUser, type AppHandle } from "../../../packages/dataworks-control/src/http/server"
import { generateMasterKey } from "../../../packages/dataworks-control/src/secret/store"
import { signWorkerToken } from "../../../packages/dataworks-control/src/worker/token"

const tmpDir = join(import.meta.dir, ".audit-write-ticket-test-tmp")
const workerTokenSecret = randomBytes(32)
const workerID = "dry-run-worker-1"
const args = { projectID: 10001, instanceID: 90001 }
const argsHash = hashAuditArgs(args)

let appHandle: AppHandle
let sessionToken: string
let user: { id: string }
let connectionID: string
let disabledConnectionID: string

beforeAll(async () => {
  rmSync(tmpDir, { recursive: true, force: true })
  mkdirSync(tmpDir, { recursive: true })
  // Dry-run write path (product fixtures). Do not set DATAWORKS_AGENT_MODE=staging here.
  delete process.env.DATAWORKS_AGENT_MODE
  appHandle = await makeApp({
    dbPath: join(tmpDir, "test.db"),
    secretsRoot: join(tmpDir, ".secrets"),
    publicOrigin: "http://dwa.test",
    masterKey: generateMasterKey(),
    workerTokenSecret,
    startServer: false,
  })

  const email = `audit-${randomBytes(4).toString("hex")}@example.com`
  await createUser({ email, password: "testpass123", role: "user" }, appHandle.db)
  user = appHandle.db.get<{ id: string }>("SELECT id FROM dwa_user WHERE email = ?", [email])!
  const session = await login(appHandle.db, { email, password: "testpass123" })
  if (!session) throw new Error("login failed in test setup")
  sessionToken = session.token

  connectionID = (await createDataConnection(appHandle.db, appHandle.secrets, {
    user_id: user.id,
    name: "audited-staging",
    region: "cn-hangzhou",
    access_key_id: "AUDIT_AK_FAKE_NOT_REAL",
    access_key_secret: "AUDIT_SK_FAKE_NOT_REAL",
    write_enabled: true,
  })).id
  disabledConnectionID = (await createDataConnection(appHandle.db, appHandle.secrets, {
    user_id: user.id,
    name: "read-only-staging",
    region: "cn-hangzhou",
    access_key_id: "READ_ONLY_AK_FAKE_NOT_REAL",
    access_key_secret: "READ_ONLY_SK_FAKE_NOT_REAL",
    write_enabled: false,
  })).id
})

afterAll(() => {
  if (appHandle?.server) appHandle.server.stop()
  appHandle.db.close()
  rmSync(tmpDir, { recursive: true, force: true })
})

function request(path: string, init: RequestInit) {
  return appHandle.app.request(`http://dwa.test${path}`, init)
}

async function issueWriteTicket(reason: string, conn = connectionID, tool = "dw_rerun_job", hash = argsHash) {
  const response = await request("/api/write-tickets", {
    method: "POST",
    headers: {
      cookie: `dwa_session=${encodeURIComponent(sessionToken)}`,
      origin: "http://dwa.test",
      "content-type": "application/json",
    },
    body: JSON.stringify({ connectionID: conn, tool, argsHash: hash, reason }),
  })
  expect(response.status).toBe(201)
  return (await response.json() as { ticket: string }).ticket
}

async function execute(ticket: string, extraHeaders: Record<string, string> = {}) {
  return request("/internal/dataworks/execute", {
    method: "POST",
    headers: {
      authorization: `Bearer ${signWorkerToken(workerTokenSecret, {
        userID: user.id,
        workerID,
        expires: Date.now() + 30_000,
      })}`,
      "x-dataworks-worker-id": workerID,
      "content-type": "application/json",
      ...extraHeaders,
    },
    body: JSON.stringify({ ticket, connectionID, tool: "dw_rerun_job", args }),
  })
}

async function browserExecute(ticket: string, bodyArgs: Record<string, unknown> = args, conn = connectionID) {
  return request("/api/dataworks/write", {
    method: "POST",
    headers: {
      cookie: `dwa_session=${encodeURIComponent(sessionToken)}`,
      origin: "http://dwa.test",
      "content-type": "application/json",
    },
    body: JSON.stringify({
      ticket,
      connectionID: conn,
      tool: "dw_rerun_job",
      args: bodyArgs,
    }),
  })
}

describe("audited one-time DataWorks write tickets", () => {
  test("executes once, rejects replay, and records a redacted success audit", async () => {
    const reason = "retry failed staging job"
    const ticket = await issueWriteTicket(reason)

    expect((await execute(ticket)).status).toBe(200)
    expect((await execute(ticket)).status).toBe(409)

    const latest = new AuditRepo(appHandle.db).list({ userID: user.id, limit: 1 })[0]
    expect(latest).toMatchObject({
      userID: user.id,
      connectionID,
      tool: "dw_rerun_job",
      permission: "write",
      argsHash,
      reason,
      outcome: "success",
    })
    expect(JSON.stringify(latest)).not.toContain(String(args.instanceID))
    const storedTicket = appHandle.db.get<{ token_hash: string; time_expires: number }>(
      "SELECT token_hash, time_expires FROM dwa_write_ticket ORDER BY time_expires LIMIT 1",
    )!
    expect(storedTicket.token_hash).toMatch(/^[a-f0-9]{64}$/)
    expect(storedTicket.token_hash).not.toBe(ticket)
    expect(storedTicket.time_expires - Date.now()).toBeGreaterThan(59_000)
    expect(storedTicket.time_expires - Date.now()).toBeLessThanOrEqual(60_000)
  })

  test("rejects browser cookies on the internal worker endpoint", async () => {
    const ticket = await issueWriteTicket("verify worker-only authentication")
    const response = await execute(ticket, { cookie: `dwa_session=${encodeURIComponent(sessionToken)}` })
    expect(response.status).toBe(403)
  })

  test("rejects a signed token presented by the wrong worker process", async () => {
    const ticket = await issueWriteTicket("verify worker process identity")
    const response = await execute(ticket, { "x-dataworks-worker-id": "different-worker" })
    expect(response.status).toBe(401)
  })

  test("does not issue tickets when the connection has writes disabled", async () => {
    const response = await request("/api/write-tickets", {
      method: "POST",
      headers: {
        cookie: `dwa_session=${encodeURIComponent(sessionToken)}`,
        origin: "http://dwa.test",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        connectionID: disabledConnectionID,
        tool: "dw_rerun_job",
        argsHash,
        reason: "this must remain read-only",
      }),
    })
    expect(response.status).toBe(403)
  })

  test("browser write path issues ticket, executes dry-run write, audits success", async () => {
    const reason = "jobs page rerun dry-run"
    const ticket = await issueWriteTicket(reason)
    const response = await browserExecute(ticket)
    expect(response.status).toBe(200)
    const body = await response.json() as { status: string; dryRun?: boolean }
    expect(body.status).toBe("queued")
    expect(body.dryRun).toBe(true)

    // replay rejected
    expect((await browserExecute(ticket)).status).toBe(409)

    const latest = new AuditRepo(appHandle.db).list({ userID: user.id, limit: 1 })[0]
    expect(latest).toMatchObject({
      tool: "dw_rerun_job",
      reason,
      outcome: "success",
      permission: "write",
    })
  })

  test("browser write denied when write_enabled is false (ticket cannot issue)", async () => {
    const response = await request("/api/write-tickets", {
      method: "POST",
      headers: {
        cookie: `dwa_session=${encodeURIComponent(sessionToken)}`,
        origin: "http://dwa.test",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        connectionID: disabledConnectionID,
        tool: "dw_pause_schedule",
        argsHash: hashAuditArgs({ connectionID: disabledConnectionID, projectID: 1, scheduleID: 2, paused: true }),
        reason: "pause must fail closed",
      }),
    })
    expect(response.status).toBe(403)
    const err = await response.json() as { error: string }
    expect(err.error).toBe("write_disabled")
  })

  test("browser jobs reject path records write-reject audit (denied/rejected)", async () => {
    // Mirrors Jobs page cancelAction → POST /api/audit/write-reject (same as WriteConfirmation).
    const rejectArgs = { connectionID, projectID: 10001, instanceID: 90001 }
    const rejectHash = hashAuditArgs(rejectArgs)
    const response = await request("/api/audit/write-reject", {
      method: "POST",
      headers: {
        cookie: `dwa_session=${encodeURIComponent(sessionToken)}`,
        origin: "http://dwa.test",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        connectionID,
        tool: "dw_rerun_job",
        argsHash: rejectHash,
      }),
    })
    expect(response.status).toBe(200)
    const body = await response.json() as { ok?: boolean }
    expect(body.ok).toBe(true)

    const latest = new AuditRepo(appHandle.db).list({ userID: user.id, limit: 1 })[0]
    expect(latest).toMatchObject({
      userID: user.id,
      connectionID,
      tool: "dw_rerun_job",
      permission: "write",
      argsHash: rejectHash,
      outcome: "denied",
      errorCode: "rejected",
    })
    // Redacted: raw instance id must not appear in the stored audit row.
    expect(JSON.stringify(latest)).not.toContain(String(rejectArgs.instanceID))
  })

  test("upgrades the existing migration chain without losing prior records", async () => {
    const legacyMigrations = join(tmpDir, "legacy-migrations")
    const migrationRoot = join(import.meta.dir, "..", "..", "..", "packages", "dataworks-control", "migration")
    mkdirSync(legacyMigrations, { recursive: true })
    for (const name of ["0001_auth.sql", "0002_rate_limit.sql", "0003_data_connections.sql", "0004_llm_connections.sql"]) {
      copyFileSync(join(migrationRoot, name), join(legacyMigrations, name))
    }

    const upgradePath = join(tmpDir, "upgrade.db")
    const legacy = await makeDatabase({ dbPath: upgradePath, migrationsDir: legacyMigrations })
    legacy.run("INSERT INTO dwa_user VALUES (?, ?, ?, ?, ?, ?, ?)", ["legacy-user", "legacy@example.com", "hash", "user", 0, 1, 1])
    legacy.run("INSERT INTO dwa_browser_session VALUES (?, ?, ?, ?)", ["legacy-session", "legacy-user", Date.now() + 60_000, 1])
    legacy.run("INSERT INTO dwa_data_connection VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
      "legacy-data", "legacy-user", "data", "cn-hangzhou", "masked", "masked", "secret:data", 0, 1, 1,
    ])
    legacy.run("INSERT INTO dwa_llm_connection VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
      "legacy-llm", "legacy-user", "fixture", "llm", "https://example.invalid", "bearer", "secret:llm", 1, "[]", "prompt_only", 1, 1,
    ])
    legacy.close()

    const upgraded = await makeDatabase({ dbPath: upgradePath, migrationsDir: migrationRoot })
    expect(upgraded.get<{ email: string }>("SELECT email FROM dwa_user WHERE id = 'legacy-user'")?.email).toBe("legacy@example.com")
    expect(upgraded.get("SELECT 1 FROM dwa_browser_session WHERE token_hash = 'legacy-session'")).toBeTruthy()
    expect(upgraded.get("SELECT 1 FROM dwa_data_connection WHERE id = 'legacy-data'")).toBeTruthy()
    expect(upgraded.get("SELECT 1 FROM dwa_llm_connection WHERE id = 'legacy-llm'")).toBeTruthy()
    expect(upgraded.get("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'dwa_audit'")).toBeTruthy()
    expect(upgraded.get("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'dwa_write_ticket'")).toBeTruthy()
    upgraded.close()
  })
})
