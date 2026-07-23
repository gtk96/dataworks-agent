import { tool } from "@opencode-ai/plugin"
import { client } from "../client.js"
import { buildSqlResult } from "./sql-result.js"

const MAX_ROWS_CAP = 10_000
const TIMEOUT_MS_CAP = 300_000

export const dw_run_sql = tool({
  description:
    "Execute a read-only SQL query against a DataWorks project through the selected connection. Returns the query result rows.",
  args: {
    connectionID: tool.schema.string().describe("Configured DataConnection ID"),
    projectID: tool.schema.number().int().describe("DataWorks project ID"),
    sql: tool.schema.string().describe("SQL query to execute (must be read-only)"),
    maxRows: tool.schema.number().int().min(1).max(MAX_ROWS_CAP).default(1000).describe("Max rows to return (1-10000)"),
    timeoutMs: tool.schema
      .number()
      .int()
      .min(1000)
      .max(TIMEOUT_MS_CAP)
      .default(30_000)
      .describe("Timeout in ms (1s-300000ms)"),
  },
  async execute(args, ctx) {
    await ctx.ask({
      permission: "dw_query",
      patterns: [args.connectionID],
      always: [],
      metadata: { tool: "dw_run_sql" },
    })
    const maxRows = Math.min(args.maxRows, MAX_ROWS_CAP)
    const timeoutMs = Math.min(args.timeoutMs, TIMEOUT_MS_CAP)
    const data = await client(ctx).execute(
      "dw_run_sql",
      { ...args, maxRows, timeoutMs },
      ctx.sessionID,
      ctx.abort,
    )
    return buildSqlResult({
      data,
      connectionID: args.connectionID,
      projectID: args.projectID,
      maxRows,
      timeoutMs,
    })
  },
})
