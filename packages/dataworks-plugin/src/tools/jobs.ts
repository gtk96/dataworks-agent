import { tool } from "@opencode-ai/plugin"
import { client } from "../client.js"

export const dw_list_jobs = tool({
  description: "List DataWorks job instances within a project.",
  args: {
    connectionID: tool.schema.string().describe("Configured DataConnection ID"),
    projectID: tool.schema.number().int().describe("DataWorks project ID"),
    page: tool.schema.number().int().min(1).default(1),
    pageSize: tool.schema.number().int().min(1).max(100).default(10),
  },
  async execute(args, ctx) {
    await ctx.ask({
      permission: "dw_read",
      patterns: [args.connectionID],
      always: [],
      metadata: { tool: "dw_list_jobs" },
    })
    const data = (await client(ctx).execute("dw_list_jobs", args, ctx.sessionID, ctx.abort)) as
      | { items?: Array<{ id: number; name: string; status?: string }> }
      | undefined
    const items = data?.items ?? []
    const output =
      items.map((j) => `${j.id}\t${j.name}\t${j.status ?? ""}`).join("\n") || "(no jobs)"
    return { title: "DataWorks jobs", output, metadata: { count: items.length } }
  },
})

export const dw_get_job_status = tool({
  description: "Get the current status of a specific DataWorks job instance.",
  args: {
    connectionID: tool.schema.string().describe("Configured DataConnection ID"),
    projectID: tool.schema.number().int().describe("DataWorks project ID"),
    instanceID: tool.schema.number().int().describe("Job instance ID"),
  },
  async execute(args, ctx) {
    await ctx.ask({
      permission: "dw_read",
      patterns: [args.connectionID],
      always: [],
      metadata: { tool: "dw_get_job_status" },
    })
    const data = await client(ctx).execute("dw_get_job_status", args, ctx.sessionID, ctx.abort)
    return {
      title: `job ${args.instanceID}`,
      output: data == null ? "(not found)" : typeof data === "string" ? data : JSON.stringify(data, null, 2),
      metadata: { instanceID: args.instanceID },
    }
  },
})
