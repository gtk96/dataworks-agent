import { describe, expect, test } from "bun:test"
import { formatSqlCell, parseSqlResultView, sqlResultSubtitle, sqlResultToTsv } from "./sql-result"

describe("parseSqlResultView", () => {
  test("reads structured metadata", () => {
    const view = parseSqlResultView({
      metadata: {
        kind: "sql_result",
        columns: [{ name: "id", type: "bigint" }],
        previewRows: [[1], [2]],
        rowCount: 2,
        truncated: false,
        durationMs: 9,
        projectID: 7,
        connectionID: "c1",
      },
    })
    expect(view?.columns).toEqual([{ name: "id", type: "bigint" }])
    expect(view?.rows).toEqual([[1], [2]])
    expect(view?.rowCount).toBe(2)
    expect(view?.durationMs).toBe(9)
    expect(view?.projectID).toBe(7)
    expect(sqlResultSubtitle(view!)).toContain("2 rows")
    expect(sqlResultToTsv(view!)).toBe("id\n1\n2")
  })

  test("falls back to tsv output", () => {
    const view = parseSqlResultView({
      output: "a\tb\n1\t2\n… truncated (10 rows total)",
    })
    expect(view?.columns.map((column) => column.name)).toEqual(["a", "b"])
    expect(view?.rows).toEqual([["1", "2"]])
    expect(view?.truncated).toBe(true)
  })

  test("empty output", () => {
    expect(parseSqlResultView({ output: "(no rows)" })?.rowCount).toBe(0)
    expect(parseSqlResultView({})).toBeUndefined()
  })
})

describe("formatSqlCell", () => {
  test("stringifies values", () => {
    expect(formatSqlCell(null)).toBe("")
    expect(formatSqlCell(1)).toBe("1")
    expect(formatSqlCell({ a: 1 })).toBe('{"a":1}')
  })
})
