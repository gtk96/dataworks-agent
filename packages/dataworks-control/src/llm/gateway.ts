import type { LlmConnection } from "@dataworks-agent/core"
import type { LlmConnectionRepo } from "./repo"
import type { SecretStore } from "../secret/store"
import { makeStaticHeaderInjector, makeQueryKeyInjector, makeAwsSigV4Injector, makeGcpOAuthInjector, makeOAuthBrokerInjector } from "./auth"
import { validateModel, validateContextPolicy, validateUpstreamRedirect, isUserContextApproved } from "./policy"

export class LlmGateway {
  constructor(
    private repo: LlmConnectionRepo,
    private secrets: SecretStore,
  ) {}

  async handleRequest(
    request: Request,
    connectionId: string,
    workerUserId: string,
  ): Promise<Response> {
    // 1. Find connection
    const connection = this.repo.findById(connectionId)
    if (!connection) {
      return new Response("connection not found", { status: 404 })
    }

    // 2. Validate connection belongs to this user
    if (connection.user_id !== workerUserId) {
      return new Response("forbidden", { status: 403 })
    }

    // 3. Check connection is enabled
    if (!connection.enabled) {
      return new Response("connection disabled", { status: 403 })
    }

    // 4. Parse request body to get model
    let model = "unknown"
    try {
      const clonedReq = request.clone()
      const body = await clonedReq.json() as { model?: string }
      model = body.model ?? "unknown"
    } catch {}

    // 5. Validate model allowlist
    if (!validateModel(model, connection)) {
      return new Response(`model "${model}" not allowed`, { status: 400 })
    }

    // 6. Check context policy
    const contextType = request.headers.get("x-dwa-context-type")
    const contextPolicy = validateContextPolicy(contextType, connection)
    if (!contextPolicy.allowed) {
      // For user_attached with approval, allow
      if (contextType === "user_attached" && isUserContextApproved(request.headers)) {
        // Approved - proceed
      } else {
        return new Response(contextPolicy.reason ?? "context policy denied", { status: 403 })
      }
    }

    // 7. Check for upstream redirect attempt
    const upstreamOverride = request.headers.get("x-dwa-upstream-override")
    if (upstreamOverride) {
      const redirectCheck = validateUpstreamRedirect(upstreamOverride, connection)
      if (!redirectCheck.allowed) {
        return new Response(`egress policy: ${redirectCheck.reason}`, { status: 403 })
      }
    }

    // 8. Get credential from secret store
    const credential = await this.secrets.ref(connection.secret_ref)
    if (!credential) {
      return new Response("credential not found", { status: 500 })
    }

    // 9. Build upstream URL (never from worker request, use connection config)
    const upstreamUrl = new URL(connection.upstream_origin)
    const pathMatch = request.url.match(/\/internal\/llm\/[^/]+\/(.*)$/)
    if (pathMatch) {
      upstreamUrl.pathname = "/" + pathMatch[1]
    }

    // 10. Strip hop-by-hop and worker-auth headers BEFORE credential injection
    //     so the injector output is not inadvertently erased.
    const cleanHeaders = new Headers(request.headers)
    cleanHeaders.delete("cookie")
    cleanHeaders.delete("authorization")  // Remove the worker/session token
    cleanHeaders.delete("x-forwarded-for")
    cleanHeaders.delete("x-real-ip")
    cleanHeaders.delete("x-api-key")
    // Strip DWA-internal headers that must not reach the upstream provider
    cleanHeaders.delete("x-dwa-context-type")
    cleanHeaders.delete("x-dwa-context-path")
    cleanHeaders.delete("x-dwa-context-approval")
    cleanHeaders.delete("x-dwa-upstream-override")
    const cleanRequest = new Request(request.url, {
      method: request.method,
      headers: cleanHeaders,
      body: request.body,
      // @ts-ignore -- Bun supports duplex on Request
      duplex: "half",
    })

    // 11. Inject credential based on auth strategy (operates on the cleaned request)
    let upstreamReq = cleanRequest
    switch (connection.auth_strategy) {
      case "static_header": {
        const injector = makeStaticHeaderInjector()
        upstreamReq = await injector({
          request: cleanRequest,
          upstream: upstreamUrl,
          credential: { secret: credential.accessKeySecret, headerScheme: "bearer" },
        })
        break
      }
      case "query_key": {
        const injector = makeQueryKeyInjector()
        upstreamReq = await injector({
          request: cleanRequest,
          upstream: upstreamUrl,
          credential: { secret: credential.accessKeySecret },
        })
        break
      }
      case "aws_sigv4": {
        const injector = makeAwsSigV4Injector()
        upstreamReq = await injector({
          request: cleanRequest,
          upstream: upstreamUrl,
          credential: { secret: credential.accessKeySecret, region: credential.accessKeyId },
        })
        break
      }
      case "gcp_oauth": {
        const injector = makeGcpOAuthInjector()
        upstreamReq = await injector({
          request: cleanRequest,
          upstream: upstreamUrl,
          credential: { secret: credential.accessKeySecret },
        })
        break
      }
      case "oauth_broker": {
        const injector = makeOAuthBrokerInjector()
        upstreamReq = await injector({
          request: cleanRequest,
          upstream: upstreamUrl,
          credential: { secret: credential.accessKeySecret },
        })
        break
      }
    }

    // 12. Stream the request to upstream (no buffering)
    //     upstreamReq.headers already contain the injected credential and
    //     are free of worker-auth / hop-by-hop headers (cleaned in step 10).
    const startTime = Date.now()
    try {
      const upstreamResponse = await fetch(upstreamUrl.toString(), {
        method: upstreamReq.method,
        headers: upstreamReq.headers,
        body: upstreamReq.body,
        signal: AbortSignal.timeout(10 * 60 * 1000), // 10 minute max
      })

      const duration = Date.now() - startTime
      // Log: connection_id, status, duration (no prompt/response bodies)
      console.log(`[llm-gateway] conn=${connectionId} status=${upstreamResponse.status} duration=${duration}ms`)

      // Stream response back (no buffering)
      return new Response(upstreamResponse.body, {
        status: upstreamResponse.status,
        headers: upstreamResponse.headers,
      })
    } catch (err) {
      console.error(`[llm-gateway] upstream error conn=${connectionId} err=${err}`)
      return new Response("upstream error", { status: 502 })
    }
  }
}
