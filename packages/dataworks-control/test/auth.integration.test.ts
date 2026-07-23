import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { makeTestServer } from "./support/server"

const app = makeTestServer()

beforeAll(() => app.start())
afterAll(() => app.stop())

describe("local auth", () => {
  test("logs in, resolves current user, and revokes logout", async () => {
    await app.createUser({ email: "admin@example.test", password: "correct-horse", role: "admin" })
    const login = await fetch(`${app.url}/api/auth/login`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "Origin": app.url,
      },
      body: JSON.stringify({ email: "admin@example.test", password: "correct-horse" }),
    })
    expect(login.status).toBe(204)
    const cookie = login.headers.get("set-cookie")!
    expect(cookie).toContain("dwa_session=")
    expect(cookie).toContain("HttpOnly")
    expect(cookie).toContain("SameSite=Lax")

    const me = await fetch(`${app.url}/api/auth/me`, {
      headers: {
        cookie,
        "Origin": app.url,
      },
    })
    expect(await me.json()).toMatchObject({ email: "admin@example.test", role: "admin" })

    const logout = await fetch(`${app.url}/api/auth/logout`, {
      method: "POST",
      headers: {
        cookie,
        "Origin": app.url,
      },
    })
    expect(logout.status).toBe(204)
    expect((await fetch(`${app.url}/api/auth/me`, { headers: { cookie, "Origin": app.url } })).status).toBe(401)
  })
})
