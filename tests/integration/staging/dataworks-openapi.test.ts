/**
 * Staging OpenAPI integration — fail closed without secrets; real calls when present.
 *
 * Required:
 *   DATAWORKS_STAGING_AK / DATAWORKS_STAGING_SK
 *   DATAWORKS_STAGING_PROJECT_ID
 * Optional:
 *   DATAWORKS_STAGING_REGION (default cn-hangzhou)
 *   DATAWORKS_STAGING_JOB_INSTANCE_ID (job status probe)
 *   DATAWORKS_ODPS_STAGING_PROJECT (table list project name)
 *
 * Artifacts: artifacts/acceptance/staging/openapi.json (metadata only, never secrets/rows).
 */
import { describe, expect, test } from "bun:test"
import { mkdirSync, writeFileSync } from "node:fs"
import { resolve, join } from "node:path"
import * as Eff from "effect/Effect"

const REQUIRED = [
  "DATAWORKS_STAGING_AK",
  "DATAWORKS_STAGING_SK",
  "DATAWORKS_STAGING_PROJECT_ID",
] as const

const ARTIFACT_DIR = resolve(import.meta.dir, "..", "..", "..", "artifacts", "acceptance", "staging")

describe("dataworks staging openapi", () => {
  test("lists projects (and optional job/tables) or fails closed when secrets missing", async () => {
    const missing = REQUIRED.filter((k) => !process.env[k]?.trim())
    if (missing.length > 0) {
      throw new Error(
        `staging preconditions missing: ${missing.join(", ")} — ` +
          `set DATAWORKS_STAGING_AK/SK, DATAWORKS_STAGING_PROJECT_ID ` +
          `(optional DATAWORKS_STAGING_REGION, DATAWORKS_STAGING_JOB_INSTANCE_ID) ` +
          `and run with DATAWORKS_AGENT_ENV=staging DATAWORKS_AGENT_DRY_RUN=0`,
      )
    }

    const region = process.env.DATAWORKS_STAGING_REGION?.trim() || "cn-hangzhou"
    const projectId = Number(process.env.DATAWORKS_STAGING_PROJECT_ID)
    if (!Number.isInteger(projectId)) {
      throw new Error("DATAWORKS_STAGING_PROJECT_ID must be an integer")
    }

    // Lazy import so fail-closed path never loads the Aliyun SDK without secrets.
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
    const client = await cache.acquire("staging-openapi", region)

    const listStarted = Date.now()
    const projectsPage = await Eff.runPromise(
      client.listProjects({ region, pageNumber: 1, pageSize: 20 }),
    )
    const listDurationMs = Date.now() - listStarted

    expect(Array.isArray(projectsPage.items)).toBe(true)
    // Staging account should see at least the configured project or any project.
    expect(projectsPage.total).toBeGreaterThanOrEqual(0)

    let jobMeta: { durationMs: number; status?: string; id?: number } | null = null
    const jobInstanceId = Number(process.env.DATAWORKS_STAGING_JOB_INSTANCE_ID ?? "")
    if (Number.isInteger(jobInstanceId) && jobInstanceId > 0) {
      const jobStarted = Date.now()
      const status = await Eff.runPromise(
        client.getJobStatus({ projectID: projectId, instanceID: jobInstanceId }),
      )
      jobMeta = {
        durationMs: Date.now() - jobStarted,
        status: status.status,
        id: status.id,
      }
      expect(typeof status.status).toBe("string")
    }

    let tablesMeta: { durationMs: number; itemCount: number; total: number } | null = null
    const projectName =
      process.env.DATAWORKS_ODPS_STAGING_PROJECT?.trim() ||
      projectsPage.items.find((p) => p.id === projectId)?.name ||
      projectsPage.items[0]?.name
    if (projectName) {
      const tStarted = Date.now()
      const tablesPage = await Eff.runPromise(
        client.listTables({
          projectID: projectId,
          pageNumber: 1,
          pageSize: 10,
          projectName,
        }),
      )
      tablesMeta = {
        durationMs: Date.now() - tStarted,
        itemCount: tablesPage.items.length,
        total: tablesPage.total,
      }
      expect(Array.isArray(tablesPage.items)).toBe(true)
    }

    mkdirSync(ARTIFACT_DIR, { recursive: true })
    const evidence = {
      timestamp: new Date().toISOString(),
      region,
      projectId,
      listProjects: {
        durationMs: listDurationMs,
        total: projectsPage.total,
        pageNumber: projectsPage.pageNumber,
        pageSize: projectsPage.pageSize,
        itemCount: projectsPage.items.length,
        // Catalog names only — no secrets.
        sampleProjectNames: projectsPage.items.slice(0, 5).map((p) => p.name),
        sampleProjectIds: projectsPage.items.slice(0, 5).map((p) => p.id),
      },
      jobStatus: jobMeta,
      listTables: tablesMeta,
      totalDurationMs: Date.now() - startedAt,
    }
    writeFileSync(join(ARTIFACT_DIR, "openapi.json"), JSON.stringify(evidence, null, 2))
  })
})
