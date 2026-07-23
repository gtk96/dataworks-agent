import { createHash } from "crypto"
import type { Database } from "../database"
import type { SecretStore } from "../secret/store"
import { LlmConnectionRepo } from "../llm/repo"
import { LlmGateway } from "../llm/gateway"
import { BrowserSessionTable } from "../schema"
import { eq } from "drizzle-orm"

export async function handleLlmGatewayRoute(
  request: Request,
  db: Database,
  secrets: SecretStore,
): Promise<Response> {
  // Only accepts worker internal token (NOT browser cookie)
  const authHeader = request.headers.get("authorization")
  if (!authHeader || !authHeader.toLowerCase().startsWith("bearer ")) {
    return new Response(null, { status: 401 })
  }

  // Extract connection ID from URL: /internal/llm/:connectionID/*
  const url = new URL(request.url)
  const match = url.pathname.match(/^\/internal\/llm\/([^/]+)\/(.*)$/)
  if (!match) {
    return new Response(null, { status: 404 })
  }

  const connectionId = match[1]!

  // Validate worker token - check it's a valid session token hash
  const token = authHeader.slice(7)
  const tokenHash = createHash("sha256").update(token).digest("hex")
  const session = db._
    .select()
    .from(BrowserSessionTable)
    .where(eq(BrowserSessionTable.token_hash, tokenHash))
    .get()

  if (!session) {
    return new Response(null, { status: 401 })
  }

  const workerUserId = session.user_id

  // Create gateway and handle the request
  const repo = new LlmConnectionRepo(db)
  const gateway = new LlmGateway(repo, secrets)
  return gateway.handleRequest(request, connectionId, workerUserId)
}
