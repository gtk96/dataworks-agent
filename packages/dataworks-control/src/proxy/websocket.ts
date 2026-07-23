import type { ServerWebSocket } from "bun"
import { checkOrigin } from "../http/csrf"
import type { ProxyContext } from "./http"
import { workerTargetUrl, websocketTargetURL, websocketProtocols } from "./http"

export interface WorkerWsProxyData {
  targetWs: string
  workerAuth: string
  protocols: string[]
  upstream?: WebSocket
  closed?: boolean
  pending?: Array<string | Buffer>
}

/**
 * Complete a browser → control-plane WebSocket upgrade and prepare reverse-proxy
 * metadata. Bun requires `server.upgrade` to run inside the fetch handler.
 *
 * Returns `undefined` when the upgrade succeeds (Bun owns the connection).
 * Returns a Response on Origin rejection or upgrade failure.
 *
 * The actual upstream dial happens in `workerWebSocketHandlers.open`.
 */
export function proxyWorkerWebSocket(
  req: Request,
  server: { upgrade: (req: Request, opts?: { data?: WorkerWsProxyData; headers?: Record<string, string> }) => boolean },
  ctx: ProxyContext,
): Response | undefined {
  if (!checkOrigin(req, ctx.publicOrigin)) {
    return new Response("forbidden_origin", { status: 403 })
  }

  const url = new URL(req.url)
  const targetHttp = workerTargetUrl(url, ctx)
  const targetWs = websocketTargetURL(targetHttp)
  const protocols = websocketProtocols(req)

  const data: WorkerWsProxyData = {
    targetWs,
    workerAuth: ctx.workerAuth,
    protocols,
    pending: [],
  }

  const upgraded = server.upgrade(req, { data })
  if (!upgraded) {
    return new Response("websocket_upgrade_failed", { status: 400 })
  }
  return undefined
}

function attachUpstreamPump(ws: ServerWebSocket<WorkerWsProxyData>, upstream: WebSocket) {
  upstream.addEventListener("message", (ev) => {
    try {
      if (typeof ev.data === "string") {
        ws.send(ev.data)
      } else if (ev.data instanceof ArrayBuffer) {
        ws.send(new Uint8Array(ev.data))
      } else if (ArrayBuffer.isView(ev.data)) {
        ws.send(ev.data as Uint8Array)
      }
    } catch {
      // client gone
    }
  })
  upstream.addEventListener("close", (ev) => {
    try {
      ws.close(ev.code, ev.reason)
    } catch {
      // ignore
    }
  })
  upstream.addEventListener("error", () => {
    try {
      ws.close(1011, "upstream_error")
    } catch {
      // ignore
    }
  })
  upstream.addEventListener("open", () => {
    const pending = ws.data.pending ?? []
    ws.data.pending = []
    for (const payload of pending) {
      try {
        if (typeof payload === "string") upstream.send(payload)
        else upstream.send(payload)
      } catch {
        // ignore
      }
    }
  })
}

/**
 * Bun.serve websocket handlers that reverse-proxy frames to the worker.
 * Pair with `proxyWorkerWebSocket`, which upgrades the client and stores target metadata.
 */
export const workerWebSocketHandlers = {
  open(ws: ServerWebSocket<WorkerWsProxyData>) {
    const data = ws.data
    try {
      const opts: { protocols?: string[]; headers: Record<string, string> } = {
        headers: { authorization: data.workerAuth },
      }
      if (data.protocols.length > 0) opts.protocols = data.protocols
      // Browser Cookie/Authorization are never forwarded; only worker Basic auth.
      const upstream = new WebSocket(data.targetWs, opts as never)
      data.upstream = upstream
      attachUpstreamPump(ws, upstream)
    } catch {
      data.closed = true
      try {
        ws.close(1011, "upstream_connect_failed")
      } catch {
        // ignore
      }
    }
  },
  message(ws: ServerWebSocket<WorkerWsProxyData>, message: string | Buffer) {
    const upstream = ws.data.upstream
    if (!upstream) {
      ws.data.pending?.push(message)
      return
    }
    if (upstream.readyState === WebSocket.CONNECTING) {
      ws.data.pending?.push(message)
      return
    }
    if (upstream.readyState !== WebSocket.OPEN) return
    try {
      if (typeof message === "string") upstream.send(message)
      else upstream.send(message)
    } catch {
      // ignore
    }
  },
  close(ws: ServerWebSocket<WorkerWsProxyData>, _code: number, _reason: string) {
    ws.data.closed = true
    try {
      ws.data.upstream?.close()
    } catch {
      // ignore
    }
  },
}

/**
 * Fallback when called without a Bun Server upgrade handle (e.g. pure Hono path).
 * Real product path must use Bun.serve + `proxyWorkerWebSocket`.
 */
export async function proxyWorkerWebSocketResponse(req: Request, ctx: ProxyContext): Promise<Response> {
  if (!checkOrigin(req, ctx.publicOrigin)) {
    return new Response("forbidden_origin", { status: 403 })
  }
  return new Response("websocket_upgrade_requires_bun_serve", { status: 426 })
}
