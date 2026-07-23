import type { Database } from "../database"
import type { UserID } from "@dataworks-agent/core"
import type { SecretStore } from "../secret/store"
import { checkOrigin } from "./csrf"
import { authenticate } from "../auth/session"
import {
  createDataConnection,
  listDataConnections,
  getDataConnection,
  removeDataConnection,
} from "../data-connection/repo"

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

export async function handleDataConnectionsRoute(
  request: Request,
  db: Database,
  publicOrigin: string,
  secrets: SecretStore,
): Promise<Response> {
  const url = new URL(request.url)
  const segments = url.pathname.split("/").filter(Boolean)
  const id = segments.length >= 3 && segments[2] !== undefined ? segments[2] : null

  const auth = await requireUser(request, db, publicOrigin)
  if (auth.response || !auth.user) return auth.response ?? new Response(null, { status: 401 })
  const user = auth.user

  if (!id && request.method === "GET") return handleList(db, user.id)
  if (!id && request.method === "POST") return handleCreate(request, db, secrets, user.id)
  if (id && request.method === "GET") return handleGet(db, id, user.id)
  if (id && request.method === "DELETE") return await handleDelete(db, secrets, id, user.id)

  return new Response(null, { status: 405 })
}

function handleList(db: Database, userId: UserID): Response {
  const items = listDataConnections(db, userId)
  return jsonResponse(items)
}

function handleGet(db: Database, id: string, userId: UserID): Response {
  const info = getDataConnection(db, id, userId)
  if (!info) return new Response(null, { status: 404 })
  return jsonResponse(info)
}

async function handleCreate(
  request: Request,
  db: Database,
  secrets: SecretStore,
  userId: UserID,
): Promise<Response> {
  const raw = await request.json()
  if (!raw || typeof raw !== "object") return new Response(null, { status: 400 })
  const body = raw as Record<string, unknown>

  const name = typeof body.name === "string" ? body.name.trim() : ""
  const region = typeof body.region === "string" ? body.region.trim() : ""
  const accessKeyId = typeof body.accessKeyId === "string" ? body.accessKeyId : ""
  const accessKeySecret = typeof body.accessKeySecret === "string" ? body.accessKeySecret : ""
  const writeEnabled = body.writeEnabled === true

  if (!name || !region || !accessKeyId || !accessKeySecret) {
    return new Response(null, { status: 400 })
  }

  const created = await createDataConnection(db, secrets, {
    user_id: userId,
    name,
    region,
    access_key_id: accessKeyId,
    access_key_secret: accessKeySecret,
    write_enabled: writeEnabled,
  })

  return jsonResponse(created)
}

async function handleDelete(
  db: Database,
  secrets: SecretStore,
  id: string,
  userId: UserID,
): Promise<Response> {
  const removed = await removeDataConnection(db, secrets, id, userId)
  return new Response(null, { status: removed ? 204 : 404 })
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  })
}
