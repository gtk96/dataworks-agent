import { mkdirSync, rmSync } from "fs"
import { join } from "path"
import { randomUUID } from "crypto"
import { createUser } from "../../src/auth/session"
import { makeDatabase } from "../../src/database"
import type { Database } from "../../src/database"
import { makeSecretStore, SecretStore } from "../../src/secret/store"

export function makeTestServer() {
  const tmpDir = join(import.meta.dir, "..", ".tmp")
  mkdirSync(tmpDir, { recursive: true })
  const dbPath = join(tmpDir, `test-${randomUUID()}.sqlite`)
  const secretsRoot = join(tmpDir, `secrets-${randomUUID()}`)
  const migrationsDir = join(import.meta.dir, "..", "..", "migration")
  const masterKey = new Uint8Array(32).fill(11)

  let server: ReturnType<typeof Bun.serve>
  let db: Database
  let secrets: Awaited<ReturnType<typeof makeSecretStore>>
  let actualUrl = ""

  const srv = {
    ownerCookie: "",
    otherCookie: "",

    get url() {
      return actualUrl
    },

    async start() {
      db = await makeDatabase({ dbPath, migrationsDir })
      secrets = await makeSecretStore({ root: secretsRoot, masterKey })

      server = Bun.serve({
        port: 0,
        async fetch(req) {
          const url = new URL(req.url)
          const publicOrigin = `http://localhost:${server.port}`

          const origin = req.headers.get("origin")
          if (origin && origin !== publicOrigin) {
            return new Response(null, { status: 403 })
          }

          const secFetchSite = req.headers.get("sec-fetch-site")
          if (!origin && secFetchSite && secFetchSite !== "same-origin" && secFetchSite !== "none") {
            return new Response(null, { status: 403 })
          }

          if (url.pathname === "/api/auth/login" && req.method === "POST") {
            const { handleLogin } = await import("../../src/http/auth-api")
            return handleLogin(req, db, publicOrigin)
          }

          if (url.pathname === "/api/auth/logout" && req.method === "POST") {
            const { handleLogout } = await import("../../src/http/auth-api")
            return handleLogout(req, db, publicOrigin)
          }

          if (url.pathname === "/api/auth/me" && req.method === "GET") {
            const { handleMe } = await import("../../src/http/auth-api")
            return handleMe(req, db, publicOrigin)
          }

          if (url.pathname.startsWith("/api/data-connections")) {
            const { handleDataConnectionsRoute } = await import("../../src/http/data-connection-api")
            return handleDataConnectionsRoute(req, db, publicOrigin, secrets)
          }

          return new Response(null, { status: 404 })
        },
      })

      actualUrl = `http://localhost:${server.port}`
    },

    stop() {
      server?.stop()
      try {
        rmSync(dbPath)
      } catch {}
      try {
        rmSync(secretsRoot, { recursive: true, force: true })
      } catch {}
    },

    async createUser(opts: { email: string; password: string; role: "admin" | "user" }) {
      await createUser(opts, db)
    },
  }

  return srv
}
