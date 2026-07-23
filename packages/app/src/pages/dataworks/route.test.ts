import { describe, expect, test } from "bun:test"
import {
  activeDataWorksNavItem,
  DATAWORKS_CONSOLE_ITEMS,
  isDataWorksPath,
  isDataWorksProtectedPath,
  isLoginPath,
  isSessionPath,
  loginRedirectTarget,
  resolveAuthGate,
  wantsAllUsers,
} from "./route"

test("exposes the approved nine-item console navigation", () => {
  expect(DATAWORKS_CONSOLE_ITEMS.map((item) => [item.key, item.href])).toEqual([
    ["chat", "/"],
    ["connections", "/dataworks/connections"],
    ["explorer", "/dataworks/explorer"],
    ["jobs", "/dataworks/jobs"],
    ["mcp", "/dataworks/mcp"],
    ["skills", "/dataworks/skills"],
    ["knowledge", "/dataworks/knowledge"],
    ["audit", "/dataworks/audit"],
    ["settings", "/settings"],
  ])
})

test("matches chat, management, and settings paths", () => {
  expect(activeDataWorksNavItem("/").key).toBe("chat")
  expect(activeDataWorksNavItem("/new-session").key).toBe("chat")
  expect(activeDataWorksNavItem("/server/local/session/ses_1").key).toBe("chat")
  expect(activeDataWorksNavItem("/dataworks/mcp").key).toBe("mcp")
  expect(activeDataWorksNavItem("/settings").key).toBe("settings")
  expect(isDataWorksProtectedPath("/")).toBe(true)
  expect(isDataWorksProtectedPath("/login")).toBe(false)
})

describe("dataworks routes", () => {
  test("classifies dataworks, login, and session paths", () => {
    expect(isDataWorksPath("/dataworks")).toBe(true)
    expect(isDataWorksPath("/dataworks/connections")).toBe(true)
    expect(isDataWorksPath("/session")).toBe(false)
    expect(isLoginPath("/login")).toBe(true)
    expect(isLoginPath("/login/")).toBe(true)
    expect(isLoginPath("/dataworks")).toBe(false)
    expect(isSessionPath("/new-session")).toBe(true)
    expect(isSessionPath("/abc/session/sess_1")).toBe(true)
    expect(isSessionPath("/server/key/session/sess_1")).toBe(true)
    expect(isSessionPath("/dataworks/explorer")).toBe(false)
  })
})

describe("dataworks auth gate", () => {
  const admin = { id: "u-admin", email: "admin@example.com", role: "admin" as const }
  const user = { id: "u-user", email: "user@example.com", role: "user" as const }

  test("anonymous users are redirected to /login", () => {
    expect(resolveAuthGate({ user: null, pathname: "/dataworks/connections" })).toEqual({
      status: "anonymous",
      redirectTo: "/login",
    })
    expect(resolveAuthGate({ user: undefined, pathname: "/dataworks/audit" })).toEqual({
      status: "anonymous",
      redirectTo: "/login",
    })
  })

  test("authenticated users see the shell", () => {
    expect(resolveAuthGate({ user, pathname: "/dataworks/connections" })).toEqual({
      status: "authenticated",
      user,
    })
    expect(resolveAuthGate({ user: admin, pathname: "/dataworks/explorer" })).toEqual({
      status: "authenticated",
      user: admin,
    })
  })

  test("non-admin users cannot open audit-all-users view", () => {
    expect(
      resolveAuthGate({
        user,
        pathname: "/dataworks/audit",
        searchParams: { scope: "all" },
      }),
    ).toEqual({ status: "forbidden", reason: "audit_all_users" })

    expect(
      resolveAuthGate({
        user,
        pathname: "/dataworks/audit",
        searchParams: new URLSearchParams("allUsers=1"),
      }),
    ).toEqual({ status: "forbidden", reason: "audit_all_users" })

    expect(
      resolveAuthGate({
        user: admin,
        pathname: "/dataworks/audit",
        searchParams: { scope: "all" },
      }),
    ).toEqual({ status: "authenticated", user: admin })

    expect(
      resolveAuthGate({
        user,
        pathname: "/dataworks/audit",
      }),
    ).toEqual({ status: "authenticated", user })
  })

  test("session and chat routes remain classified under the same provider shell", () => {
    // Session/chat paths are not DataWorks-gated; they keep rendering via AppInterface providers.
    expect(isSessionPath("/new-session")).toBe(true)
    expect(isDataWorksPath("/new-session")).toBe(false)
    expect(resolveAuthGate({ user: null, pathname: "/new-session" }).status).toBe("anonymous")
    // Gate only applies when DataWorks pages call it; session routes do not redirect via this helper.
    expect(isSessionPath("/L1VzZXJzL3Byb2plY3Q/session/sess_1")).toBe(true)
  })

  test("wantsAllUsers and login redirect helpers", () => {
    expect(wantsAllUsers({ scope: "all" })).toBe(true)
    expect(wantsAllUsers({ allUsers: "true" })).toBe(true)
    expect(wantsAllUsers({})).toBe(false)
    expect(loginRedirectTarget("/dataworks/jobs")).toBe("/dataworks/jobs")
    expect(loginRedirectTarget("https://evil.example")).toBe("/")
    expect(loginRedirectTarget("/login")).toBe("/")
    expect(loginRedirectTarget(undefined)).toBe("/")
  })
})
