import { describe, expect, mock, test } from "bun:test"

mock.module("@solidjs/router", () => ({
  A: (props: { href?: string; children?: unknown }) => props.children,
  useNavigate: () => () => undefined,
  useParams: () => ({}),
  useLocation: () => ({ pathname: "/" }),
  useSearchParams: () => [{}, () => undefined],
}))

const { consolePageKey, shouldUseConsoleShell } = await import("./console-layout")

describe("dataworks console shell", () => {
  test("wraps chat and management routes but not login", () => {
    expect(shouldUseConsoleShell("/")).toBe(true)
    expect(shouldUseConsoleShell("/new-session")).toBe(true)
    expect(shouldUseConsoleShell("/dataworks/mcp")).toBe(true)
    expect(shouldUseConsoleShell("/login")).toBe(false)
  })

  test("derives the active page key", () => {
    expect(consolePageKey("/")).toBe("chat")
    expect(consolePageKey("/dataworks/jobs")).toBe("jobs")
    expect(consolePageKey("/settings")).toBe("settings")
  })
})
