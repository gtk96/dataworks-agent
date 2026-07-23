import { describe, expect, test } from "bun:test"
import {
  QUICK_ACTION_KEYS,
  normalizeDataWorksProject,
  queryChatReadiness,
  quickActionI18nKey,
} from "./dashboard-utils"

describe("dataworks dashboard", () => {
  test("ready when prompt is non-empty", () => {
    expect(queryChatReadiness({ prompt: "查表" })).toEqual({ ready: true })
    expect(queryChatReadiness({ prompt: "SELECT 1" })).toEqual({ ready: true })
  })

  test("blocks only when prompt is empty or whitespace", () => {
    expect(queryChatReadiness({ prompt: "" })).toEqual({ ready: false, reason: "prompt" })
    expect(queryChatReadiness({ prompt: " " })).toEqual({ ready: false, reason: "prompt" })
    expect(queryChatReadiness({ prompt: "\n\t  " })).toEqual({ ready: false, reason: "prompt" })
  })

  test("exposes i18n keys for quick actions rather than hardcoded strings", () => {
    expect(QUICK_ACTION_KEYS).toEqual(["tables", "jobs", "orders", "ping"])
    expect(quickActionI18nKey("tables", "prompt")).toBe("dataworks.chat.prompt.tables")
    expect(quickActionI18nKey("jobs", "label")).toBe("dataworks.chat.label.jobs")
    expect(quickActionI18nKey("orders", "category")).toBe("dataworks.chat.category.orders")
    expect(quickActionI18nKey("ping", "hint")).toBe("dataworks.chat.hint.ping")
  })

  test("normalizes backend project shape id/name to projectId/projectName", () => {
    expect(normalizeDataWorksProject({ id: 10001, name: "dwa_staging", region: "cn-hangzhou" })).toEqual({
      projectId: "10001",
      projectName: "dwa_staging",
      region: "cn-hangzhou",
      envType: undefined,
    })
    expect(normalizeDataWorksProject({ projectId: 7, projectName: "prod" })).toEqual({
      projectId: "7",
      projectName: "prod",
      region: undefined,
      envType: undefined,
    })
    expect(normalizeDataWorksProject({ name: "orphan" })).toBeNull()
  })
})