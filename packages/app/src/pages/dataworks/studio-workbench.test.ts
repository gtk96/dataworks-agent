import { describe, expect, test } from "bun:test"
import { projectRequestIsCurrent, validConnectionID, validProjectID } from "@/context/dataworks"
import { scopeRequestIsCurrent, tableSqlArtifact } from "./resource-explorer"
import { normalizeResultColumns, visibleResultRows } from "./results-grid"

describe("workbench scope restore", () => {
  test("restores only IDs present in fresh server lists", () => {
    expect(validConnectionID("conn-2", [{ id: "conn-1" }, { id: "conn-2" }])).toBe("conn-2")
    expect(validConnectionID("stale", [{ id: "conn-1" }])).toBe("conn-1")
    expect(validProjectID("2", [{ projectId: 1 }, { projectId: 2 }])).toBe("2")
    expect(validProjectID("stale", [])).toBeUndefined()
  })

  test("rejects stale project responses across connection changes", () => {
    expect(projectRequestIsCurrent("conn-a", "conn-a", 1, 1)).toBe(true)
    expect(projectRequestIsCurrent("conn-a", "conn-b", 1, 1)).toBe(false)
    expect(projectRequestIsCurrent("conn-a", "conn-a", 1, 2)).toBe(false)
  })
})

describe("resource explorer", () => {
  const scope = {
    connectionID: "conn-1",
    projectID: "100",
    projectName: "analytics",
    region: "cn-hangzhou",
  }

  test("opens a bounded table query without execution", () => {
    expect(tableSqlArtifact({ name: "orders" })).toEqual({
      sql: "SELECT * FROM orders LIMIT 100",
      title: "orders",
    })
  })

  test("rejects an async completion from a stale scope", () => {
    expect(scopeRequestIsCurrent("conn-1\n100\nanalytics\ncn-hangzhou", scope, 1, 1)).toBe(true)
    expect(scopeRequestIsCurrent("conn-1\n200\nanalytics\ncn-hangzhou", scope, 1, 1)).toBe(false)
  })

  test("rejects an older table request within the same scope", () => {
    expect(scopeRequestIsCurrent("conn-1\n100\nanalytics\ncn-hangzhou", scope, 1, 2)).toBe(false)
    expect(scopeRequestIsCurrent("conn-1\n100\nanalytics\ncn-hangzhou", scope, 2, 2)).toBe(true)
  })
})

describe("results grid", () => {
  test("normalizes result columns and bounds visible rows", () => {
    expect(normalizeResultColumns(["raw", { name: "", type: "bigint" }])).toEqual([
      { name: "raw", type: "" },
      { name: "col_2", type: "bigint" },
    ])
    expect(visibleResultRows(Array.from({ length: 1001 }, (_, index) => [index]))).toHaveLength(1000)
  })
})
