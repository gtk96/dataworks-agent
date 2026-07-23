import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { randomUUID } from "crypto"
import * as Eff from "effect/Effect"
import { makeDatabase } from "../src/database"
import { makeSecretStore } from "../src/secret/store"
import { createUser } from "../src/auth/session"
import { createDataConnection } from "../src/data-connection/repo"
import { DataWorksServiceImpl, makeService, readModeFromEnv } from "../src/dataworks/service"
import { OpenApiClientCache } from "../src/dataworks/openapi"
import type { DataWorksClient } from "@dataworks-agent/core"

interface FakeSdk extends DataWorksClient {
  __tag: "fake-sdk"
  listProjectsCalls: number
  listJobsCalls: number
  getJobStatusCalls: number
  tableLineageCalls: number
}

function makeFakeSdk(): FakeSdk {
  const fake: FakeSdk = {
    __tag: "fake-sdk",
    listProjectsCalls: 0,
    listJobsCalls: 0,
    getJobStatusCalls: 0,
    tableLineageCalls: 0,
    listProjects: () => {
      fake.listProjectsCalls += 1
      return Eff.succeed({ items: [], total: 0, pageNumber: 1, pageSize: 10 }) as never
    },
    listJobs: () => {
      fake.listJobsCalls += 1
      return Eff.succeed({ items: [], total: 0, pageNumber: 1, pageSize: 10 }) as never
    },
    getJobStatus: () => {
      fake.getJobStatusCalls += 1
      return Eff.succeed({ id: 0, status: "OK" }) as never
    },
    tableLineage: () => {
      fake.tableLineageCalls += 1
      return Eff.succeed({ tableName: "x", upstream: [], downstream: [] }) as never
    },
    listTables: () => {
      return Eff.succeed({ items: [], total: 0, pageNumber: 1, pageSize: 10 }) as never
    },
    describeTable: () => {
      return Eff.succeed({ name: "x", columns: [] }) as never
    },
  }
  return fake
}

describe("readModeFromEnv", () => {
  const originalMode = process.env.DATAWORKS_AGENT_MODE
  afterEach(() => {
    if (originalMode === undefined) delete process.env.DATAWORKS_AGENT_MODE
    else process.env.DATAWORKS_AGENT_MODE = originalMode
  })

  test("defaults to dry-run when env var is missing", () => {
    delete process.env.DATAWORKS_AGENT_MODE
    expect(readModeFromEnv({} as NodeJS.ProcessEnv)).toBe("dry-run")
  })

  test("returns dry-run for unknown values", () => {
    expect(readModeFromEnv({ DATAWORKS_AGENT_MODE: "garbage" } as NodeJS.ProcessEnv)).toBe("dry-run")
  })

  test("returns staging when env says staging", () => {
    expect(readModeFromEnv({ DATAWORKS_AGENT_MODE: "staging" } as NodeJS.ProcessEnv)).toBe("staging")
  })

  test("returns production when env says production", () => {
    expect(readModeFromEnv({ DATAWORKS_AGENT_MODE: "production" } as NodeJS.ProcessEnv)).toBe("production")
  })

  test("is case-insensitive", () => {
    expect(readModeFromEnv({ DATAWORKS_AGENT_MODE: "STAGING" } as NodeJS.ProcessEnv)).toBe("staging")
  })
})

describe("DataWorksServiceImpl routing", () => {
  let tempDir: string
  let db: Awaited<ReturnType<typeof makeDatabase>>
  let secrets: Awaited<ReturnType<typeof makeSecretStore>>
  let connectionID: string

  beforeEach(async () => {
    tempDir = mkdtempSync(join(tmpdir(), "dataworks-service-test-"))
    const dbPath = join(tempDir, `test-${randomUUID()}.sqlite`)
    const migrationsDir = join(import.meta.dir, "..", "migration")
    const secretsRoot = join(tempDir, `secrets-${randomUUID()}`)
    db = await makeDatabase({ dbPath, migrationsDir })
    secrets = await makeSecretStore({ root: secretsRoot, masterKey: new Uint8Array(32).fill(13) })
    const email = `svc-${randomUUID().slice(0, 8)}@example.test`
    await createUser({ email, password: "testpass123", role: "user" }, db)
    const userRow = db.get<{ id: string }>("SELECT id FROM dwa_user WHERE email = ?", [email])
    if (!userRow) throw new Error("user not found after createUser")
    const conn = await createDataConnection(db, secrets, {
      user_id: userRow.id as never,
      name: "fake-staging",
      region: "cn-hangzhou",
      access_key_id: "LTAI_FAKE_NOT_REAL",
      access_key_secret: "sk_fake_not_real_secret",
      write_enabled: false,
    })
    connectionID = conn.id
  })

  afterEach(() => {
    // Best-effort cleanup; ignore if the OS hasn't released handles yet.
    try {
      rmSync(tempDir, { recursive: true, force: true, maxRetries: 3, retryDelay: 50 })
    } catch {}
  })

  test("in dry-run mode, service uses fixture data and does not consult the cache", async () => {
    const cache = new OpenApiClientCache({
      resolveCredentials: async () => {
        throw new Error("dry-run should not call resolveCredentials")
      },
    })
    const service = new DataWorksServiceImpl({ mode: "dry-run", openApiCache: cache })
    const page = await service.listProjects({ region: "cn-hangzhou", pageNumber: 1, pageSize: 10 })
    expect(page.items.length).toBeGreaterThan(0)
    expect(page.items[0]?.name).toBe("dwa_staging")
  })

  test("in staging mode, service dispatches to OpenApiClientCache and does not hit the network here", async () => {
    const fake = makeFakeSdk()
    const cache = new OpenApiClientCache({
      resolveCredentials: async (id) => {
        expect(id).toBe(connectionID)
        return { accessKeyId: "LTAI_FAKE", accessKeySecret: "sk_fake" }
      },
    })
    // Patch the cache by intercepting acquire: a real cache would call the SDK
    // constructor; here we replace the cached entry directly.
    const service = new DataWorksServiceImpl({ mode: "staging", openApiCache: cache, connectionID })
    // Inject the fake client to verify the service consults the cache for every call.
    ;(cache as unknown as { entries: Map<string, { client: DataWorksClient; usedAt: number }> }).entries.set(
      `${connectionID}|cn-hangzhou`,
      { client: fake as unknown as DataWorksClient, usedAt: Date.now() },
    )
    await service.listProjects({ region: "cn-hangzhou", pageNumber: 1, pageSize: 10 })
    expect(fake.listProjectsCalls).toBe(1)
    await service.listJobs({ projectID: 1234, pageNumber: 1, pageSize: 10 })
    expect(fake.listJobsCalls).toBe(1)
    await service.getJobStatus({ projectID: 1234, instanceID: 5678 })
    expect(fake.getJobStatusCalls).toBe(1)
    await service.tableLineage({ projectID: 1234, tableName: "fake_table" })
    expect(fake.tableLineageCalls).toBe(1)
  })

  test("makeService returns dry-run service in test mode without a cache", async () => {
    const service = await makeService({ mode: readModeFromEnv({} as NodeJS.ProcessEnv) })
    // default readModeFromEnv returns "dry-run" when the env is empty
    const page = await service.listProjects({ region: "cn-hangzhou", pageNumber: 1, pageSize: 10 })
    expect(Array.isArray(page.items)).toBe(true)
  })

  test("makeService returns staging service that fails fast without openApiCache", async () => {
    const service = new DataWorksServiceImpl({ mode: "staging" })
    expect(service.listProjects({ region: "cn-hangzhou", pageNumber: 1, pageSize: 10 })).rejects.toThrow(
      /openApiCache is required/,
    )
  })

  test("makeService returns staging service that fails fast without connectionID", async () => {
    const cache = new OpenApiClientCache({ resolveCredentials: async () => null })
    const service = new DataWorksServiceImpl({ mode: "staging", openApiCache: cache })
    expect(service.listProjects({ region: "cn-hangzhou", pageNumber: 1, pageSize: 10 })).rejects.toThrow(
      /connectionID is required/,
    )
  })

  test("OpenApiClientCache reuses entries within the idle window", async () => {
    let calls = 0
    const cache = new OpenApiClientCache({
      resolveCredentials: async () => {
        calls += 1
        return { accessKeyId: "LTAI_FAKE", accessKeySecret: "sk_fake" }
      },
    })
    // We need to stub the SDK construction to avoid the real network call.
    // The simplest path: directly inject a pre-baked client into the cache.
    const fake = makeFakeSdk()
    ;(cache as unknown as { entries: Map<string, { client: DataWorksClient; usedAt: number }> }).entries.set(
      `${connectionID}|cn-hangzhou`,
      { client: fake as unknown as DataWorksClient, usedAt: Date.now() },
    )
    const service = new DataWorksServiceImpl({ mode: "staging", openApiCache: cache, connectionID })
    await service.listProjects({ region: "cn-hangzhou", pageNumber: 1, pageSize: 10 })
    await service.listProjects({ region: "cn-hangzhou", pageNumber: 1, pageSize: 10 })
    expect(calls).toBe(0) // resolveCredentials was never invoked
    expect(fake.listProjectsCalls).toBe(2)
  })
})
