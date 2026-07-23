#!/usr/bin/env bun
import { readFileSync } from "fs"

const port = Number(process.env.PORT ?? 4096)
const host = "127.0.0.1"
const username = process.env.WORKER_USERNAME ?? "dwa-worker"
const password = process.env.WORKER_PASSWORD ?? "default-insecure"

// Fake LLM provider port - streams SSE chunks.
// Default 0 = ephemeral so concurrent native workers do not collide.
const FAKE_LLM_PORT = Number(process.env.FAKE_LLM_PORT ?? 0)
let fakeLlmHeaders: Headers | null = null

function authorized(req: Request): boolean {
  const header = req.headers.get("authorization")
  if (!header) return false
  if (!header.toLowerCase().startsWith("basic ")) return false
  const decoded = atob(header.slice(6))
  const sep = decoded.indexOf(":")
  if (sep < 0) return false
  const u = decoded.slice(0, sep)
  const p = decoded.slice(sep + 1)
  return u === username && p === password
}

// Start fake LLM provider server
const fakeLlmServer = Bun.serve({
  port: FAKE_LLM_PORT,
  hostname: "127.0.0.1",
  async fetch(req) {
    // Record headers for test verification
    fakeLlmHeaders = req.headers
    await req.text()

    // Stream 3 SSE chunks + [DONE]
    const chunks = [
      "data: chunk1\n\n",
      "data: chunk2\n\n",
      "data: chunk3\n\n",
      "data: [DONE]\n\n",
    ]
    const bodyStream = new ReadableStream({
      async start(controller) {
        for (const chunk of chunks) {
          await new Promise((resolve) => setTimeout(resolve, 50))
          controller.enqueue(new TextEncoder().encode(chunk))
        }
        controller.close()
      },
    })
    return new Response(bodyStream, {
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
      },
    })
  },
})

console.log(`[fake-llm-provider] listening on http://127.0.0.1:${fakeLlmServer.port}`)

const server = Bun.serve({
  port,
  hostname: host,
  async fetch(req, srv) {
    if (!authorized(req)) {
      return new Response("unauthorized", { status: 401 })
    }
    const url = new URL(req.url)

    // WebSocket echo for reverse-proxy tests
    if (url.pathname === "/ws-echo") {
      if (srv.upgrade(req, { data: {} })) return undefined as never
      return new Response("upgrade_failed", { status: 400 })
    }

    if (url.pathname === "/env") {
      return Response.json({
        XDG_DATA_HOME: process.env.XDG_DATA_HOME,
        XDG_CONFIG_HOME: process.env.XDG_CONFIG_HOME,
        HOME: process.env.HOME,
        BASIC_USERNAME: username,
        FAKE_LLM_PORT: FAKE_LLM_PORT,
        DATAWORKS_CONTROL_PLANE_URL: process.env.DATAWORKS_CONTROL_PLANE_URL ?? null,
        DATAWORKS_WORKER_ID: process.env.DATAWORKS_WORKER_ID ?? null,
        // Do not echo the full worker token value into responses used by secret-absence tests.
        HAS_WORKER_TOKEN: Boolean(process.env.DATAWORKS_WORKER_TOKEN),
        HAS_PRIVATE_PATHS: Boolean(process.env.DWA_PRIVATE_PATHS),
      })
    }
    if (url.pathname === "/echo") {
      const body = await req.text().catch(() => "")
      return new Response(body, { status: 200 })
    }
    if (url.pathname === "/__llm-headers") {
      // Test endpoint to retrieve recorded fake LLM headers
      if (fakeLlmHeaders) {
        const headersObj: Record<string, string> = {}
        fakeLlmHeaders.forEach((v, k) => {
          headersObj[k] = v
        })
        return Response.json(headersObj)
      }
      return Response.json({})
    }
    if (url.pathname === "/__llm-providers") {
      // Return fake provider URL for testing
      return Response.json({
        fakeProviderUrl: `http://127.0.0.1:${fakeLlmServer.port}`,
      })
    }
    return new Response("not found", { status: 404 })
  },
  websocket: {
    open() {
      // ready
    },
    message(ws, message) {
      if (typeof message === "string") {
        ws.send(`echo:${message}`)
      } else {
        ws.send(message)
      }
    },
    close() {
      // ignore
    },
  },
})

console.log(`fake-opencode-worker listening on http://${server.hostname}:${server.port}`)
