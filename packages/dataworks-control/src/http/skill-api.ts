import type { Database } from "../database"
import { checkOrigin } from "./csrf"
import { authenticate } from "../auth/session"
import { SkillRepo } from "../skill/repo"
import { SkillParseError } from "@dataworks-agent/core"

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

export interface SkillApiOptions {
  readonly appDataRoot: string
}

export async function handleSkillsRoute(
  request: Request,
  db: Database,
  publicOrigin: string,
  opts: SkillApiOptions,
): Promise<Response> {
  const url = new URL(request.url)
  const segments = url.pathname.split("/").filter(Boolean)
  const afterApi = segments.slice(1)
  const scope = afterApi[0] === "skills" ? afterApi[1] : undefined
  const isSystemPath = scope === "system"
  const name = isSystemPath ? afterApi[2] : scope && scope !== "system" ? scope : undefined

  const auth = await requireUser(request, db, publicOrigin)
  if (auth.response || !auth.user) return auth.response ?? new Response(null, { status: 401 })
  const user = auth.user
  const repo = new SkillRepo({ appDataRoot: opts.appDataRoot })

  if (!name && request.method === "GET") {
    const all = repo.listAll(user.id)
    return jsonResponse({
      system: all.system.map(publicSkill),
      user: all.user.map(publicSkill),
      roots: repo.discoveryRoots(user.id),
    })
  }

  if (name && request.method === "GET") {
    if (isSystemPath) {
      const skill = repo.listAll(user.id).system.find((s) => s.name === name)
      if (!skill) return new Response(null, { status: 404 })
      return jsonResponse(publicSkill(skill))
    }
    const skill = repo.get(user.id, name)
    if (!skill) return new Response(null, { status: 404 })
    return jsonResponse(publicSkill(skill))
  }

  if (name && request.method === "PUT") {
    if (isSystemPath) {
      if (user.role !== "admin") return new Response(null, { status: 403 })
      try {
        const body = await readMarkdownBody(request)
        const skill = repo.writeSystem({ name, markdown: body })
        return jsonResponse(publicSkill(skill))
      } catch (error) {
        return skillErrorResponse(error)
      }
    }
    try {
      const body = await readMarkdownBody(request)
      const skill = repo.writeUser(user.id, { name, markdown: body })
      return jsonResponse(publicSkill(skill))
    } catch (error) {
      return skillErrorResponse(error)
    }
  }

  if (name && request.method === "DELETE") {
    if (isSystemPath) {
      if (user.role !== "admin") return new Response(null, { status: 403 })
      const removed = repo.removeSystem(name)
      return new Response(null, { status: removed ? 204 : 404 })
    }
    const removed = repo.removeUser(user.id, name)
    return new Response(null, { status: removed ? 204 : 404 })
  }

  if (!name && request.method === "POST") {
    try {
      const raw = await request.json()
      if (!raw || typeof raw !== "object") return new Response(null, { status: 400 })
      const body = raw as Record<string, unknown>
      const skillName = typeof body.name === "string" ? body.name.trim() : ""
      const markdown = typeof body.markdown === "string" ? body.markdown : ""
      if (!skillName || !markdown) return new Response(null, { status: 400 })
      const skill = repo.writeUser(user.id, { name: skillName, markdown })
      return new Response(JSON.stringify(publicSkill(skill)), {
        status: 201,
        headers: { "content-type": "application/json" },
      })
    } catch (error) {
      return skillErrorResponse(error)
    }
  }

  return new Response(null, { status: 405 })
}

function publicSkill(skill: {
  name: string
  description?: string
  triggers: readonly string[]
  allowed_tools: readonly string[]
  forbidden_tools: readonly string[]
  max_tool_calls_per_session: number
  write_enabled: boolean
  location: string
  content: string
  scope: "system" | "user"
}) {
  return {
    name: skill.name,
    description: skill.description,
    triggers: skill.triggers,
    allowedTools: skill.allowed_tools,
    forbiddenTools: skill.forbidden_tools,
    maxToolCallsPerSession: skill.max_tool_calls_per_session,
    writeEnabled: skill.write_enabled,
    location: skill.location,
    content: skill.content,
    scope: skill.scope,
  }
}

async function readMarkdownBody(request: Request): Promise<string> {
  const ctype = request.headers.get("content-type") ?? ""
  if (ctype.includes("application/json")) {
    const raw = await request.json()
    if (!raw || typeof raw !== "object") throw new SkillParseError("schema", "body required")
    const markdown = (raw as { markdown?: unknown }).markdown
    if (typeof markdown !== "string") throw new SkillParseError("schema", "markdown required")
    return markdown
  }
  return await request.text()
}

function skillErrorResponse(error: unknown): Response {
  if (error instanceof SkillParseError) {
    const status = error.code === "too_large" ? 413 : 400
    return new Response(JSON.stringify({ error: error.code, message: error.message }), {
      status,
      headers: { "content-type": "application/json" },
    })
  }
  if (error instanceof Error && error.message === "invalid_user_id") {
    return new Response(null, { status: 400 })
  }
  return new Response(null, { status: 500 })
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  })
}
