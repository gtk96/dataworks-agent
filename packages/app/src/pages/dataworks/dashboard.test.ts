import { describe, expect, test } from "bun:test"
import {
  normalizeDataWorksProject,
  queryChatReadiness,
  serverModelLabel,
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

  test("uses the supported server display label", () => {
    expect(serverModelLabel({ type: "http", http: { url: "http://localhost:4096" } }, "DataWorks AI")).toBe(
      "localhost:4096",
    )
  })
})
