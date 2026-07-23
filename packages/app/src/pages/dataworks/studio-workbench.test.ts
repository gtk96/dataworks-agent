import { describe, expect, test } from "bun:test"
import { validConnectionID, validProjectID } from "@/context/dataworks"
import { scopeRequestIsCurrent, tableSqlArtifact } from "./resource-explorer"

describe("workbench scope restore", () => {
  test("restores only IDs present in fresh server lists", () => {
    expect(validConnectionID("conn-2", [{ id: "conn-1" }, { id: "conn-2" }])).toBe("conn-2")
    expect(validConnectionID("stale", [{ id: "conn-1" }])).toBe("conn-1")
    expect(validProjectID("2", [{ projectId: 1 }, { projectId: 2 }])).toBe("2")
    expect(validProjectID("stale", [])).toBeUndefined()
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
    expect(scopeRequestIsCurrent("conn-1\n100\nanalytics\ncn-hangzhou", scope)).toBe(true)
    expect(scopeRequestIsCurrent("conn-1\n200\nanalytics\ncn-hangzhou", scope)).toBe(false)
  })
})
