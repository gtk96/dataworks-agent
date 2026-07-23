import { describe, expect, test } from "bun:test"
import { mkdirSync, writeFileSync } from "node:fs"
import { resolve, join } from "node:path"

/**
 * Staging Step 1 harness for Explorer tables + SQL.
 *
 * Fail-closed: missing secrets throw with a clear Error listing the env vars.
 * When secrets are present, list tables (OpenAPI meta search) and run SELECT 1
 * via OdpsService in real mode, writing **masked** metadata only to
 * artifacts/staging/tables-sql.json (no AK/SK, no business rows).
 *
 * Required env (aligned with docs/operations/staging.md):
 *   DATAWORKS_STAGING_AK / DATAWORKS_STAGING_SK
 *   DATAWORKS_STAGING_REGION (optional, default cn-hangzhou)
 *   DATAWORKS_STAGING_PROJECT_ID
 *   DATAWORKS_ODPS_STAGING_AK / DATAWORKS_ODPS_STAGING_SK
 *   DATAWORKS_ODPS_STAGING_ENDPOINT
 *   DATAWORKS_ODPS_STAGING_PROJECT
 */

const REQUIRED = [
  "DATAWORKS_STAGING_AK",
  "DATAWORKS_STAGING_SK",
  "DATAWORKS_STAGING_PROJECT_ID",
  "DATAWORKS_ODPS_STAGING_AK",
  "DATAWORKS_ODPS_STAGING_SK",
  "DATAWORKS_ODPS_STAGING_ENDPOINT",
  "DATAWORKS_ODPS_STAGING_PROJECT",
] as const

const ARTIFACT_DIR = resolve(
  import.meta.dir,
  "..",
  "..",
  "..",
  "artifacts",
  "acceptance",
  "staging",
)

describe("dataworks staging tables + sql (step 1)", () => {
  test("lists tables and runs SELECT 1, or fails closed when secrets missing", async () => {
    const missing = REQUIRED.filter((k) => !process.env[k]?.trim())
    if (missing.length > 0) {
      throw new Error(
        `staging preconditions missing: ${missing.join(", ")} — ` +
          `set DATAWORKS_STAGING_AK/SK, DATAWORKS_STAGING_PROJECT_ID, ` +
          `DATAWORKS_ODPS_STAGING_AK/SK/ENDPOINT/PROJECT ` +
          `(optional DATAWORKS_STAGING_REGION) and run with ` +
          `DATAWORKS_AGENT_MODE=staging DATAWORKS_AGENT_DRY_RUN=0`,
      )
    }

    const region = process.env.DATAWORKS_STAGING_REGION?.trim() || "cn-hangzhou"
    const projectId = Number(process.env.DATAWORKS_STAGING_PROJECT_ID)
    const projectName = process.env.DATAWORKS_ODPS_STAGING_PROJECT!.trim()
    if (!Number.isInteger(projectId)) {
      throw new Error("DATAWORKS_STAGING_PROJECT_ID must be an integer")
    }
    if (!projectName) {
      throw new Error("DATAWORKS_ODPS_STAGING_PROJECT must be a non-empty MaxCompute project name")
    }

    // Lazy imports so the fail-closed path does not load OpenAPI SDK when secrets absent.
    const { OpenApiDataWorksClient } = await import(
      "../../../packages/dataworks-control/src/dataworks/openapi"
    )
    const { makeOdpsService } = await import("../../../packages/dataworks-control/src/odps/service")
    // OpenApiDataWorksClient needs an SDK instance — use the public cache path via a thin fake.
    // Build via OpenApiClientCache with inline credentials (not written to artifacts).
    const { OpenApiClientCache } = await import(
      "../../../packages/dataworks-control/src/dataworks/openapi"
    )

    const startedAt = Date.now()
    const cache = new OpenApiClientCache({
      resolveCredentials: async () => ({
        accessKeyId: process.env.DATAWORKS_STAGING_AK!,
        accessKeySecret: process.env.DATAWORKS_STAGING_SK!,
      }),
    })
    const client = await cache.acquire("staging-tables-sql", region)
    void OpenApiDataWorksClient

    const listStarted = Date.now()
    // Prefer empty/project-name keyword over blind "*"; OpenAPI still requires keyword field.
    const tablesPage = await import("effect").then(({ Effect }) =>
      Effect.runPromise(
        client.listTables({
          projectID: projectId,
          pageNumber: 1,
          pageSize: 20,
          projectName,
          // omit user keyword → openapi uses projectName (not "*")
        }),
      ),
    )
    const listDurationMs = Date.now() - listStarted

    const odps = makeOdpsService({ dryRun: false, defaultTimeoutMs: 60_000 })
    const sqlStarted = Date.now()
    let sqlMeta: {
      instanceId: string | null
      durationMs: number
      columnCount: number
      rowCount: number
      truncated: boolean
    }
    try {
      const result = await odps.query({
        credential: {
          accessKeyId: process.env.DATAWORKS_ODPS_STAGING_AK!,
          accessKeySecret: process.env.DATAWORKS_ODPS_STAGING_SK!,
        },
        endpoint: process.env.DATAWORKS_ODPS_STAGING_ENDPOINT!,
        project: projectName,
        sql: "SELECT 1",
        maxRows: 1,
        maxBytes: 1024,
        timeoutMs: 60_000,
      })
      sqlMeta = {
        instanceId: result.instance_id,
        durationMs: result.duration_ms,
        columnCount: result.columns.length,
        rowCount: result.rows.length,
        truncated: result.truncated,
      }
    } finally {
      await odps.stop()
    }
    const sqlWallMs = Date.now() - sqlStarted

    expect(tablesPage.items).toBeDefined()
    expect(Array.isArray(tablesPage.items)).toBe(true)
    expect(sqlMeta.rowCount).toBeGreaterThanOrEqual(1)
    expect(sqlMeta.columnCount).toBeGreaterThanOrEqual(1)

    mkdirSync(ARTIFACT_DIR, { recursive: true })
    // Masked metadata only — never AK/SK or business rows.
    const evidence = {
      timestamp: new Date().toISOString(),
      region,
      projectId,
      projectName,
      listTables: {
        durationMs: listDurationMs,
        total: tablesPage.total,
        pageNumber: tablesPage.pageNumber,
        pageSize: tablesPage.pageSize,
        itemCount: tablesPage.items.length,
        // table names are catalog metadata (acceptable); omit row samples
        sampleTableNames: tablesPage.items.slice(0, 5).map((t) => t.name),
        sampleTableGuids: tablesPage.items
          .slice(0, 5)
          .map((t) => t.tableGuid)
          .filter(Boolean),
      },
      select1: {
        durationMs: sqlMeta.durationMs,
        wallMs: sqlWallMs,
        instanceId: sqlMeta.instanceId,
        columnCount: sqlMeta.columnCount,
        rowCount: sqlMeta.rowCount,
        truncated: sqlMeta.truncated,
      },
      totalDurationMs: Date.now() - startedAt,
    }
    writeFileSync(join(ARTIFACT_DIR, "tables-sql.json"), JSON.stringify(evidence, null, 2))
  })
})
