import { checkEgressPolicy } from "./egress"

export interface ProxyContext {
  workerUrl: string
  workerAuth: string
  publicOrigin: string
  allowedHostnames?: Set<string>
}

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
])

function stripHeaders(src: Headers): Headers {
  const out = new Headers()
  for (const [k, v] of src.entries()) {
    if (HOP_BY_HOP.has(k.toLowerCase())) continue
    if (["authorization", "cookie", "auth_token", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"].includes(k.toLowerCase())) continue
    out.set(k, v)
  }
  return out
}

/** Map control-plane `/opencode/*` path onto the worker root (strip `/opencode` prefix). */
export function workerPathname(pathname: string): string {
  if (pathname === "/opencode") return "/"
  if (pathname.startsWith("/opencode/")) {
    const rest = pathname.slice("/opencode".length)
    return rest.length === 0 ? "/" : rest
  }
  return pathname
}

export function workerTargetUrl(url: URL, ctx: ProxyContext): string {
  const target = new URL(ctx.workerUrl)
  const path = workerPathname(url.pathname)
  return target.toString().replace(/\/$/, "") + path + url.search
}

export function websocketTargetURL(httpUrl: string): string {
  const next = new URL(httpUrl)
  if (next.protocol === "http:") next.protocol = "ws:"
  if (next.protocol === "https:") next.protocol = "wss:"
  return next.toString()
}

export function websocketProtocols(input: Request | Headers | Record<string, string | undefined>): string[] {
  let value: string | null = null
  if (input instanceof Request) value = input.headers.get("sec-websocket-protocol")
  else if (input instanceof Headers) value = input.get("sec-websocket-protocol")
  else value = input["sec-websocket-protocol"] ?? null
  if (!value) return []
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
}

export async function proxyWorkerHttp(url: URL, method: string, req: Request, ctx: ProxyContext): Promise<Response> {
  const fullUrl = workerTargetUrl(url, ctx)
  const headers = stripHeaders(req.headers)
  headers.set("authorization", ctx.workerAuth)
  const init: RequestInit = { method, headers, body: req.body, redirect: "manual" }
  if (req.body) {
    ;(init as RequestInit & { duplex: string }).duplex = "half"
  }
  const upstream = await fetch(fullUrl, init)
  return new Response(upstream.body, { status: upstream.status, headers: stripHeaders(upstream.headers) })
}

export function handleEgressTest(req: Request, ctx: ProxyContext): Response {
  const target = req.headers.get("x-test-target")
  if (!target) return new Response("missing x-test-target", { status: 400 })
  const decision = checkEgressPolicy(target, ctx.allowedHostnames)
  if (!decision.allowed) {
    return new Response(`egress_denied: ${decision.reason ?? "unknown"}`, { status: 403 })
  }
  return new Response(`egress_allowed: ${target}`, { status: 200 })
}

export function isWebSocketUpgrade(req: Request): boolean {
  const upgrade = req.headers.get("upgrade")
  if (!upgrade || upgrade.toLowerCase() !== "websocket") return false
  const connection = req.headers.get("connection") ?? ""
  return connection.toLowerCase().includes("upgrade")
}
