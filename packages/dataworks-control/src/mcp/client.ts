export interface McpServerConfig {
  readonly endpoint: string
  readonly allowedTools: ReadonlyArray<string>
  readonly resolveSecretHeaders?: () => Promise<Record<string, string>>
}

export interface McpDataWorksClientConfig {
  readonly servers: Readonly<Record<string, McpServerConfig>>
  readonly fetch?: typeof fetch
}

export interface McpCallInput {
  readonly server: string
  readonly tool: string
  readonly args: Readonly<Record<string, unknown>>
}

export class McpToolNotAllowedError extends Error {
  constructor(server: string, tool: string) {
    super(`MCP tool is not allowed: ${server}/${tool}`)
    this.name = "McpToolNotAllowedError"
  }
}

export class McpCallError extends Error {
  constructor(
    message: string,
    readonly code: number | string,
  ) {
    super(message)
    this.name = "McpCallError"
  }
}

export class McpDataWorksClient {
  private requestID = 0

  constructor(private readonly config: McpDataWorksClientConfig) {}

  async call(input: McpCallInput): Promise<unknown> {
    const server = this.config.servers[input.server]
    if (!server || !server.allowedTools.includes(input.tool)) {
      throw new McpToolNotAllowedError(input.server, input.tool)
    }

    const response = await (this.config.fetch ?? fetch)(server.endpoint, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "mcp-protocol-version": "2025-03-26",
        ...(server.resolveSecretHeaders ? await server.resolveSecretHeaders() : {}),
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: ++this.requestID,
        method: "tools/call",
        params: { name: input.tool, arguments: input.args },
      }),
    })

    if (!response.ok) throw new McpCallError(`MCP request failed with status ${response.status}`, response.status)
    const payload = await response.json() as {
      result?: unknown
      error?: { code?: number | string; message?: string }
    }
    if (payload.error) {
      throw new McpCallError(payload.error.message ?? "MCP request failed", payload.error.code ?? "mcp_error")
    }
    if (!("result" in payload)) throw new McpCallError("MCP response omitted result", "invalid_response")
    return payload.result
  }
}
