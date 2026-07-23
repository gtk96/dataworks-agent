import { expect, test } from "bun:test"
import { shouldShowSqlArtifactButton } from "./markdown-sql-artifact"

test("shows completed normalized SQL fences without layout metadata", () => {
  expect(shouldShowSqlArtifactButton("SQL", true)).toBe(true)
  expect(shouldShowSqlArtifactButton("odps", true)).toBe(true)
  expect(shouldShowSqlArtifactButton("MaxCompute", true)).toBe(true)
  expect(shouldShowSqlArtifactButton("sql", false)).toBe(false)
})
