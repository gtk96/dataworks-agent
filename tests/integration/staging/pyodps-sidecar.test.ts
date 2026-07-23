import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { resolve } from "node:path"
import { mkdirSync, writeFileSync } from "node:fs"
import { join } from "node:path"

import { OdpsSidecarSupervisor } from "../../../packages/dataworks-control/src/odps/sidecar"
import {
  makeOdpsService,
  OdpsPolicyError,
  OdpsSidecarError,
} from "../../../packages/dataworks-control/src/odps/service"

const SIDECAR_PATH = resolve(
  import.meta.dir,
  "..",
  "..",
  "..",
  "sidecars",
  "pyodps",
)
const FIXTURE_PATH = resolve(
  import.meta.dir,
  "..",
  "..",
  "..",
  "tests",
  "fixtures",
  "odps",
  "query.json",
)
const ARTIFACT_DIR = resolve(
  import.meta.dir,
  "..",
  "..",
  "..",
  "artifacts",
  "acceptance",
  "staging",
)

const REQUIRED = [
  "DATAWORKS_ODPS_STAGING_AK",
  "DATAWORKS_ODPS_STAGING_SK",
  "DATAWORKS_ODPS_STAGING_ENDPOINT",
  "DATAWORKS_ODPS_STAGING_PROJECT",
] as const

async function readFixture(): Promise<{
  table: { name: string; project: string; columns: ReadonlyArray<{ name: string; type: string }> }
  queries: { smoke: string; bounded: string }
}> {
  return (await Bun.file(FIXTURE_PATH).json()) as {
    table: { name: string; project: string; columns: ReadonlyArray<{ name: string; type: string }> }
    queries: { smoke: string; bounded: string }
  }
}

describe("pyodps sidecar staging integration", () => {
  test("exits clearly when staging credentials are missing", async () => {
    const missing = REQUIRED.filter((k) => !process.env[k])
    if (missing.length > 0) {
      throw new Error(
        `staging preconditions missing: ${missing.join(", ")} — ` +
          `set the listed env vars (DATAWORKS_ODPS_STAGING_AK, DATAWORKS_ODPS_STAGING_SK, ` +
          `DATAWORKS_ODPS_STAGING_ENDPOINT, DATAWORKS_ODPS_STAGING_PROJECT) ` +
          `and run with DATAWORKS_AGENT_ENV=staging DATAWORKS_AGENT_DRY_RUN=0`,
      )
    }
    // Credentials present — record evidence.
    mkdirSync(ARTIFACT_DIR, { recursive: true })
    const fixture = await readFixture()
    const supervisor = new OdpsSidecarSupervisor({
      projectPath: SIDECAR_PATH,
      dryRun: false,
    })
    const service = makeOdpsService({
      supervisor,
      defaultTimeoutMs: 60_000,
    })

    let smokeResult: { columns: ReadonlyArray<{ name: string; type: string }>; rows: ReadonlyArray<ReadonlyArray<unknown>>; truncated: boolean; instance_id: string | null; duration_ms: number } | null = null
    let boundedResult: typeof smokeResult = null
    let caughtPolicyError: { code: string; token?: string } | null = null
    try {
      await supervisor.start()
      smokeResult = await service.query({
        credential: {
          accessKeyId: process.env.DATAWORKS_ODPS_STAGING_AK!,
          accessKeySecret: process.env.DATAWORKS_ODPS_STAGING_SK!,
        },
        endpoint: process.env.DATAWORKS_ODPS_STAGING_ENDPOINT!,
        project: process.env.DATAWORKS_ODPS_STAGING_PROJECT!,
        sql: fixture.queries.smoke,
        maxRows: 1,
        maxBytes: 1024,
      })
      boundedResult = await service.query({
        credential: {
          accessKeyId: process.env.DATAWORKS_ODPS_STAGING_AK!,
          accessKeySecret: process.env.DATAWORKS_ODPS_STAGING_SK!,
        },
        endpoint: process.env.DATAWORKS_ODPS_STAGING_ENDPOINT!,
        project: process.env.DATAWORKS_ODPS_STAGING_PROJECT!,
        sql: fixture.queries.bounded,
        maxRows: fixture.table.columns.length === 0 ? 25 : 25,
        maxBytes: 4096,
      })
      // Sanity-check: ODPS policy must reject DROP / INSERT statements.
      try {
        await service.query({
          credential: { accessKeyId: "x", accessKeySecret: "y" },
          endpoint: "x",
          project: "x",
          sql: "DROP TABLE foo",
        })
      } catch (err) {
        if (err instanceof OdpsPolicyError) {
          caughtPolicyError = { code: err.code, ...(err.token !== undefined ? { token: err.token } : {}) }
        } else if (err instanceof OdpsSidecarError) {
          // Sidecar can never be reached with bad creds; not a policy error.
          caughtPolicyError = { code: err.code }
        }
      }
    } finally {
      await supervisor.stop()
    }

    expect(smokeResult).not.toBeNull()
    expect(boundedResult).not.toBeNull()
    expect(caughtPolicyError).not.toBeNull()
    expect(caughtPolicyError!.code).toBe("BANNED_TOKEN")

    // Record columns + row count + instance id + duration — never row contents.
    const evidence = {
      fixture: { table: fixture.table.name, project: fixture.table.project },
      smoke: smokeResult
        ? {
            columns: smokeResult.columns,
            row_count: smokeResult.rows.length,
            instance_id: smokeResult.instance_id,
            duration_ms: smokeResult.duration_ms,
            truncated: smokeResult.truncated,
          }
        : null,
      bounded: boundedResult
        ? {
            columns: boundedResult.columns,
            row_count: boundedResult.rows.length,
            instance_id: boundedResult.instance_id,
            duration_ms: boundedResult.duration_ms,
            truncated: boundedResult.truncated,
          }
        : null,
      policy_gate: caughtPolicyError,
    }
    writeFileSync(join(ARTIFACT_DIR, "pyodps-sidecar.json"), JSON.stringify(evidence, null, 2))
  })
})

void beforeAll
void afterAll
