import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { McpCallError, McpDataWorksClient, McpToolNotAllowedError } from "../../../packages/dataworks-control/src/mcp/client"

let server: ReturnType<typeof Bun.serve>
let calls = 0

beforeAll(() => {
  server = Bun.serve({
    port: 0,
    async fetch(request) {
      calls += 1
      if (request.headers.get("x-mcp-secret") !== "dry-run-secret") {
        return Response.json({ error: "unauthorized" }, { status: 401 })
      }
      const body = await request.json() as {
        id: number
        method: string
        params: { name: string; arguments: unknown }
      }
      if (body.params.name === "dw_broken_tool") {
        return Response.json({
          jsonrpc: "2.0",
          id: body.id,
          error: { code: -32000, message: "fixture MCP failure" },
        })
      }
      return Response.json({
        jsonrpc: "2.0",
        id: body.id,
        result: { content: [{ type: "text", text: JSON.stringify({ status: "Running" }) }] },
      })
    },
  })
})

afterAll(() => server.stop(true))

function makeClient() {
  return new McpDataWorksClient({
    servers: {
      staging: {
        endpoint: `http://127.0.0.1:${server.port}`,
        allowedTools: ["dw_get_job_status", "dw_broken_tool"],
        resolveSecretHeaders: async () => ({ "x-mcp-secret": "dry-run-secret" }),
      },
    },
  })
}

describe("explicit MCP fallback", () => {
  test("calls only an allowlisted MCP server and tool pair", async () => {
    const result = await makeClient().call({
      server: "staging",
      tool: "dw_get_job_status",
      args: { instanceID: 90001 },
    })
    expect(result).toEqual({ content: [{ type: "text", text: "{\"status\":\"Running\"}" }] })
  })

  test("rejects a non-allowlisted tool before making a request", async () => {
    const callsBefore = calls
    await expect(makeClient().call({
      server: "staging",
      tool: "dw_rerun_job",
      args: { instanceID: 90001 },
    })).rejects.toBeInstanceOf(McpToolNotAllowedError)
    expect(calls).toBe(callsBefore)
  })

  test("surfaces MCP failures instead of selecting another adapter", async () => {
    await expect(makeClient().call({
      server: "staging",
      tool: "dw_broken_tool",
      args: {},
    })).rejects.toMatchObject({
      name: "McpCallError",
      code: -32000,
    } satisfies Partial<McpCallError>)
  })
})
