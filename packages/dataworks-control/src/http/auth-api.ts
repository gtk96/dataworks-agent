import type { Database } from "../database"
import type { UserID } from "../../../dataworks-core/src/identity"
import { login, logout, checkRateLimit, recordRateLimitFailure, authenticate } from "../auth/session"
import { checkOrigin, getClientIP } from "./csrf"

const COOKIE_PATH = "/"
const COOKIE_SAMESITE = "Lax"

function buildSessionCookie(token: string, expires: number, isDev: boolean): string {
  const expiresDate = new Date(expires).toUTCString()
  let cookie = `dwa_session=${encodeURIComponent(token)}; Path=${COOKIE_PATH}; SameSite=${COOKIE_SAMESITE}; HttpOnly; Expires=${expiresDate}`
  if (!isDev) {
    cookie += "; Secure"
  }
  return cookie
}

function expireSessionCookie(isDev: boolean): string {
  let cookie = `dwa_session=; Path=${COOKIE_PATH}; SameSite=${COOKIE_SAMESITE}; HttpOnly; Expires=Thu, 01 Jan 1970 00:00:00 GMT`
  if (!isDev) {
    cookie += "; Secure"
  }
  return cookie
}

export async function handleLogin(
  request: Request,
  db: Database,
  publicOrigin: string,
  isDev = true,
): Promise<Response> {
  if (request.method !== "POST") {
    return new Response(null, { status: 405 })
  }

  if (!checkOrigin(request, publicOrigin)) {
    return new Response(null, { status: 403 })
  }

  const ip = getClientIP(request)
  let body: Record<string, unknown>
  try {
    body = (await request.json()) as Record<string, unknown>
  } catch {
    return new Response(null, { status: 400 })
  }

  const email = typeof body.email === "string" ? body.email : null
  const password = typeof body.password === "string" ? body.password : null
  if (!email || !password) {
    return new Response(null, { status: 400 })
  }

  const rateLimit = await checkRateLimit(db, ip, email)
  if (!rateLimit.allowed) {
    return new Response(null, {
      status: 429,
      headers: { "Retry-After": String(rateLimit.retryAfter) },
    })
  }

  const result = await login(db, { email, password })
  if (!result) {
    await recordRateLimitFailure(db, ip, email)
    return new Response(null, { status: 401 })
  }

  return new Response(null, {
    status: 204,
    headers: { "Set-Cookie": buildSessionCookie(result.token, result.expires, isDev) },
  })
}

export async function handleLogout(
  request: Request,
  db: Database,
  publicOrigin: string,
  isDev = true,
): Promise<Response> {
  if (request.method !== "POST") {
    return new Response(null, { status: 405 })
  }

  if (!checkOrigin(request, publicOrigin)) {
    return new Response(null, { status: 403 })
  }

  await logout(request, db)

  return new Response(null, {
    status: 204,
    headers: { "Set-Cookie": expireSessionCookie(isDev) },
  })
}

export async function handleMe(request: Request, db: Database, publicOrigin: string): Promise<Response> {
  if (!checkOrigin(request, publicOrigin)) {
    return new Response(null, { status: 403 })
  }

  const user = await authenticate(request, db)
  if (!user) {
    return new Response(null, { status: 401 })
  }

  return new Response(JSON.stringify({ id: user.id, email: user.email, role: user.role }), {
    status: 200,
    headers: { "content-type": "application/json" },
  })
}
