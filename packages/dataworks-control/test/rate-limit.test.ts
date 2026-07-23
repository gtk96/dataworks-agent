import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { mkdirSync, rmSync } from "fs"
import { join } from "path"
import { randomUUID } from "crypto"
import { makeDatabase } from "../src/database"
import { checkRateLimit, recordRateLimitFailure } from "../src/auth/session"
import type { Database } from "../src/database"

describe("rate limit", () => {
  let db: Database
  let dbPath: string
  const migrationsDir = join(import.meta.dir, "..", "migration")

  beforeEach(async () => {
    const tmpDir = join(import.meta.dir, "..", ".tmp")
    mkdirSync(tmpDir, { recursive: true })
    dbPath = join(tmpDir, `rate-limit-test-${randomUUID()}.sqlite`)
    db = await makeDatabase({ dbPath, migrationsDir })
  })

  afterEach(() => {
    try {
      rmSync(dbPath)
    } catch {}
  })

  test("first request is allowed", async () => {
    const result = await checkRateLimit(db, "192.168.1.1", "user@example.test")
    expect(result.allowed).toBe(true)
    expect(result.retryAfter).toBe(0)
  })

  test("allows up to 5 failures within window", async () => {
    const ip = "192.168.1.2"
    const email = "user@example.test"

    for (let i = 0; i < 5; i++) {
      const result = await checkRateLimit(db, ip, email)
      expect(result.allowed).toBe(true)
      await recordRateLimitFailure(db, ip, email)
    }
  })

  test("blocks after 5 failures", async () => {
    const ip = "192.168.1.3"
    const email = "user@example.test"

    // Record 5 failures
    for (let i = 0; i < 5; i++) {
      await recordRateLimitFailure(db, ip, email)
    }

    const result = await checkRateLimit(db, ip, email)
    expect(result.allowed).toBe(false)
    expect(result.retryAfter).toBeGreaterThan(0)
  })

  test("blocks after 5 failures then clears on next check if window expired", async () => {
    const ip = "192.168.1.4"
    const email = "user@example.test"

    // Record 5 failures
    for (let i = 0; i < 5; i++) {
      await recordRateLimitFailure(db, ip, email)
    }

    // Simulate window expiration by directly manipulating the DB
    const WINDOW_MS = 15 * 60 * 1000
    const expiredTime = Date.now() - WINDOW_MS - 1000
    db.run(
      "UPDATE dwa_rate_limit SET first_failure = ? WHERE ip_address = ? AND email = ?",
      [expiredTime, ip, email],
    )

    const result = await checkRateLimit(db, ip, email)
    expect(result.allowed).toBe(true)
  })
})

describe("password hashing", () => {
  test("hashes and verifies password", async () => {
    const { hashPassword, verifyPassword } = await import("../src/auth/password")

    const hash = await hashPassword("my-secret-password")
    expect(hash).not.toBe("my-secret-password")
    expect(await verifyPassword(hash, "my-secret-password")).toBe(true)
    expect(await verifyPassword(hash, "wrong-password")).toBe(false)
  })
})

describe("token hashing", () => {
  test("sha256 hash is deterministic", () => {
    const { createHash } = require("crypto")

    const token = "test-token-abc123"
    const hash1 = createHash("sha256").update(token).digest("hex")
    const hash2 = createHash("sha256").update(token).digest("hex")
    expect(hash1).toBe(hash2)
  })

  test("different tokens produce different hashes", () => {
    const { createHash } = require("crypto")

    const hash1 = createHash("sha256").update("token-a").digest("hex")
    const hash2 = createHash("sha256").update("token-b").digest("hex")
    expect(hash1).not.toBe(hash2)
  })
})
