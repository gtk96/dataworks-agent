// Process-local shared OdpsService used by browser HTTP (dataworks-api)
// and worker internal execute (audit-api). One inject hook for tests.

import { makeOdpsService, type OdpsService } from "./service"
import { readModeFromEnv } from "../dataworks/service"

let sharedOdps: OdpsService | null = null

function shouldOdpsDryRun(): boolean {
  if (process.env.DATAWORKS_AGENT_ALLOW_FIXTURES === "1") return true
  if (process.env.DWA_PYODPS_DRY_RUN === "1" || process.env.DWA_PYODPS_DRY_RUN === "true") return true
  return readModeFromEnv() === "dry-run"
}

/** Lazily construct a single process-local OdpsService. */
export function getSharedOdpsService(): OdpsService {
  if (!sharedOdps) {
    sharedOdps = makeOdpsService({ dryRun: shouldOdpsDryRun() })
  }
  return sharedOdps
}

/**
 * Test-only inject hook. Pass `null` to clear so the next call rebuilds
 * from env (or a real supervisor). Used by both dataworks-api and audit-api paths.
 */
export function setOdpsServiceForTests(service: OdpsService | null): void {
  sharedOdps = service
}

export function odpsEndpointForRegion(region: string): string {
  const env = process.env.DATAWORKS_ODPS_ENDPOINT ?? process.env.DATAWORKS_ODPS_STAGING_ENDPOINT
  if (env) return env
  return `https://service.${region}.maxcompute.aliyun.com/api`
}
