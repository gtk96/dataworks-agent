import { describe, expect, test } from "bun:test"
import { SQL_PREVIEW_ROW_CAP, buildSqlResult, formatSqlOutput } from "../src/tools/sql-result"

describe("buildSqlResult", () => {
  test("normalizes array-of-objects rows with columns", () => {
    const result = buildSqlResult({
      data: {
        columns: [
          { name: "id", type: "bigint" },
          { name: "name", type: "string" },
        ],
        rows: [
          { id: 1, name: "a" },
          { id: 2, name: "b" },
        ],
        truncated: false,
        durationMs: 12,
        instanceId: "i-1",
      },
      connectionID: "conn_1",
      projectID: 42,
      maxRows: 1000,
      timeoutMs: 30_000,
    })

    expect(result.metadata.kind).toBe("sql_result")
    expect(result.metadata.columns).toEqual([
      { name: "id", type: "bigint" },
      { name: "name", type: "string" },
    ])
    expect(result.metadata.previewRows).toEqual([
      [1, "a"],
      [2, "b"],
    ])
    expect(result.metadata.rowCount).toBe(2)
    expect(result.metadata.connectionID).toBe("conn_1")
    expect(result.metadata.projectID).toBe(42)
    expect(result.metadata.durationMs).toBe(12)
    expect(result.metadata.instanceId).toBe("i-1")
    expect(result.output).toContain("id\tname")
    expect(result.output).toContain("1\ta")
  })

  test("caps preview rows and marks truncated", () => {
    const rows = Array.from({ length: SQL_PREVIEW_ROW_CAP + 50 }, (_, index) => [index])
    const result = buildSqlResult({
      data: {
        columns: ["n"],
        rows,
        truncated: false,
      },
      connectionID: "c",
      projectID: 1,
      maxRows: 10_000,
      timeoutMs: 30_000,
    })
    expect(result.metadata.previewRows.length).toBe(SQL_PREVIEW_ROW_CAP)
    expect(result.metadata.rowCount).toBe(SQL_PREVIEW_ROW_CAP + 50)
    expect(result.metadata.truncated).toBe(true)
    expect(result.output).toContain("truncated")
  })

  test("handles null and plain string payloads", () => {
    expect(buildSqlResult({ data: null, connectionID: "c", projectID: 1, maxRows: 10, timeoutMs: 1000 }).output).toBe(
      "(no rows)",
    )
    const stringed = buildSqlResult({
      data: "ok",
      connectionID: "c",
      projectID: 1,
      maxRows: 10,
      timeoutMs: 1000,
    })
    expect(stringed.output).toBe("ok")
    expect(stringed.metadata.previewRows).toEqual([["ok"]])
  })
})

describe("formatSqlOutput", () => {
  test("formats empty results", () => {
    expect(formatSqlOutput({ columns: [], rows: [], truncated: false, rowCount: 0 })).toBe("(no rows)")
  })
})
