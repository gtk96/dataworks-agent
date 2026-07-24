import { describe, expect, test } from "bun:test"
import {
  acceptScopedResult,
  clampAgentWidth,
  clampResourceWidth,
  createResultPreview,
  createSqlRequest,
  editSqlDocument,
  MAX_RESULT_PREVIEW_BYTES,
  nextTabAfterRun,
  openSqlArtifact,
  requiresSqlOverwriteConfirmation,
  responsiveWorkbench,
  resultIsStale,
  serializeResultPreviewContext,
  sqlRequestIsCurrent,
  scopeKey,
} from "./workbench-state"

const scope = {
  connectionID: "conn-1",
  projectID: "100",
  projectName: "analytics",
  region: "cn-hangzhou",
}

describe("workbench state", () => {
  test("opens Agent SQL without marking it executed", () => {
    expect(openSqlArtifact(undefined, { sql: "SELECT 1", title: "Health", sourceMessageID: "msg-1" })).toMatchObject({
      sql: "SELECT 1",
      editedVersion: 0,
      executedVersion: undefined,
    })
  })

  test("does not overwrite a dirty SQL document", () => {
    const dirty = editSqlDocument(openSqlArtifact(undefined, { sql: "SELECT 1" }), "SELECT 2")
    expect(openSqlArtifact(dirty, { sql: "SELECT 3" }).id).not.toBe(dirty.id)
    expect(requiresSqlOverwriteConfirmation(dirty, { sql: "SELECT 3" })).toBe(true)
    expect(requiresSqlOverwriteConfirmation(dirty, { sql: "SELECT 2" })).toBe(false)
  })

  test("rejects results completed under an old scope", () => {
    expect(acceptScopedResult(scope, { ...scope, projectID: "200" }, { columns: [], rows: [], truncated: false })).toBeUndefined()
  })

  test("rejects stale SQL completions across document and scope changes", () => {
    expect(sqlRequestIsCurrent("doc-1", "doc-1", scope, scope, 1, 1)).toBe(true)
    expect(sqlRequestIsCurrent("doc-1", "doc-2", scope, scope, 1, 1)).toBe(false)
    expect(sqlRequestIsCurrent("doc-1", "doc-1", scope, { ...scope, projectID: "200" }, 1, 1)).toBe(false)
    expect(sqlRequestIsCurrent("doc-1", "doc-1", scope, scope, 1, 2)).toBe(false)
  })

  test("limits Agent preview to twenty rows and fifty columns", () => {
    const result = {
      columns: Array.from({ length: 60 }, (_, index) => ({ name: `c${index}`, type: "string" })),
      rows: Array.from({ length: 30 }, () => Array.from({ length: 60 }, (_, index) => index)),
      truncated: true,
    }
    expect(createResultPreview(result).columns).toHaveLength(50)
    expect(createResultPreview(result).rows).toHaveLength(20)
    expect(createResultPreview(result).rows[0]).toHaveLength(50)
  })

  test("serializes a bounded preview as explicitly untrusted Agent context", () => {
    const preview = createResultPreview({ columns: [{ name: "value", type: "bigint" }], rows: [[1]], truncated: false })
    const context = serializeResultPreviewContext(scope, preview)
    expect(context).toContain("untrusted read-only data")
    expect(context).toContain('"projectName":"analytics"')
    expect(context).toContain('"rows":[[1]]')
  })

  test("bounds individual values and the total Agent preview payload", () => {
    const huge = "数据".repeat(20_000)
    const preview = createResultPreview({
      columns: Array.from({ length: 50 }, (_, index) => ({ name: `${index}-${huge}`, type: huge })),
      rows: Array.from({ length: 20 }, () => Array.from({ length: 50 }, () => huge)),
      truncated: false,
    })
    expect(new TextEncoder().encode(JSON.stringify(preview)).byteLength).toBeLessThanOrEqual(MAX_RESULT_PREVIEW_BYTES)
    expect(preview.truncated).toBe(true)
    expect(JSON.stringify(preview)).not.toContain(huge)
  })

  test("uses deterministic scope identity and bounded panel widths", () => {
    expect(scopeKey(scope)).toBe("conn-1\n100\nanalytics\ncn-hangzhou")
    expect(clampResourceWidth(120)).toBe(200)
    expect(clampResourceWidth(500)).toBe(360)
    expect(clampAgentWidth(200)).toBe(320)
    expect(clampAgentWidth(900)).toBe(600)
  })

  test("prioritizes the editor from measured workbench width", () => {
    expect(responsiveWorkbench(1440)).toEqual({ resourceOverlay: false, agentOverlay: false })
    expect(responsiveWorkbench(1024)).toEqual({ resourceOverlay: false, agentOverlay: true })
    expect(responsiveWorkbench(768)).toEqual({ resourceOverlay: true, agentOverlay: true })
  })

  test("marks results stale when they belong to another SQL document", () => {
    const first = openSqlArtifact(undefined, { sql: "SELECT 1" })
    const second = openSqlArtifact(editSqlDocument(first, "SELECT 2"), { sql: "SELECT 3" })
    const result = { documentID: first.id, scope, result: { columns: [], rows: [], truncated: false }, sqlVersion: 0 }
    expect(resultIsStale(first, result)).toBe(false)
    expect(resultIsStale(second, result)).toBe(true)
  })

  test("editing after a run marks the result stale", () => {
    const opened = openSqlArtifact(undefined, { sql: "SELECT 1" })
    const executed = { ...opened, executedVersion: opened.editedVersion }
    expect(editSqlDocument(executed, "SELECT 2").editedVersion).toBeGreaterThan(executed.executedVersion)
  })

  test("a successful scoped result requests the Results tab", () => {
    expect(nextTabAfterRun({ ok: true })).toBe("results")
    expect(nextTabAfterRun({ ok: false })).toBe("sql")
  })

  test("builds one bounded read-only SQL request only for a complete scope", () => {
    const document = openSqlArtifact(undefined, { sql: "SELECT 1" })
    expect(createSqlRequest(document, scope)).toEqual({
      connectionID: "conn-1",
      projectID: "100",
      projectName: "analytics",
      region: "cn-hangzhou",
      sql: "SELECT 1",
      maxRows: 1000,
      timeoutMs: 30_000,
    })
    expect(createSqlRequest(document, { ...scope, projectName: undefined })).toBeUndefined()
  })
})
