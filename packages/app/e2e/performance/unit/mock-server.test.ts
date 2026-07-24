import { expect, test } from "bun:test"
import type { Page, Route } from "@playwright/test"
import { mockDataWorksRequest, mockDataWorksServer, mockOpenCodeServer } from "../../utils/mock-server"

test("installs standalone DataWorks control-plane routes", async () => {
  let handler: ((route: Route) => Promise<void>) | undefined
  const responses: Array<{ body: unknown; status?: number }> = []
  const page = {
    route: (url: string, callback: (route: Route) => Promise<void>) => {
      expect(url).toBe("**/api/**")
      handler = callback
      return Promise.resolve()
    },
  } as unknown as Page

  await mockDataWorksServer(page, { user: null })
  await handler!({
    request: () => ({ method: () => "GET", url: () => "http://127.0.0.1:3000/api/auth/me" }),
    fulfill: (response: { body?: string; status?: number }) => {
      responses.push({ body: JSON.parse(response.body ?? "null"), status: response.status })
      return Promise.resolve()
    },
  } as unknown as Route)

  expect(responses).toEqual([{ body: { error: "unauthorized" }, status: 401 }])
})

test("handles shared DataWorks control-plane routes", async () => {
  const responses: Array<{ body: unknown; status?: number }> = []
  const route = (url: string, method = "GET") =>
    ({
      request: () => ({ method: () => method, url: () => url }),
      fulfill: (response: { body?: string; status?: number }) => {
        responses.push({ body: JSON.parse(response.body ?? "null"), status: response.status })
        return Promise.resolve()
      },
    }) as unknown as Route

  const auth = mockDataWorksRequest(route("http://127.0.0.1:3000/api/auth/me"))
  const connections = mockDataWorksRequest(route("http://127.0.0.1:3000/api/data-connections"))
  expect(auth).toBeInstanceOf(Promise)
  expect(connections).toBeInstanceOf(Promise)
  expect(mockDataWorksRequest(route("http://127.0.0.1:4096/session"))).toBeUndefined()
  expect(mockDataWorksRequest(route("http://127.0.0.1:4096/api/auth/me"))).toBeUndefined()
  expect(mockDataWorksRequest(route("http://127.0.0.1:3000/api/data-connections", "POST"))).toBeUndefined()
  const unauthorized = mockDataWorksRequest(route("http://127.0.0.1:3000/api/auth/me"), { user: null })
  expect(unauthorized).toBeInstanceOf(Promise)
  await Promise.all([auth, connections])
  expect(responses).toEqual([
    { body: { id: "e2e-user", email: "e2e@example.test", role: "admin" }, status: 200 },
    { body: [], status: 200 },
    { body: { error: "unauthorized" }, status: 401 },
  ])
})

test("applies message latency after a list response gate is released", async () => {
  const events: string[] = []
  const gate = Promise.withResolvers<void>()
  let handler: ((route: Route) => Promise<void>) | undefined
  const page = {
    route: (_url: string, callback: (route: Route) => Promise<void>) => {
      handler = callback
      return Promise.resolve()
    },
  } as unknown as Page
  await mockOpenCodeServer(page, {
    provider: {},
    directory: "C:/OpenCode",
    project: {},
    sessions: [{ id: "session" }],
    messageDelay: 25,
    beforeMessagesResponse: () => {
      events.push("before")
      return gate.promise
    },
    onMessages: (request) => events.push(request.phase),
    pageMessages: () => {
      events.push("page")
      return { items: [] }
    },
  })

  const response = handler!({
    request: () => ({ url: () => "http://127.0.0.1:4096/session/session/message" }),
    fulfill: () => {
      events.push("fulfill")
      return Promise.resolve()
    },
  } as unknown as Route)
  expect(events).toEqual(["start", "before"])

  const released = performance.now()
  gate.resolve()
  await response
  expect(performance.now() - released).toBeGreaterThanOrEqual(20)
  expect(events).toEqual(["start", "before", "page", "end", "fulfill"])
})
