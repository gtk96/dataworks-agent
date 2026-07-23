import { tool } from "@opencode-ai/plugin"
import { client } from "../client.js"

export const dw_table_lineage = tool({
  description: "Get upstream and downstream lineage for a DataWorks table.",
  args: {
    connectionID: tool.schema.string().describe("Configured DataConnection ID"),
    projectID: tool.schema.number().int().describe("DataWorks project ID"),
    tableName: tool.schema.string().describe("Table name to trace lineage for"),
  },
  async execute(args, ctx) {
    await ctx.ask({
      permission: "dw_read",
      patterns: [args.connectionID],
      always: [],
      metadata: { tool: "dw_table_lineage" },
    })
    const data = await client(ctx).execute("dw_table_lineage", args, ctx.sessionID, ctx.abort)
    return {
      title: `lineage ${args.tableName}`,
      output: data == null ? "(no lineage)" : typeof data === "string" ? data : JSON.stringify(data, null, 2),
      metadata: { tableName: args.tableName },
    }
  },
})

export const dw_alert_list = tool({
  description: "List active DataWorks alerts visible through the selected connection.",
  args: {
    connectionID: tool.schema.string().describe("Configured DataConnection ID"),
    page: tool.schema.number().int().min(1).default(1),
    pageSize: tool.schema.number().int().min(1).max(100).default(10),
  },
  async execute(args, ctx) {
    await ctx.ask({
      permission: "dw_read",
      patterns: [args.connectionID],
      always: [],
      metadata: { tool: "dw_alert_list" },
    })
    const data = (await client(ctx).execute("dw_alert_list", args, ctx.sessionID, ctx.abort)) as
      | { items?: unknown[] }
      | undefined
    const items = data?.items ?? []
    const output =
      items
        .map((row) => (row && typeof row === "object" ? JSON.stringify(row) : String(row)))
        .join("\n") || "(no alerts)"
    return { title: "DataWorks alerts", output, metadata: { count: items.length } }
  },
})

export const dw_mcp_call = tool({
  description: "Invoke an MCP tool exposed by the DataWorks control plane.",
  args: {
    connectionID: tool.schema.string().describe("Configured DataConnection ID"),
    server: tool.schema.string().describe("MCP server name"),
    method: tool.schema.string().describe("MCP method to invoke"),
    arguments: tool.schema.record(tool.schema.string(), tool.schema.unknown()).optional(),
  },
  async execute(args, ctx) {
    await ctx.ask({
      permission: "dw_read",
      patterns: [args.connectionID],
      always: [],
      metadata: { tool: "dw_mcp_call" },
    })
    const data = await client(ctx).execute("dw_mcp_call", args, ctx.sessionID, ctx.abort)
    return {
      title: `mcp ${args.server}/${args.method}`,
      output: data == null ? "(empty)" : typeof data === "string" ? data : JSON.stringify(data, null, 2),
      metadata: { server: args.server, method: args.method },
    }
  },
})
