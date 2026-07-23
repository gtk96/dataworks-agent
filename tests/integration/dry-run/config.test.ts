import { describe, expect, test } from "bun:test"
import { DataWorksConfig } from "../../../packages/dataworks-core/src/config"

describe("dataworks-dry-run integration", () => {
  test("loads sanitized dry-run config without cloud credentials", () => {
    const config = DataWorksConfig.load({ DATAWORKS_AGENT_DRY_RUN: "1" })
    expect(config.dryRun).toBe(true)
    expect(config.host).toBe("127.0.0.1")
    expect(config.port).toBe(8084)
  })

  test("fails fast when dry-run disabled without environment", () => {
    expect(() => DataWorksConfig.load({ DATAWORKS_AGENT_DRY_RUN: "0" })).toThrow("DATAWORKS_AGENT_ENV")
  })
})
