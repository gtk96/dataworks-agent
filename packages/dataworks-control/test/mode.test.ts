import { describe, expect, test } from "bun:test"
import {
  assertProductDryRunAllowed,
  DryRunForbiddenError,
  readProductMode,
} from "../src/mode"

describe("product mode", () => {
  test("assertProductDryRunAllowed throws DryRunForbiddenError when DATAWORKS_AGENT_DRY_RUN is truthy", () => {
    for (const value of ["1", "true", "TRUE", "yes", "Yes"]) {
      expect(() => assertProductDryRunAllowed({ DATAWORKS_AGENT_DRY_RUN: value })).toThrow(
        DryRunForbiddenError,
      )
    }
  })

  test("assertProductDryRunAllowed allows unset, 0, false, and empty dry-run", () => {
    expect(() => assertProductDryRunAllowed({})).not.toThrow()
    expect(() => assertProductDryRunAllowed({ DATAWORKS_AGENT_DRY_RUN: "0" })).not.toThrow()
    expect(() => assertProductDryRunAllowed({ DATAWORKS_AGENT_DRY_RUN: "false" })).not.toThrow()
    expect(() => assertProductDryRunAllowed({ DATAWORKS_AGENT_DRY_RUN: "" })).not.toThrow()
  })

  test("readProductMode refuses dry-run before resolving mode", () => {
    expect(() => readProductMode({ DATAWORKS_AGENT_DRY_RUN: "1" })).toThrow(DryRunForbiddenError)
    expect(() =>
      readProductMode({ DATAWORKS_AGENT_DRY_RUN: "yes", DATAWORKS_AGENT_ENV: "production" }),
    ).toThrow(DryRunForbiddenError)
  })

  test("readProductMode maps env to staging | production | development", () => {
    expect(readProductMode({ DATAWORKS_AGENT_ENV: "staging" })).toBe("staging")
    expect(readProductMode({ DATAWORKS_AGENT_ENV: "production" })).toBe("production")
    expect(readProductMode({ DATAWORKS_AGENT_ENV: "development" })).toBe("development")
    expect(readProductMode({ NODE_ENV: "production" })).toBe("production")
    expect(readProductMode({})).toBe("development")
  })
})
