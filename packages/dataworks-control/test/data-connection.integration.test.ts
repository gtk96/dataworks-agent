import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { makeTestServer } from "./support/server"

const app = makeTestServer()

beforeAll(async () => {
  await app.start()
  await app.createUser({ email: "owner@example.test", password: "correct-horse", role: "user" })
  await app.createUser({ email: "other@example.test", password: "correct-horse", role: "user" })

  const ownerLogin = await fetch(`${app.url}/api/auth/login`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "Origin": app.url,
    },
    body: JSON.stringify({ email: "owner@example.test", password: "correct-horse" }),
  })
  app.ownerCookie = ownerLogin.headers.get("set-cookie")!

  const otherLogin = await fetch(`${app.url}/api/auth/login`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "Origin": app.url,
    },
    body: JSON.stringify({ email: "other@example.test", password: "correct-horse" }),
  })
  app.otherCookie = otherLogin.headers.get("set-cookie")!
})

afterAll(() => app.stop())

describe("data connections API", () => {
  test("CRUD hides secret material and respects user scoping", async () => {
    const created = await fetch(`${app.url}/api/data-connections`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "Origin": app.url,
        cookie: app.ownerCookie,
      },
      body: JSON.stringify({
        name: "staging",
        region: "cn-hangzhou",
        accessKeyId: "LTAI_TEST_1234",
        accessKeySecret: "secret-value",
        writeEnabled: false,
      }),
    })
    expect(created.status).toBe(200)
    const createdJson = (await created.json()) as { id: string; accessKeyDisplay: string; writeEnabled: boolean }
    expect(createdJson).toMatchObject({ name: "staging", accessKeyDisplay: "LTAI_T***1234", writeEnabled: false })
    expect(JSON.stringify(createdJson)).not.toContain("secret-value")
    expect(JSON.stringify(createdJson)).not.toContain("accessKeySecret")

    const list = await fetch(`${app.url}/api/data-connections`, {
      headers: { cookie: app.ownerCookie, "Origin": app.url },
    })
    expect(list.status).toBe(200)
    const listJson = (await list.json()) as { name: string }[]
    expect(listJson.length).toBe(1)
    expect(listJson[0]!.name).toBe("staging")
    expect(JSON.stringify(listJson)).not.toContain("secret-value")

    const otherList = await fetch(`${app.url}/api/data-connections`, {
      headers: { cookie: app.otherCookie, "Origin": app.url },
    })
    expect(otherList.status).toBe(200)
    const otherListJson = (await otherList.json()) as unknown[]
    expect(otherListJson.length).toBe(0)

    const got = await fetch(`${app.url}/api/data-connections/${createdJson.id}`, {
      headers: { cookie: app.ownerCookie, "Origin": app.url },
    })
    expect(got.status).toBe(200)
    const gotJson = (await got.json()) as Record<string, unknown>
    expect(JSON.stringify(gotJson)).not.toContain("secret-value")

    const otherGet = await fetch(`${app.url}/api/data-connections/${createdJson.id}`, {
      headers: { cookie: app.otherCookie, "Origin": app.url },
    })
    expect(otherGet.status).toBe(404)

    const deleted = await fetch(`${app.url}/api/data-connections/${createdJson.id}`, {
      method: "DELETE",
      headers: { cookie: app.ownerCookie, "Origin": app.url },
    })
    expect(deleted.status).toBe(204)

    const afterDelete = await fetch(`${app.url}/api/data-connections/${createdJson.id}`, {
      headers: { cookie: app.ownerCookie, "Origin": app.url },
    })
    expect(afterDelete.status).toBe(404)
  })
})
