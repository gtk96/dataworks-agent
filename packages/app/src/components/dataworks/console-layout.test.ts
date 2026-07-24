import { describe, expect, mock, test } from "bun:test"

mock.module("@solidjs/router", () => ({
  A: (props: { href?: string; children?: unknown }) => props.children,
  useNavigate: () => () => undefined,
  useParams: () => ({}),
  useLocation: () => ({ pathname: "/" }),
  useSearchParams: () => [{}, () => undefined],
}))

const { consolePageKey, consoleSurface, shouldUseConsoleShell } = await import("./console-layout")
const { resizeAgentWidth, resizeResourceWidth } = await import("@/pages/dataworks/workbench-state")

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

  test("classifies workbench, management, and unwrapped routes", () => {
    expect(consoleSurface("/")).toBe("workbench")
    expect(consoleSurface("/new-session")).toBe("workbench")
    expect(consoleSurface("/server/local/session/ses_1")).toBe("workbench")
    expect(consoleSurface("/dataworks/connections")).toBe("management")
    expect(consoleSurface("/login")).toBe("none")
  })

  test("resizes panels in sixteen pixel bounded steps", () => {
    expect(resizeResourceWidth(240, "ArrowRight")).toBe(256)
    expect(resizeResourceWidth(200, "ArrowLeft")).toBe(200)
    expect(resizeResourceWidth(240, "Home")).toBe(200)
    expect(resizeResourceWidth(240, "End")).toBe(360)
    expect(resizeAgentWidth(420, "ArrowLeft")).toBe(404)
    expect(resizeAgentWidth(600, "ArrowRight")).toBe(600)
    expect(resizeAgentWidth(420, "Home")).toBe(320)
    expect(resizeAgentWidth(420, "End")).toBe(600)
  })
})
