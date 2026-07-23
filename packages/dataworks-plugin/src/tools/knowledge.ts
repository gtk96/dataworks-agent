import { tool } from "@opencode-ai/plugin"
import { formatSearchToolOutput } from "../rag-context.js"

/**
 * Explicit user-directed knowledge search tool.
 * Control-plane performs tenant-filtered retrieval via worker token.
 */
export const dw_knowledge_search = tool({
  description:
    "Search the user's private knowledge base for relevant document chunks. Returns cited excerpts only; never absolute filesystem paths.",
  args: {
    knowledgeBaseId: tool.schema.string().describe("Knowledge base ID"),
    query: tool.schema.string().describe("Natural language or keyword query"),
    topK: tool.schema.number().int().min(1).max(20).default(5).describe("Max chunks to return"),
  },
  async execute(args, ctx) {
    await ctx.ask({
      permission: "dw_query",
      patterns: [args.knowledgeBaseId],
      always: [],
      metadata: { tool: "dw_knowledge_search" },
    })

    const hits = await searchKnowledge(
      {
        knowledgeBaseId: args.knowledgeBaseId,
        query: args.query,
        topK: args.topK,
      },
      ctx.abort,
    )

    return {
      title: "knowledge search",
      output: formatSearchToolOutput(hits),
      metadata: { count: hits.length },
    }
  },
})

export type KnowledgeSearchHitRow = {
  documentId: string
  knowledgeBaseId: string
  filename: string
  text: string
  startOffset: number
  endOffset: number
  score: number
  citation: string
}

/**
 * Tenant-scoped knowledge search via worker internal API (preferred) or
 * cookie-backed public URL fallback. Returns [] when control plane is missing
 * or request fails (non-fatal for callers such as RAG system transform).
 */
export async function searchKnowledge(
  input: { knowledgeBaseId: string; query: string; topK: number },
  signal?: AbortSignal,
): Promise<KnowledgeSearchHitRow[]> {
  const body = {
    knowledgeBaseId: input.knowledgeBaseId,
    query: input.query,
    topK: input.topK,
  }

  // Preferred: worker-authenticated internal search (no browser cookie).
  const baseUrl = process.env.DATAWORKS_CONTROL_PLANE_URL
  const workerToken = process.env.DATAWORKS_WORKER_TOKEN
  const workerID = process.env.DATAWORKS_WORKER_ID
  if (baseUrl && workerToken && workerID) {
    const url = new URL("/internal/knowledge/search", baseUrl)
    const response = await fetch(url.toString(), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${workerToken}`,
        "x-dataworks-worker-id": workerID,
      },
      body: JSON.stringify(body),
      signal,
    })
    if (response.ok) {
      const data = (await response.json()) as { results?: unknown }
      if (Array.isArray(data.results)) return data.results as KnowledgeSearchHitRow[]
    }
  }

  // Fallback for dry-run / tests that inject a cookie-backed public URL.
  const searchUrl = process.env.DATAWORKS_KNOWLEDGE_SEARCH_URL
  if (searchUrl) {
    const response = await fetch(searchUrl, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(process.env.DATAWORKS_SESSION_COOKIE
          ? { cookie: process.env.DATAWORKS_SESSION_COOKIE }
          : {}),
        ...(process.env.DATAWORKS_PUBLIC_ORIGIN
          ? { origin: process.env.DATAWORKS_PUBLIC_ORIGIN }
          : {}),
      },
      body: JSON.stringify(body),
      signal,
    })
    if (response.ok) {
      const data = (await response.json()) as { results?: unknown }
      if (Array.isArray(data.results)) return data.results as KnowledgeSearchHitRow[]
    }
  }

  return []
}
