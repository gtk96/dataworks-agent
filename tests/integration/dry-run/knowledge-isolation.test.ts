import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { randomBytes } from "crypto"
import { mkdirSync, rmSync } from "fs"
import { join } from "path"
import { login } from "../../../packages/dataworks-control/src/auth/session"
import { makeApp, createUser, type AppHandle } from "../../../packages/dataworks-control/src/http/server"
import { generateMasterKey } from "../../../packages/dataworks-control/src/secret/store"
import { signWorkerToken } from "../../../packages/dataworks-control/src/worker/token"

const tmpDir = join(import.meta.dir, ".knowledge-isolation-test-tmp")
const workerTokenSecret = randomBytes(32)

let appHandle: AppHandle
let tokenA: string
let tokenB: string
let userA: string
let userB: string

beforeAll(async () => {
  rmSync(tmpDir, { recursive: true, force: true })
  mkdirSync(tmpDir, { recursive: true })
  appHandle = await makeApp({
    dbPath: join(tmpDir, "test.db"),
    secretsRoot: join(tmpDir, ".secrets"),
    appDataRoot: join(tmpDir, "app-data"),
    publicOrigin: "http://dwa.test",
    masterKey: generateMasterKey(),
    workerTokenSecret,
    startServer: false,
  })

  const emailA = `a-${randomBytes(3).toString("hex")}@example.com`
  const emailB = `b-${randomBytes(3).toString("hex")}@example.com`
  await createUser({ email: emailA, password: "testpass123", role: "user" }, appHandle.db)
  await createUser({ email: emailB, password: "testpass123", role: "user" }, appHandle.db)
  userA = appHandle.db.get<{ id: string }>("SELECT id FROM dwa_user WHERE email = ?", [emailA])!.id
  userB = appHandle.db.get<{ id: string }>("SELECT id FROM dwa_user WHERE email = ?", [emailB])!.id
  const sa = await login(appHandle.db, { email: emailA, password: "testpass123" })
  const sb = await login(appHandle.db, { email: emailB, password: "testpass123" })
  if (!sa || !sb) throw new Error("login failed")
  tokenA = sa.token
  tokenB = sb.token
})

afterAll(() => {
  if (appHandle?.server) appHandle.server.stop()
  appHandle?.db.close()
  try {
    rmSync(tmpDir, { recursive: true, force: true })
  } catch {
    // Windows lock
  }
})

function headers(token: string) {
  return {
    cookie: `dwa_session=${encodeURIComponent(token)}`,
    origin: "http://dwa.test",
  }
}

function request(path: string, init: RequestInit = {}) {
  return appHandle.app.request(`http://dwa.test${path}`, init)
}

async function createKb(token: string, name: string) {
  const res = await request("/api/knowledge/bases", {
    method: "POST",
    headers: { ...headers(token), "content-type": "application/json" },
    body: JSON.stringify({ name, egressPolicy: "local_only" }),
  })
  expect(res.status).toBe(201)
  return (await res.json()) as { id: string }
}

async function uploadAndReady(token: string, kbId: string, filename: string, text: string) {
  const form = new FormData()
  form.append("file", new Blob([text], { type: "text/markdown" }), filename)
  const res = await request(`/api/knowledge/bases/${kbId}/documents`, {
    method: "POST",
    headers: headers(token),
    body: form,
  })
  expect(res.status).toBe(201)
  const doc = (await res.json()) as { id: string }
  const start = Date.now()
  while (Date.now() - start < 15_000) {
    const poll = await request(`/api/knowledge/bases/${kbId}/documents/${doc.id}`, {
      headers: headers(token),
    })
    const body = (await poll.json()) as { status: string }
    if (body.status === "ready") return doc
    if (body.status === "failed" || body.status === "error") throw new Error(JSON.stringify(body))
    await Bun.sleep(50)
  }
  throw new Error("timeout waiting for ready")
}

describe("knowledge isolation dry-run", () => {
  test("user B search returns no chunks from user A", async () => {
    const kbA = await createKb(tokenA, "a-kb")
    const kbB = await createKb(tokenB, "b-kb")

    await uploadAndReady(tokenA, kbA.id, "secret-a.md", "# A\n\nUSER_A_SECRET_MARKER private cargo.\n")
    await uploadAndReady(tokenB, kbB.id, "public-b.md", "# B\n\nUSER_B_OWN_MARKER public notes.\n")

    const searchBOnOwn = await request("/api/knowledge/search", {
      method: "POST",
      headers: { ...headers(tokenB), "content-type": "application/json" },
      body: JSON.stringify({ knowledgeBaseId: kbB.id, query: "USER_B_OWN_MARKER", topK: 5 }),
    })
    expect(searchBOnOwn.status).toBe(200)
    const own = (await searchBOnOwn.json()) as { results: Array<{ text: string; userId?: string }> }
    expect(own.results.some((r) => r.text.includes("USER_B_OWN_MARKER"))).toBe(true)
    expect(own.results.every((r) => !r.text.includes("USER_A_SECRET_MARKER"))).toBe(true)

    const searchBForA = await request("/api/knowledge/search", {
      method: "POST",
      headers: { ...headers(tokenB), "content-type": "application/json" },
      body: JSON.stringify({ knowledgeBaseId: kbA.id, query: "USER_A_SECRET_MARKER", topK: 10 }),
    })
    // Must not leak A's KB: 404 or empty results, never the secret
    if (searchBForA.status === 200) {
      const leaked = (await searchBForA.json()) as { results: Array<{ text: string }> }
      expect(leaked.results.every((r) => !r.text.includes("USER_A_SECRET_MARKER"))).toBe(true)
      expect(leaked.results.length).toBe(0)
    } else {
      expect([400, 403, 404]).toContain(searchBForA.status)
    }

    const searchA = await request("/api/knowledge/search", {
      method: "POST",
      headers: { ...headers(tokenA), "content-type": "application/json" },
      body: JSON.stringify({ knowledgeBaseId: kbA.id, query: "USER_A_SECRET_MARKER", topK: 5 }),
    })
    expect(searchA.status).toBe(200)
    const aBody = (await searchA.json()) as { results: Array<{ text: string }> }
    expect(aBody.results[0]?.text).toContain("USER_A_SECRET_MARKER")

    // Cross-user list isolation
    const listB = await request("/api/knowledge/bases", { headers: headers(tokenB) })
    expect(listB.status).toBe(200)
    const basesB = (await listB.json()) as { bases: Array<{ id: string }> }
    expect(basesB.bases.every((b) => b.id !== kbA.id)).toBe(true)
    expect(basesB.bases.some((b) => b.id === kbB.id)).toBe(true)

    // Worker-authenticated internal search uses token userID (tenant), never body spoofing
    const workerA = signWorkerToken(workerTokenSecret, {
      userID: userA,
      workerID: "worker-a-test",
      expires: Date.now() + 60_000,
    })
    const internalA = await request("/internal/knowledge/search", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${workerA}`,
        "x-dataworks-worker-id": "worker-a-test",
      },
      body: JSON.stringify({ knowledgeBaseId: kbA.id, query: "USER_A_SECRET_MARKER", topK: 5 }),
    })
    expect(internalA.status).toBe(200)
    const internalBody = (await internalA.json()) as { results: Array<{ text: string }> }
    expect(internalBody.results.some((r) => r.text.includes("USER_A_SECRET_MARKER"))).toBe(true)

    // Worker B cannot read A's chunks even if it knows kbA.id
    const workerB = signWorkerToken(workerTokenSecret, {
      userID: userB,
      workerID: "worker-b-test",
      expires: Date.now() + 60_000,
    })
    const internalB = await request("/internal/knowledge/search", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${workerB}`,
        "x-dataworks-worker-id": "worker-b-test",
      },
      body: JSON.stringify({ knowledgeBaseId: kbA.id, query: "USER_A_SECRET_MARKER", topK: 10 }),
    })
    if (internalB.status === 200) {
      const body = (await internalB.json()) as { results: Array<{ text: string }> }
      expect(body.results.every((r) => !r.text.includes("USER_A_SECRET_MARKER"))).toBe(true)
      expect(body.results.length).toBe(0)
    } else {
      expect([400, 403, 404]).toContain(internalB.status)
    }

    // Cookie on internal route is rejected
    const cookieInternal = await request("/internal/knowledge/search", {
      method: "POST",
      headers: {
        ...headers(tokenA),
        "content-type": "application/json",
        authorization: `Bearer ${workerA}`,
        "x-dataworks-worker-id": "worker-a-test",
      },
      body: JSON.stringify({ knowledgeBaseId: kbA.id, query: "USER_A_SECRET_MARKER" }),
    })
    expect(cookieInternal.status).toBe(403)
  })
})
