import { expect, test } from "bun:test"
import { shouldShowSqlArtifactButton } from "./markdown-sql-artifact"

test("shows completed bounded SQL fences without layout metadata", () => {
  expect(shouldShowSqlArtifactButton("SQL", true, "SELECT 1")).toBe(true)
  expect(shouldShowSqlArtifactButton("odps", true, "SELECT 1")).toBe(true)
  expect(shouldShowSqlArtifactButton("MaxCompute", true, "SELECT 1")).toBe(true)
  expect(shouldShowSqlArtifactButton("sql", false, "SELECT 1")).toBe(false)
  expect(shouldShowSqlArtifactButton("sql", true, "x".repeat(4001))).toBe(false)
})
