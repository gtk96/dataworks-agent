import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { randomBytes } from "crypto"
import { mkdirSync, rmSync } from "fs"
import { join } from "path"
import { hashAuditArgs } from "../../dataworks-core/src/audit"
import type { UserID } from "../../dataworks-core/src/identity"
import { AuditRepo } from "../../dataworks-control/src/audit/repo"
import { createDataConnection } from "../../dataworks-control/src/data-connection/repo"
import { makeApp, createUser, type AppHandle } from "../../dataworks-control/src/http/server"
import { generateMasterKey } from "../../dataworks-control/src/secret/store"
import { signWorkerToken } from "../../dataworks-control/src/worker/token"
import { dataworksPlugin } from "../src/index"
import { WritePermissionDeniedError } from "../src/permission"
import type { ToolContext } from "@opencode-ai/plugin"

const tmpDir = join(import.meta.dir, ".write-permission-test-tmp")
const workerTokenSecret = randomBytes(32)
const workerID = "write-perm-worker-1"
const args = { projectID: 10001, instanceID: 90001 }

let appHandle: AppHandle
let sessionToken: string
let user: { id: string }
let enabledConnectionID: string
let disabledConnectionID: string
let workerToken: string

beforeAll(async () => {
  rmSync(tmpDir, { recursive: true, force: true })
  mkdirSync(tmpDir, { recursive: true })
  appHandle = await makeApp({
    dbPath: join(tmpDir, "test.db"),
    secretsRoot: join(tmpDir, ".secrets"),
    publicOrigin: "http://dwa.test",
    masterKey: generateMasterKey(),
    workerTokenSecret,
    startServer: false,
  })

  const email = `write-perm-${randomBytes(4).toString("hex")}@example.com`
  await createUser({ email, password: "testpass123", role: "user" }, appHandle.db)
  user = appHandle.db.get<{ id: string }>("SELECT id FROM dwa_user WHERE email = ?", [email])!
  const loginRes = await appHandle.app.request("http://dwa.test/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json", origin: "http://dwa.test" },
    body: JSON.stringify({ email, password: "testpass123" }),
  })
  expect(loginRes.status).toBe(204)
  const setCookie = loginRes.headers.get("set-cookie") ?? ""
  sessionToken = setCookie.split(";")[0]!.replace(/^dwa_session=/, "")

  enabledConnectionID = (
    await createDataConnection(appHandle.db, appHandle.secrets, {
      user_id: user.id as UserID,
      name: "write-enabled",
      region: "cn-hangzhou",
      access_key_id: "WRITE_AK_FAKE_NOT_REAL",
      access_key_secret: "WRITE_SK_FAKE_NOT_REAL",
      write_enabled: true,
    })
  ).id
  disabledConnectionID = (
    await createDataConnection(appHandle.db, appHandle.secrets, {
      user_id: user.id as UserID,
      name: "write-disabled",
      region: "cn-hangzhou",
      access_key_id: "READ_AK_FAKE_NOT_REAL",
      access_key_secret: "READ_SK_FAKE_NOT_REAL",
      write_enabled: false,
    })
  ).id

  workerToken = signWorkerToken(workerTokenSecret, {
    userID: user.id as UserID,
    workerID,
    expires: Date.now() + 60_000,
  })

  process.env.DATAWORKS_CONTROL_PLANE_URL = "http://dwa.test"
  process.env.DATAWORKS_WORKER_TOKEN = workerToken
  process.env.DATAWORKS_WORKER_ID = workerID

  // Patch global fetch so ControlPlaneClient hits the in-process Hono app.
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url
    if (url.startsWith("http://dwa.test")) {
      return appHandle.app.request(url, init)
    }
    return originalFetch(input as never, init)
  }) as typeof fetch
  ;(globalThis as { __dwaOriginalFetch?: typeof fetch }).__dwaOriginalFetch = originalFetch
})

afterAll(() => {
  const original = (globalThis as { __dwaOriginalFetch?: typeof fetch }).__dwaOriginalFetch
  if (original) globalThis.fetch = original
  process.env.DATAWORKS_CONTROL_PLANE_URL = ""
  process.env.DATAWORKS_WORKER_TOKEN = ""
  process.env.DATAWORKS_WORKER_ID = ""
  if (appHandle?.server) appHandle.server.stop()
  appHandle.db.close()
  rmSync(tmpDir, { recursive: true, force: true })
})

function makeCtx(options: {
  reason?: string
  reject?: boolean
  captureAsk?: (input: unknown) => void
}): ToolContext {
  return {
    sessionID: "ses_write_test",
    messageID: "msg_write_test",
    agent: "build",
    directory: tmpDir,
    worktree: tmpDir,
    abort: new AbortController().signal,
    metadata() {},
    extra: options.reason ? { dwWriteReason: options.reason } : {},
    async ask(input) {
      options.captureAsk?.(input)
      if (options.reject) {
        throw new Error("The user rejected permission to use this specific tool call.")
      }
      // approve path — reason comes from extra
    },
  } as ToolContext & { extra: Record<string, unknown> }
}

describe("write-tool permission", () => {
  test("writeEnabled=false → denied before ticket issuance", async () => {
    const tools = dataworksPlugin()
    const tool = tools.dw_rerun_job
    expect(tool).toBeTruthy()

    let asked = false
    const ctx = makeCtx({
      reason: "should never issue",
      captureAsk: () => {
        asked = true
      },
    })

    await expect(
      tool!.execute(
        { connectionID: disabledConnectionID, projectID: args.projectID, instanceID: args.instanceID },
        ctx,
      ),
    ).rejects.toMatchObject({ code: "write_disabled" })

    // No permission prompt when write is disabled (deny before ticket / ask).
    expect(asked).toBe(false)

    const tickets = appHandle.db.all("SELECT * FROM dwa_write_ticket")
    expect(tickets.length).toBe(0)
  })

  test('writeEnabled=true → emits permission.asked with permission="dw_write"', async () => {
    const tools = dataworksPlugin()
    const tool = tools.dw_rerun_job!

    let askedInput: { permission?: string; patterns?: string[]; always?: string[]; metadata?: Record<string, unknown> } | null =
      null
    const ctx = makeCtx({
      reason: "retry failed staging job",
      captureAsk: (input) => {
        askedInput = input as typeof askedInput
      },
    })

    const result = await tool.execute(
      { connectionID: enabledConnectionID, projectID: args.projectID, instanceID: args.instanceID },
      ctx,
    )

    expect(askedInput).toBeTruthy()
    expect(askedInput!.permission).toBe("dw_write")
    expect(askedInput!.always).toEqual([])
    expect(askedInput!.patterns).toContain(enabledConnectionID)
    expect(askedInput!.metadata?.tool).toBe("dw_rerun_job")
    expect(askedInput!.metadata?.argsHash).toBe(hashAuditArgs({
      connectionID: enabledConnectionID,
      projectID: args.projectID,
      instanceID: args.instanceID,
    }))
    expect(result).toMatchObject({ title: "dw_rerun_job" })
    expect(String((result as { output: string }).output)).not.toContain("WRITE_SK_FAKE")
  })

  test("reject reply → no execution / audit outcome=denied with errorCode=rejected", async () => {
    const tools = dataworksPlugin()
    const tool = tools.dw_rerun_job!
    const before = new AuditRepo(appHandle.db).list({ userID: user.id as UserID, limit: 50 }).length

    const ctx = makeCtx({ reject: true })
    await expect(
      tool.execute(
        { connectionID: enabledConnectionID, projectID: 20002, instanceID: 80002 },
        ctx,
      ),
    ).rejects.toBeInstanceOf(WritePermissionDeniedError)

    const audits = new AuditRepo(appHandle.db).list({ userID: user.id as UserID, limit: 50 })
    expect(audits.length).toBeGreaterThan(before)
    const latest = audits[0]!
    expect(latest.outcome).toBe("denied")
    expect(latest.errorCode).toBe("rejected")
    expect(latest.tool).toBe("dw_rerun_job")

    // No success execute for this reject path
    expect(audits.some((a) => a.outcome === "success" && a.argsHash === hashAuditArgs({
      connectionID: enabledConnectionID,
      projectID: 20002,
      instanceID: 80002,
    }))).toBe(false)
  })

  test("approve with empty reason → 400 / reason_required, no ticket", async () => {
    const tools = dataworksPlugin()
    const tool = tools.dw_rerun_job!
    const ticketsBefore = appHandle.db.all("SELECT * FROM dwa_write_ticket").length

    const ctx = makeCtx({ reason: "   " })
    try {
      await tool.execute(
        { connectionID: enabledConnectionID, projectID: 30003, instanceID: 70003 },
        ctx,
      )
      throw new Error("expected throw")
    } catch (error) {
      expect(error).toBeInstanceOf(WritePermissionDeniedError)
      expect((error as WritePermissionDeniedError).code).toBe("reason_required")
      expect((error as Error & { status?: number }).status).toBe(400)
    }

    expect(appHandle.db.all("SELECT * FROM dwa_write_ticket").length).toBe(ticketsBefore)
  })

  test("approve with reason → one-time ticket → one execution", async () => {
    const tools = dataworksPlugin()
    const tool = tools.dw_rerun_job!
    const runArgs = {
      connectionID: enabledConnectionID,
      projectID: 40004,
      instanceID: 60004,
    }
    const argsHash = hashAuditArgs(runArgs)

    const ctx = makeCtx({ reason: "approved one-time rerun" })
    const result = await tool.execute(runArgs, ctx)
    expect(result).toMatchObject({ title: "dw_rerun_job" })

    const audits = new AuditRepo(appHandle.db).list({ userID: user.id as UserID, limit: 20 })
    const success = audits.find((a) => a.argsHash === argsHash && a.outcome === "success")
    expect(success).toBeTruthy()
    expect(success!.reason).toBe("approved one-time rerun")
    expect(success!.permission).toBe("write")

    // Replay the same ticket should fail — ticket was consumed by first execute.
    // Issue a fresh ticket with same argsHash and try to execute twice via internal API.
    const issue = await appHandle.app.request("http://dwa.test/internal/dataworks/write-tickets", {
      method: "POST",
      headers: {
        authorization: `Bearer ${workerToken}`,
        "x-dataworks-worker-id": workerID,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        connectionID: enabledConnectionID,
        tool: "dw_rerun_job",
        argsHash,
        reason: "replay check",
        sessionID: "ses_write_test",
      }),
    })
    expect(issue.status).toBe(201)
    const { ticket } = (await issue.json()) as { ticket: string }

    const first = await appHandle.app.request("http://dwa.test/internal/dataworks/execute", {
      method: "POST",
      headers: {
        authorization: `Bearer ${workerToken}`,
        "x-dataworks-worker-id": workerID,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        ticket,
        connectionID: enabledConnectionID,
        tool: "dw_rerun_job",
        args: runArgs,
        sessionID: "ses_write_test",
      }),
    })
    expect(first.status).toBe(200)

    const second = await appHandle.app.request("http://dwa.test/internal/dataworks/execute", {
      method: "POST",
      headers: {
        authorization: `Bearer ${workerToken}`,
        "x-dataworks-worker-id": workerID,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        ticket,
        connectionID: enabledConnectionID,
        tool: "dw_rerun_job",
        args: runArgs,
        sessionID: "ses_write_test",
      }),
    })
    expect(second.status).toBe(409)

    // session cookie unused in this test but kept for parity with browser flows
    void sessionToken
  })
})
