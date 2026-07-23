import type { Database } from "../database"
import type { SecretStore } from "../secret/store"
import type { LlmConnection, AuthStrategy } from "@dataworks-agent/core"
import { PROVIDER_CATALOG } from "@dataworks-agent/core"
import { LlmConnectionRepo } from "../llm/repo"
import { authenticate } from "../auth/session"
import { checkOrigin } from "./csrf"

function rejectIfForbidden(request: Request, publicOrigin: string): Response | null {
  if (!checkOrigin(request, publicOrigin)) return new Response(null, { status: 403 })
  return null
}

async function requireUser(request: Request, db: Database, publicOrigin: string) {
  const forbidden = rejectIfForbidden(request, publicOrigin)
  if (forbidden) return { response: forbidden, user: null as null }
  const user = await authenticate(request, db)
  if (!user) return { response: new Response(null, { status: 401 }), user: null as null }
  return { response: null as null, user }
}

/** Public response strips secret_ref so browser clients never see vault pointers. */
function publicConnection(connection: LlmConnection.Info) {
  const { secret_ref: _secretRef, ...rest } = connection
  return rest
}

export async function handleLlmConnectionsRoute(
  request: Request,
  db: Database,
  publicOrigin: string,
  secrets: SecretStore,
): Promise<Response> {
  const url = new URL(request.url)
  const method = request.method

  const auth = await requireUser(request, db, publicOrigin)
  if (auth.response || !auth.user) return auth.response ?? new Response(null, { status: 401 })
  const user = auth.user
  const repo = new LlmConnectionRepo(db)

  // GET /api/llm-connections - list user's connections
  if (method === "GET" && url.pathname === "/api/llm-connections") {
    const items = repo.findByUserId(user.id).map(publicConnection)
    return new Response(JSON.stringify(items), {
      headers: { "content-type": "application/json" },
    })
  }

  // POST /api/llm-connections - create connection
  if (method === "POST" && url.pathname === "/api/llm-connections") {
    try {
      const body = (await request.json()) as {
        name?: string
        provider_id?: string
        upstream_origin?: string
        auth_strategy?: string
        secret?: string
        allowed_models?: string[]
        data_classification_allowlist?: string
      }
      const name = body.name
      const provider_id = body.provider_id
      const upstream_origin = body.upstream_origin
      const auth_strategy = body.auth_strategy
      const secret = body.secret
      const allowed_models = body.allowed_models
      const data_classification_allowlist = body.data_classification_allowlist

      if (!name || !provider_id || !upstream_origin || !auth_strategy || !secret) {
        return new Response(JSON.stringify({ error: "missing required fields" }), {
          status: 400,
          headers: { "content-type": "application/json" },
        })
      }

      const provider = PROVIDER_CATALOG[provider_id]
      if (!provider) {
        return new Response(JSON.stringify({ error: "unknown provider" }), {
          status: 400,
          headers: { "content-type": "application/json" },
        })
      }

      if (!provider.auth_strategy) {
        return new Response(
          JSON.stringify({ error: `Provider ${provider.name} not available in multi-user mode` }),
          { status: 400, headers: { "content-type": "application/json" } },
        )
      }

      if (provider.auth_strategy !== auth_strategy && auth_strategy !== "static_header") {
        return new Response(
          JSON.stringify({
            error: `Provider ${provider.name} requires ${provider.auth_strategy} auth strategy`,
          }),
          { status: 400, headers: { "content-type": "application/json" } },
        )
      }

      const secretRef = `llm-conn-${user.id}-${Date.now()}-${Math.random().toString(36).slice(2)}`
      await secrets.put(secretRef, {
        accessKeyId: provider_id,
        accessKeySecret: secret,
      })

      const connection = repo.create({
        user_id: user.id,
        provider_id,
        name,
        upstream_origin,
        auth_strategy: auth_strategy as AuthStrategy,
        secret_ref: secretRef,
        allowed_models: allowed_models ?? [],
        data_classification_allowlist: (data_classification_allowlist ?? "prompt_only") as LlmConnection.Info["data_classification_allowlist"],
      })

      return new Response(JSON.stringify(publicConnection(connection)), {
        status: 201,
        headers: { "content-type": "application/json" },
      })
    } catch (err) {
      console.error("llm-connection create error:", err)
      return new Response(JSON.stringify({ error: "invalid request" }), {
        status: 400,
        headers: { "content-type": "application/json" },
      })
    }
  }

  // GET / PATCH / DELETE /api/llm-connections/:id — ownership enforced
  const idMatch = url.pathname.match(/^\/api\/llm-connections\/([^/]+)$/)
  if (idMatch) {
    const id = idMatch[1]!
    const owned = repo.findById(id)
    if (!owned || owned.user_id !== user.id) {
      // Hide existence of other users' connections
      return new Response(null, { status: 404 })
    }

    if (method === "GET") {
      return new Response(JSON.stringify(publicConnection(owned)), {
        headers: { "content-type": "application/json" },
      })
    }

    if (method === "DELETE") {
      if (owned.secret_ref) {
        await secrets.delete(owned.secret_ref).catch(() => undefined)
      }
      const deleted = repo.delete(id)
      if (!deleted) return new Response(null, { status: 404 })
      return new Response(null, { status: 204 })
    }

    if (method === "PATCH") {
      try {
        const body = (await request.json()) as LlmConnection.UpdateInput
        // Never allow reassignment of user ownership via update body.
        const updated = repo.update(id, body)
        if (!updated || updated.user_id !== user.id) {
          return new Response(null, { status: 404 })
        }
        return new Response(JSON.stringify(publicConnection(updated)), {
          headers: { "content-type": "application/json" },
        })
      } catch {
        return new Response(JSON.stringify({ error: "invalid request" }), {
          status: 400,
          headers: { "content-type": "application/json" },
        })
      }
    }

    return new Response(null, { status: 405 })
  }

  return new Response(null, { status: 404 })
}
