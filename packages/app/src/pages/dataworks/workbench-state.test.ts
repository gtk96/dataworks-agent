import { describe, expect, test } from "bun:test"
import {
  acceptScopedResult,
  clampAgentWidth,
  clampResourceWidth,
  createResultPreview,
  editSqlDocument,
  openSqlArtifact,
  responsiveWorkbench,
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
  })

  test("rejects results completed under an old scope", () => {
    expect(acceptScopedResult(scope, { ...scope, projectID: "200" }, { columns: [], rows: [], truncated: false })).toBeUndefined()
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

  test("uses deterministic scope identity and bounded panel widths", () => {
    expect(scopeKey(scope)).toBe("conn-1\n100\nanalytics\ncn-hangzhou")
    expect(clampResourceWidth(120)).toBe(200)
    expect(clampResourceWidth(500)).toBe(360)
    expect(clampAgentWidth(200)).toBe(320)
    expect(clampAgentWidth(900)).toBe(600)
  })

  test("prioritizes the editor below 960px", () => {
    expect(responsiveWorkbench(1440)).toEqual({ resourceOverlay: false, agentOverlay: false })
    expect(responsiveWorkbench(1024)).toEqual({ resourceOverlay: false, agentOverlay: false })
    expect(responsiveWorkbench(768)).toEqual({ resourceOverlay: true, agentOverlay: true })
  })
})
