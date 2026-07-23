import type { UserID } from "@dataworks-agent/core"
import type { Database } from "../database"
import { checkOrigin } from "./csrf"
import { authenticate } from "../auth/session"
import { KnowledgeError, KnowledgeRepo } from "../knowledge/repo"
import { verifyWorkerToken } from "../worker/token"

function rejectIfForbidden(request: Request, publicOrigin: string): Response | null {
  if (!checkOrigin(request, publicOrigin)) return new Response(null, { status: 403 })
  return null
}

async function requireUser(request: Request, db: Database, publicOrigin: string) {
  const forbidden = rejectIfForbidden(request, publicOrigin)
  if (forbidden) return { response: forbidden, user: null }
  const user = await authenticate(request, db)
  if (!user) return { response: new Response(null, { status: 401 }), user: null }
  return { response: null, user }
}

export interface KnowledgeApiOptions {
  readonly appDataRoot: string
  readonly repo?: KnowledgeRepo
}

const repos = new WeakMap<Database, KnowledgeRepo>()

function getRepo(db: Database, opts: KnowledgeApiOptions): KnowledgeRepo {
  if (opts.repo) return opts.repo
  let repo = repos.get(db)
  if (!repo) {
    repo = new KnowledgeRepo({ db, appDataRoot: opts.appDataRoot, syncIngest: true })
    repos.set(db, repo)
  }
  return repo
}

export async function handleKnowledgeRoute(
  request: Request,
  db: Database,
  publicOrigin: string,
  opts: KnowledgeApiOptions,
): Promise<Response> {
  const url = new URL(request.url)
  const segments = url.pathname.split("/").filter(Boolean)
  // /api/knowledge/...
  const parts = segments[0] === "api" && segments[1] === "knowledge" ? segments.slice(2) : []

  const auth = await requireUser(request, db, publicOrigin)
  if (auth.response || !auth.user) return auth.response ?? new Response(null, { status: 401 })
  const user = auth.user
  const repo = getRepo(db, opts)

  try {
    // POST /api/knowledge/search
    if (parts[0] === "search" && request.method === "POST") {
      const body = (await request.json()) as {
        knowledgeBaseId?: string
        query?: string
        topK?: number
      }
      if (!body.knowledgeBaseId || !body.query) return json({ error: "knowledgeBaseId and query required" }, 400)
      const result = await repo.search({
        userId: user.id,
        knowledgeBaseId: body.knowledgeBaseId,
        query: body.query,
        ...(body.topK !== undefined ? { topK: body.topK } : {}),
      })
      return json(result)
    }

    // POST /api/knowledge/context
    if (parts[0] === "context" && request.method === "POST") {
      const body = (await request.json()) as {
        knowledgeBaseId?: string
        query?: string
        activeProvider?: string
        topK?: number
        maxTokens?: number
      }
      if (!body.knowledgeBaseId || !body.query || !body.activeProvider) {
        return json({ error: "knowledgeBaseId, query, activeProvider required" }, 400)
      }
      const ctx = await repo.buildContext({
        userId: user.id,
        knowledgeBaseId: body.knowledgeBaseId,
        query: body.query,
        activeProvider: body.activeProvider,
        ...(body.topK !== undefined ? { topK: body.topK } : {}),
        ...(body.maxTokens !== undefined ? { maxTokens: body.maxTokens } : {}),
      })
      if (!ctx.allowed) return json({ error: ctx.reason ?? "denied" }, 403)
      return json(ctx)
    }

    // /api/knowledge/bases
    if (parts[0] === "bases") {
      const kbId = parts[1]
      const sub = parts[2]
      const subId = parts[3]
      const action = parts[2]

      if (!kbId && request.method === "GET") {
        return json({ bases: repo.listBases(user.id) })
      }

      if (!kbId && request.method === "POST") {
        const body = (await request.json()) as {
          name?: string
          egressPolicy?: "local_only" | "approved_providers"
          approvedProviders?: string[]
        }
        if (!body.name?.trim()) return json({ error: "name required" }, 400)
        const base = repo.createBase({
          userId: user.id,
          name: body.name.trim(),
          ...(body.egressPolicy !== undefined ? { egressPolicy: body.egressPolicy } : {}),
          ...(body.approvedProviders !== undefined ? { approvedProviders: body.approvedProviders } : {}),
        })
        return json(base, 201)
      }

      if (kbId && !sub && request.method === "GET") {
        const base = repo.getBase(user.id, kbId)
        if (!base) return new Response(null, { status: 404 })
        return json(base)
      }

      if (kbId && !sub && request.method === "PATCH") {
        const body = (await request.json()) as {
          name?: string
          egressPolicy?: "local_only" | "approved_providers"
          approvedProviders?: string[]
          embeddingProvider?: "local" | "remote"
        }
        const base = repo.updateBase(user.id, kbId, body)
        return json(base)
      }

      if (kbId && action === "approve-provider" && request.method === "POST") {
        const body = (await request.json()) as { providerId?: string }
        if (!body.providerId) return json({ error: "providerId required" }, 400)
        const base = repo.approveProvider(user.id, kbId, body.providerId)
        return json(base)
      }

      if (kbId && sub === "documents" && !subId && request.method === "GET") {
        return json({ documents: repo.listDocuments(user.id, kbId) })
      }

      if (kbId && sub === "documents" && !subId && request.method === "POST") {
        const form = await request.formData()
        const file = form.get("file")
        if (!file || !(file instanceof File)) return json({ error: "file required" }, 400)
        const doc = await repo.uploadDocument({
          userId: user.id,
          knowledgeBaseId: kbId,
          filename: file.name,
          mimeType: file.type || null,
          stream: file,
        })
        return json(doc, 201)
      }

      if (kbId && sub === "documents" && subId && request.method === "GET") {
        const doc = repo.getDocument(user.id, kbId, subId)
        if (!doc) return new Response(null, { status: 404 })
        return json(doc)
      }

      if (kbId && sub === "documents" && subId && request.method === "DELETE") {
        const ok = repo.deleteDocument(user.id, kbId, subId)
        return new Response(null, { status: ok ? 204 : 404 })
      }

      if (kbId && sub === "reindex" && request.method === "POST") {
        // mark rebuild job; dry-run no-op success
        return json({ ok: true })
      }
    }

    return new Response(null, { status: 404 })
  } catch (error) {
    if (error instanceof KnowledgeError) {
      return json({ error: error.code, message: error.message }, error.status)
    }
    throw error
  }
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

/**
 * Worker-facing knowledge search (Bearer worker token, no browser cookie).
 * Tenant scope is taken from the verified token userID — never from the body.
 */
export async function handleInternalKnowledgeSearchRoute(
  request: Request,
  db: Database,
  workerTokenSecret: Uint8Array,
  opts: KnowledgeApiOptions,
): Promise<Response> {
  if (request.headers.has("cookie")) return new Response(null, { status: 403 })
  if (request.method !== "POST") return new Response(null, { status: 405 })
  const authorization = request.headers.get("authorization")
  const workerID = request.headers.get("x-dataworks-worker-id")
  if (!authorization?.startsWith("Bearer ") || !workerID) return new Response(null, { status: 401 })
  const worker = verifyWorkerToken(workerTokenSecret, authorization.slice(7), workerID)
  if (!worker) return new Response(null, { status: 401 })

  try {
    const body = (await request.json()) as {
      knowledgeBaseId?: string
      query?: string
      topK?: number
    }
    if (!body.knowledgeBaseId || !body.query) {
      return json({ error: "knowledgeBaseId and query required" }, 400)
    }
    const repo = getRepo(db, opts)
    const result = await repo.search({
      userId: worker.userID as UserID,
      knowledgeBaseId: body.knowledgeBaseId,
      query: body.query,
      ...(body.topK !== undefined ? { topK: body.topK } : {}),
    })
    return json(result)
  } catch (error) {
    if (error instanceof KnowledgeError) {
      return json({ error: error.code, message: error.message }, error.status)
    }
    throw error
  }
}
