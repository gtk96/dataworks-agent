import { describe, expect, test } from "bun:test"
import { projectKey, projectLabel } from "./query-scope-utils"

describe("dataworks query scope", () => {
  test("normalizes project identity and display", () => {
    expect(projectKey({ projectId: 7, projectName: "经营分析" })).toBe("7")
    expect(projectLabel({ projectId: 7, projectName: "经营分析" })).toBe("经营分析 (7)")
    expect(projectLabel({ projectId: "p1" })).toBe("p1")
  })

  test("falls back to alternate fields when projectName is missing", () => {
    expect(projectKey({ projectId: "abc", name: "ignored" } as never)).toBe("abc")
    expect(projectKey({ projectId: "" } as never)).toBe("")
    expect(projectKey({} as never)).toBe("")
    expect(projectLabel({} as never)).toBe("project")
  })

  test("accepts backend Project shape with id/name only", () => {
    expect(projectKey({ id: 10001, name: "dwa_staging" } as never)).toBe("10001")
    expect(projectLabel({ id: 10001, name: "dwa_staging" } as never)).toBe("dwa_staging (10001)")
  })
})
