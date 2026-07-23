import { tool } from "@opencode-ai/plugin"
import { client } from "../client.js"

export const dw_list_projects = tool({
  description: "List DataWorks projects visible through the selected data connection.",
  args: {
    connectionID: tool.schema.string().describe("Configured DataConnection ID"),
    page: tool.schema.number().int().min(1).default(1).describe("1-based page number"),
    pageSize: tool.schema.number().int().min(1).max(100).default(10).describe("Page size (1-100)"),
    region: tool.schema.string().default("cn-hangzhou").describe("Region identifier"),
  },
  async execute(args, ctx) {
    await ctx.ask({
      permission: "dw_read",
      patterns: [args.connectionID],
      always: [],
      metadata: { tool: "dw_list_projects" },
    })
    const data = (await client(ctx).execute(
      "dw_list_projects",
      args,
      ctx.sessionID,
      ctx.abort,
    )) as { items?: Array<{ id: number; name: string; envType?: string; region?: string }> } | undefined
    const items = data?.items ?? []
    const output = items.map((p) => `${p.id}\t${p.name}\t${p.envType ?? ""}\t${p.region ?? ""}`).join("\n") || "(no projects)"
    return { title: "DataWorks projects", output, metadata: { count: items.length } }
  },
})