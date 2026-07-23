import { expect, test } from "bun:test"
import { emitSqlArtifact, isSqlArtifactDetail, SQL_ARTIFACT_EVENT } from "./sql-artifact-event"

test("emits a bounded typed SQL artifact without execution", () => {
  const target = new EventTarget()
  let detail: unknown
  target.addEventListener(SQL_ARTIFACT_EVENT, (event) => {
    detail = (event as CustomEvent).detail
  })
  emitSqlArtifact(target, { sql: "SELECT 1", source: "agent-markdown" })
  expect(isSqlArtifactDetail(detail)).toBe(true)
  expect(detail).toEqual({ sql: "SELECT 1", source: "agent-markdown" })
})

test("rejects empty and oversized payloads", () => {
  expect(isSqlArtifactDetail({ sql: "", source: "agent-markdown" })).toBe(false)
  expect(isSqlArtifactDetail({ sql: "x".repeat(4001), source: "agent-markdown" })).toBe(false)
})
