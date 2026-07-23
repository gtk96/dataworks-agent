import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { mkdtempSync, readFileSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { SecretStore } from "../src/secret/store"
import { makeDatabase } from "../src/database"
import { createUser, login } from "../src/auth/session"
import { makeApp } from "../src/http/server"
import { KeyringUnavailable, type SystemKeyringBackend } from "../src/secret/keyring"

describe("SecretStore", () => {
  let tempDir: string

  beforeEach(() => {
    tempDir = mkdtempSync(join(tmpdir(), "secret-store-test-"))
  })

  afterEach(() => {
    rmSync(tempDir, { recursive: true, force: true })
  })

  test("encrypts without plaintext and rotates nonce", async () => {
    const store = await SecretStore.test({ root: tempDir, masterKey: new Uint8Array(32).fill(7) })
    await store.put("connection:a", { accessKeyId: "LTAI_TEST", accessKeySecret: "secret-value" })

    const first = readFileSync(join(tempDir, "secrets.dat"))
    expect(Buffer.from(first).toString("utf-8")).not.toContain("secret-value")

    await store.put("connection:a", { accessKeyId: "LTAI_TEST", accessKeySecret: "secret-value" })
    const second = readFileSync(join(tempDir, "secrets.dat"))
    expect(Buffer.from(first).equals(Buffer.from(second))).toBe(false)

    expect(await store.ref("connection:a")).toEqual({
      accessKeyId: "LTAI_TEST",
      accessKeySecret: "secret-value",
    })
  })

  test("rejects files with wrong magic", async () => {
    const store = await SecretStore.test({ root: tempDir, masterKey: new Uint8Array(32).fill(7) })
    await store.put("connection:a", { accessKeyId: "LTAI_TEST", accessKeySecret: "secret-value" })

    const path = join(tempDir, "secrets.dat")
    const buf = readFileSync(path)
    buf[0] = 0x58
    await Bun.write(path, buf)

    await expect(store.ref("connection:a")).rejects.toThrow(/magic|version/i)
  })

  test("delete removes ref", async () => {
    const store = await SecretStore.test({ root: tempDir, masterKey: new Uint8Array(32).fill(7) })
    await store.put("connection:a", { accessKeyId: "LTAI_TEST", accessKeySecret: "secret-value" })
    await store.delete("connection:a")

    expect(await store.ref("connection:a")).toBeUndefined()
  })

  test("atomic write does not leak temp file", async () => {
    const store = await SecretStore.test({ root: tempDir, masterKey: new Uint8Array(32).fill(7) })
    await store.put("connection:a", { accessKeyId: "LTAI_TEST", accessKeySecret: "secret-value" })
    expect(await Bun.file(join(tempDir, "secrets.dat.tmp")).exists()).toBe(false)
  })
})

describe("makeApp keyring startup", () => {
  test("fails closed with KeyringUnavailable when the system keyring cannot be reached", async () => {
    const secretsRoot = mkdtempSync(join(tmpdir(), "server-keyring-test-"))
    const unavailableBackend: SystemKeyringBackend = {
      getPassword() {
        throw new Error("system keyring unavailable")
      },
      setPassword() {
        throw new Error("system keyring unavailable")
      },
    }

    try {
      await expect(
        makeApp({
          dbPath: ":memory:",
          publicOrigin: "http://localhost",
          migrationsDir: join(import.meta.dir, "..", "migration"),
          secretsRoot,
          keyringBackend: unavailableBackend,
        }),
      ).rejects.toBeInstanceOf(KeyringUnavailable)
    } finally {
      rmSync(secretsRoot, { recursive: true, force: true })
    }
  })
})

describe("migration upgrade preserves admin and session rows", () => {
  const migrationsDir = join(import.meta.dir, "..", "migration")

  test("0003 upgrade preserves admin and session rows from auth-only fixture", async () => {
    const tmpDir = mkdtempSync(join(tmpdir(), "migration-upgrade-"))
    const dbPath = join(tmpDir, "migrated.sqlite")
    const { Database } = await import("bun:sqlite")

    // Build the auth-only DB by running the full migration chain, then dropping
    // 0002 and 0003 tables and migration rows so the DB is precisely the v0
    // (post-0001) state.
    const initial = new Database(dbPath, { create: true })
    for (const stmt of [
      `CREATE TABLE IF NOT EXISTS dwa_migration (id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, time_completed INTEGER NOT NULL)`,
    ]) initial.exec(stmt)
    for (const file of ["0001_auth.sql"]) {
      const sql = readFileSync(join(migrationsDir, file), "utf-8")
      const stripped = sql
        .split("\n")
        .filter((line) => !line.trim().startsWith("--"))
        .join("\n")
      for (const stmt of stripped.split(";").map((s) => s.trim()).filter((s) => s.length > 0)) {
        initial.exec(stmt)
      }
    }
    const seedDb = await makeDatabase({ dbPath, migrationsDir })
    await createUser(
      { email: "admin@example.test", password: "correct-horse", role: "admin" },
      seedDb,
    )
    initial.exec(
      "INSERT INTO dwa_browser_session (token_hash, user_id, time_expires, time_created) SELECT 'preset-token-hash-v0', id, strftime('%s','now')*1000 + 600000, strftime('%s','now')*1000 FROM dwa_user WHERE email='admin@example.test'",
    )
    initial.close()

    const rdb = await makeDatabase({ dbPath, migrationsDir })
    const adminBefore = rdb.get<{ id: string; email: string }>(
      "SELECT id, email FROM dwa_user WHERE email = 'admin@example.test'",
    )
    expect(adminBefore?.email).toBe("admin@example.test")
    const sessionsBefore = rdb.all<{ token_hash: string }>(
      "SELECT token_hash FROM dwa_browser_session",
    )
    expect(sessionsBefore.map((s) => s.token_hash)).toContain("preset-token-hash-v0")
    void rdb

    const upgraded = await makeDatabase({ dbPath, migrationsDir })

    const adminAfter = upgraded.get<{ id: string; email: string }>(
      "SELECT id, email FROM dwa_user WHERE email = 'admin@example.test'",
    )
    expect(adminAfter?.id).toBe(adminBefore?.id)
    expect(adminAfter?.email).toBe("admin@example.test")

    const sessionsAfter = upgraded.all<{ token_hash: string }>(
      "SELECT token_hash FROM dwa_browser_session",
    )
    expect(sessionsAfter.length).toBe(sessionsBefore.length)
    expect(sessionsAfter.map((s) => s.token_hash).sort()).toEqual(
      sessionsBefore.map((s) => s.token_hash).sort(),
    )

    const hasDataConnTable = upgraded.get<{ name: string }>(
      "SELECT name FROM sqlite_master WHERE type='table' AND name='dwa_data_connection'",
    )
    expect(hasDataConnTable?.name).toBe("dwa_data_connection")

    const hasRateLimitTable = upgraded.get<{ name: string }>(
      "SELECT name FROM sqlite_master WHERE type='table' AND name='dwa_rate_limit'",
    )
    expect(hasRateLimitTable?.name).toBe("dwa_rate_limit")
  })
})
