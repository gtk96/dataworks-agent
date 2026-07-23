import type { ToolContext } from "@opencode-ai/plugin"

export type DataWorksToolContext = ToolContext

export interface ControlPlaneClientOptions {
  readonly baseUrl: string
  readonly workerToken: string
  readonly workerID: string
}

const MAX_RESPONSE_BYTES = 10 * 1024 * 1024

export class ControlPlaneClient {
  private constructor(private readonly options: ControlPlaneClientOptions) {}

  static fromContext(ctx: ToolContext, env: NodeJS.ProcessEnv = process.env): ControlPlaneClient {
    const baseUrl = env.DATAWORKS_CONTROL_PLANE_URL
    const workerToken = env.DATAWORKS_WORKER_TOKEN
    const workerID = env.DATAWORKS_WORKER_ID
    if (!baseUrl) throw new Error("DATAWORKS_CONTROL_PLANE_URL not set")
    if (!workerToken) throw new Error("DATAWORKS_WORKER_TOKEN not set")
    if (!workerID) throw new Error("DATAWORKS_WORKER_ID not set")
    return new ControlPlaneClient({ baseUrl, workerToken, workerID })
  }

  async execute(
    tool: string,
    args: Readonly<Record<string, unknown>>,
    sessionID: string,
    signal: AbortSignal,
  ): Promise<unknown> {
    return this.executeInternal(tool, args, sessionID, signal)
  }

  async executeWrite(
    tool: string,
    args: Readonly<Record<string, unknown>>,
    ticket: string,
    sessionID: string,
    signal: AbortSignal,
  ): Promise<unknown> {
    return this.executeInternal(tool, args, sessionID, signal, ticket)
  }

  /**
   * Look up whether the connection has writes enabled. Uses the control-plane
   * worker-facing connection metadata endpoint when available; falls back to
   * null (unknown) so the write-ticket path remains the authoritative gate.
   */
  async isWriteEnabled(connectionID: string, signal: AbortSignal): Promise<boolean | null> {
    const url = new URL(`/internal/dataworks/connections/${encodeURIComponent(connectionID)}`, this.options.baseUrl)
    const response = await fetch(url.toString(), {
      method: "GET",
      headers: {
        authorization: `Bearer ${this.options.workerToken}`,
        "x-dataworks-worker-id": this.options.workerID,
      },
      signal,
    })
    if (response.status === 404) return null
    if (!response.ok) return null
    const data = (await response.json().catch(() => null)) as { writeEnabled?: boolean } | null
    if (!data || typeof data.writeEnabled !== "boolean") return null
    return data.writeEnabled
  }

  async recordWriteRejected(
    input: {
      connectionID: string
      tool: string
      argsHash: string
      sessionID?: string
    },
    signal: AbortSignal,
  ): Promise<void> {
    const url = new URL("/internal/dataworks/write-reject", this.options.baseUrl).toString()
    await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${this.options.workerToken}`,
        "x-dataworks-worker-id": this.options.workerID,
      },
      body: JSON.stringify({
        connectionID: input.connectionID,
        tool: input.tool,
        argsHash: input.argsHash,
        sessionID: input.sessionID ?? null,
      }),
      signal,
    }).catch(() => undefined)
  }

  async issueWriteTicket(
    input: {
      connectionID: string
      tool: string
      argsHash: string
      reason: string
      sessionID?: string
    },
    signal: AbortSignal,
  ): Promise<string> {
    const url = new URL("/internal/dataworks/write-tickets", this.options.baseUrl).toString()
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${this.options.workerToken}`,
        "x-dataworks-worker-id": this.options.workerID,
      },
      body: JSON.stringify({
        connectionID: input.connectionID,
        tool: input.tool,
        argsHash: input.argsHash,
        reason: input.reason,
        sessionID: input.sessionID ?? null,
      }),
      signal,
    })
    const data = (await response.json().catch(() => null)) as { ticket?: string; error?: string } | null
    if (response.status === 400) {
      throw new ControlPlaneError("invalid_response", data?.error ?? "reason_required", 400)
    }
    if (response.status === 403) {
      throw new ControlPlaneError("forbidden", data?.error ?? "write_disabled", 403)
    }
    if (response.status === 401) {
      throw new ControlPlaneError("unauthorized", "auth_failed", 401)
    }
    if (!response.ok || !data?.ticket) {
      throw new ControlPlaneError("internal", data?.error ?? "ticket_issue_failed", response.status)
    }
    return data.ticket
  }

  private async executeInternal(
    tool: string,
    args: Readonly<Record<string, unknown>>,
    sessionID: string,
    signal: AbortSignal,
    ticket?: string,
  ): Promise<unknown> {
    const connectionID = args.connectionID
    if (typeof connectionID !== "string") {
      throw new ControlPlaneError("invalid_response", "connectionID required in args", 400)
    }

    const url = new URL("/internal/dataworks/execute", this.options.baseUrl).toString()
    const headers: Record<string, string> = {
      "content-type": "application/json",
      authorization: `Bearer ${this.options.workerToken}`,
      "x-dataworks-worker-id": this.options.workerID,
    }

    const response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({ tool, args, sessionID, connectionID, ...(ticket ? { ticket } : {}) }),
      signal,
    })

    if (response.status === 403) {
      throw new ControlPlaneError("forbidden", "write_ticket_required", response.status)
    }
    if (response.status === 401) {
      throw new ControlPlaneError("unauthorized", "auth_failed", response.status)
    }
    if (response.status === 409) {
      throw new ControlPlaneError("conflict", "write_ticket_invalid_or_consumed", response.status)
    }

    const contentLength = response.headers.get("content-length")
    if (contentLength && Number(contentLength) > MAX_RESPONSE_BYTES) {
      throw new ControlPlaneError("too_large", "response_exceeds_10mb", 413)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new ControlPlaneError("invalid_response", "no response body", 500)
    }
    const chunks: Uint8Array[] = []
    let total = 0
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (!value) continue
      total += value.byteLength
      if (total > MAX_RESPONSE_BYTES) {
        await reader.cancel()
        throw new ControlPlaneError("too_large", "response_exceeds_10mb", 413)
      }
      chunks.push(value)
    }
    const body = new TextDecoder().decode(Buffer.concat(chunks))
    const data = JSON.parse(body) as unknown

    if (!response.ok) {
      const message =
        data && typeof data === "object" && "error" in data
          ? String((data as { error: unknown }).error)
          : "internal"
      throw new ControlPlaneError("internal", message, response.status)
    }

    return data
  }
}

export class ControlPlaneError extends Error {
  constructor(
    readonly tag: "forbidden" | "unauthorized" | "conflict" | "too_large" | "invalid_response" | "internal",
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = "ControlPlaneError"
  }
}

export function client(ctx: ToolContext): ControlPlaneClient {
  return ControlPlaneClient.fromContext(ctx)
}