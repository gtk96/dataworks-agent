import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { resolve } from "node:path"

import { OdpsSidecarSupervisor } from "../../../packages/dataworks-control/src/odps/sidecar"
import { evaluateSql } from "../../../packages/dataworks-control/src/odps/sql-policy"

// Locate the sidecar project relative to this test file.
const SIDECAR_PATH = resolve(import.meta.dir, "..", "..", "..", "sidecars", "pyodps")

describe("pyodps sidecar dry-run integration", () => {
  test("sql-policy accepts a read-only SELECT and rejects DROP", () => {
    expect(evaluateSql("SELECT 1").ok).toBe(true)
    expect(evaluateSql("select id from tbl where id = 1").ok).toBe(true)
    expect(evaluateSql("DROP TABLE foo").ok).toBe(false)
    expect(evaluateSql("INSERT INTO foo VALUES (1)").ok).toBe(false)
    expect(evaluateSql("WITH t AS (SELECT 1) SELECT * FROM t").ok).toBe(true)
    expect(evaluateSql("WITH t AS (SELECT 1) INSERT INTO t SELECT * FROM t").ok).toBe(false)
    expect(evaluateSql("SELECT 1; SELECT 2").ok).toBe(false)
    expect(evaluateSql("SELECT 'a;b;c'").ok).toBe(true)
    expect(evaluateSql("SELECT 1 /* c; DROP TABLE foo; */").ok).toBe(true)
  })

  test("real uv-spawned sidecar answers health and dry-run SELECT 1", async () => {
    if (process.env.DATAWORKS_AGENT_DRY_RUN !== "1") {
      // Without the gate we already exercise the policy above; skip the
      // network/exec path.
      return
    }
    const supervisor = new OdpsSidecarSupervisor({
      projectPath: SIDECAR_PATH,
      dryRun: true,
    })
    try {
      await supervisor.start()
      const health = await supervisor.health()
      expect(health.ok).toBe(true)
      expect(typeof health.version).toBe("string")
      const result = await supervisor.query({
        endpoint: "dry-run://",
        project: "dwa_synthetic",
        sql: "SELECT 1",
        timeout_ms: 5_000,
        max_rows: 10,
        max_bytes: 1_024,
        access_key_id: "FAKE_AK",
        access_key_secret: "FAKE_SK",
      })
      expect(result.columns).toEqual([{ name: "_c0", type: "BIGINT" }])
      expect(result.rows).toEqual([[1]])
      expect(result.truncated).toBe(false)
      expect(result.instance_id).toBe("dry-run")
    } finally {
      await supervisor.stop()
    }
  }, { timeout: 30_000 })

  test("kill + restart: supervisor respawns the child within backoff", async () => {
    if (process.env.DATAWORKS_AGENT_DRY_RUN !== "1") return
    const supervisor = new OdpsSidecarSupervisor({
      projectPath: SIDECAR_PATH,
      dryRun: true,
    })
    try {
      await supervisor.start()
      const originalPid = supervisor.pid
      expect(originalPid).toBeGreaterThan(0)
      supervisor.killChild()
      // Backoff schedule is 1s / 2s / 5s. Allow up to 6.5s.
      const deadline = Date.now() + 6500
      let latestPid = originalPid
      while (Date.now() < deadline) {
        if (supervisor.pid !== originalPid && supervisor.pid !== 0) {
          latestPid = supervisor.pid
          break
        }
        await new Promise((r) => setTimeout(r, 100))
      }
      expect(latestPid).not.toBe(originalPid)
      const health = await supervisor.health()
      expect(health.ok).toBe(true)
    } finally {
      await supervisor.stop()
    }
  }, { timeout: 30_000 })
})

void beforeAll
void afterAll
