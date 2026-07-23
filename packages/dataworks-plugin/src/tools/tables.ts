import { tool } from "@opencode-ai/plugin"
import { client } from "../client.js"

function asOutput(data: unknown, empty: string): { title: string; output: string; metadata: Record<string, unknown> } {
  if (data == null) return { title: "tables", output: empty, metadata: {} }
  if (typeof data === "string") return { title: "tables", output: data, metadata: {} }
  const items = Array.isArray((data as { items?: unknown }).items)
    ? (data as { items: unknown[] }).items
    : null
  if (items) {
    const output =
      items
        .map((row) => {
          if (row && typeof row === "object") {
            const r = row as Record<string, unknown>
            return [r.name ?? r.tableName ?? r.id, r.type ?? r.envType ?? ""].filter(Boolean).join("\t")
          }
          return String(row)
        })
        .join("\n") || empty
    return { title: "tables", output, metadata: { count: items.length } }
  }
  return { title: "tables", output: JSON.stringify(data, null, 2), metadata: {} }
}

export const dw_list_tables = tool({
  description: "List tables within a DataWorks project accessible through the selected connection.",
  args: {
    connectionID: tool.schema.string().describe("Configured DataConnection ID"),
    projectID: tool.schema.number().int().describe("DataWorks project ID"),
    page: tool.schema.number().int().min(1).default(1),
    pageSize: tool.schema.number().int().min(1).max(200).default(50),
  },
  async execute(args, ctx) {
    await ctx.ask({
      permission: "dw_read",
      patterns: [args.connectionID],
      always: [],
      metadata: { tool: "dw_list_tables" },
    })
    const data = await client(ctx).execute("dw_list_tables", args, ctx.sessionID, ctx.abort)
    return asOutput(data, "(no tables)")
  },
})

export const dw_describe_table = tool({
  description: "Describe the schema and metadata of a single DataWorks table.",
  args: {
    connectionID: tool.schema.string().describe("Configured DataConnection ID"),
    projectID: tool.schema.number().int().describe("DataWorks project ID"),
    tableName: tool.schema.string().describe("Table name to describe"),
  },
  async execute(args, ctx) {
    await ctx.ask({
      permission: "dw_read",
      patterns: [args.connectionID],
      always: [],
      metadata: { tool: "dw_describe_table" },
    })
    const data = await client(ctx).execute("dw_describe_table", args, ctx.sessionID, ctx.abort)
    return {
      title: `describe ${args.tableName}`,
      output: data == null ? "(no schema)" : typeof data === "string" ? data : JSON.stringify(data, null, 2),
      metadata: { tableName: args.tableName },
    }
  },
})
