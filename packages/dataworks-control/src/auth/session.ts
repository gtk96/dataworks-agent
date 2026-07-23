import { createHash, randomBytes } from "crypto"
import type { Database } from "../database"
import {
  queryUserById,
  queryUserByEmail,
  querySessionByTokenHash,
  insertSession,
  deleteSessionByTokenHash,
  deleteExpiredSessions,
  queryRateLimit,
  upsertRateLimit,
  deleteRateLimit,
} from "../database"
import { hashPassword, verifyPassword } from "./password"
import { UserTable } from "../schema"
import type { UserID } from "@dataworks-agent/core"
import { UserID as UserIDUtil } from "@dataworks-agent/core"

const SESSION_TTL_MS = 12 * 60 * 60 * 1000

function base64urlEncode(buffer: Uint8Array): string {
  return Buffer.from(buffer).toString("base64url")
}

function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex")
}

export async function createUser(
  opts: { email: string; password: string; role: "admin" | "user" },
  db: Database,
): Promise<void> {
  const now = Date.now()
  const id = UserIDUtil.unsafe(crypto.randomUUID())
  const passwordHash = await hashPassword(opts.password)

  db._.insert(UserTable).values({
    id,
    email: opts.email,
    password_hash: passwordHash,
    role: opts.role,
    disabled: false,
    time_created: now,
    time_updated: now,
  }).run()
}

export async function authenticate(
  request: Request,
  db: Database,
): Promise<{ id: UserID; email: string; role: string } | null> {
  const cookieHeader = request.headers.get("cookie")
  if (!cookieHeader) return null

  const cookies = Object.fromEntries(
    cookieHeader.split(";").map((c) => c.trim().split("=").map(decodeURIComponent)),
  )
  const token = cookies["dwa_session"]
  if (!token) return null

  const tokenHash = hashToken(token)
  const now = Date.now()

  // GC expired sessions
  deleteExpiredSessions(db, now)

  const session = querySessionByTokenHash(db, tokenHash)
  if (!session) return null

  if (session.time_expires < now) return null

  const user = queryUserById(db, session.user_id)
  if (!user || user.disabled) return null

  return { id: user.id, email: user.email, role: user.role }
}

export async function login(
  db: Database,
  opts: { email: string; password: string },
): Promise<{ token: string; expires: number } | null> {
  const user = queryUserByEmail(db, opts.email)
  if (!user) return null
  if (user.disabled) return null

  const valid = await verifyPassword(user.password_hash, opts.password)
  if (!valid) return null

  const token = base64urlEncode(randomBytes(32))
  const tokenHash = hashToken(token)
  const now = Date.now()
  const expires = now + SESSION_TTL_MS

  insertSession(db, { token_hash: tokenHash, user_id: user.id, time_expires: expires, time_created: now })

  return { token, expires }
}

export async function logout(request: Request, db: Database): Promise<void> {
  const cookieHeader = request.headers.get("cookie")
  if (!cookieHeader) return

  const cookies = Object.fromEntries(
    cookieHeader.split(";").map((c) => c.trim().split("=").map(decodeURIComponent)),
  )
  const token = cookies["dwa_session"]
  if (!token) return

  const tokenHash = hashToken(token)
  deleteSessionByTokenHash(db, tokenHash)
}

export async function checkRateLimit(
  db: Database,
  ip: string,
  email: string,
): Promise<{ allowed: boolean; retryAfter: number }> {
  const WINDOW_MS = 15 * 60 * 1000
  const MAX_FAILURES = 5
  const now = Date.now()

  const record = queryRateLimit(db, ip, email)

  if (record) {
    if (now - record.first_failure > WINDOW_MS) {
      deleteRateLimit(db, ip, email)
    } else if (record.failure_count >= MAX_FAILURES) {
      const retryAfter = Math.ceil((record.first_failure + WINDOW_MS - now) / 1000)
      return { allowed: false, retryAfter }
    }
  }

  return { allowed: true, retryAfter: 0 }
}

export async function recordRateLimitFailure(db: Database, ip: string, email: string): Promise<void> {
  const now = Date.now()
  const record = queryRateLimit(db, ip, email)

  if (record) {
    upsertRateLimit(db, {
      ip_address: ip,
      email,
      failure_count: record.failure_count + 1,
      first_failure: record.first_failure,
    })
  } else {
    upsertRateLimit(db, {
      ip_address: ip,
      email,
      failure_count: 1,
      first_failure: now,
    })
  }
}
