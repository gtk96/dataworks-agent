import { describe, expect, test } from "bun:test"
import { DataWorksConfig } from "../src/config"

describe("DataWorksConfig", () => {
  test("defaults to safe local dry-run", () => {
    expect(DataWorksConfig.load({})).toEqual({
      dryRun: true,
      host: "127.0.0.1",
      port: 8084,
      publicRegistration: false,
      workerIdleSeconds: 900,
    })
  })

  test("rejects disabling dry-run without an environment name", () => {
    expect(() => DataWorksConfig.load({ DATAWORKS_AGENT_DRY_RUN: "0" })).toThrow("DATAWORKS_AGENT_ENV")
  })
})
