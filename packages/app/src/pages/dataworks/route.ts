export const DATAWORKS_ROUTES = [
  "/dataworks/connections",
  "/dataworks/explorer",
  "/dataworks/jobs",
  "/dataworks/skills",
  "/dataworks/knowledge",
  "/dataworks/audit",
] as const

export type DataWorksRoute = (typeof DATAWORKS_ROUTES)[number]

export type DataWorksUser = {
  id: string
  email: string
  role: "admin" | "user" | string
}

export type AuthGateResult =
  | { status: "anonymous"; redirectTo: "/login" }
  | { status: "authenticated"; user: DataWorksUser }
  | { status: "forbidden"; reason: "audit_all_users" }

export type DataWorksConsoleKey =
  | "chat"
  | "connections"
  | "explorer"
  | "jobs"
  | "mcp"
  | "skills"
  | "knowledge"
  | "audit"
  | "settings"

export type DataWorksConsoleIcon =
  | "chat"
  | "connection"
  | "table"
  | "job"
  | "mcp"
  | "skill"
  | "knowledge"
  | "audit"
  | "settings"

export type DataWorksConsoleItem = {
  href: string
  key: DataWorksConsoleKey
  icon: DataWorksConsoleIcon
  match: (pathname: string) => boolean
}

const chatPath = (pathname: string) =>
  pathname === "/" ||
  pathname === "/new-session" ||
  pathname.includes("/session") ||
  pathname.startsWith("/server/")

export const DATAWORKS_CONSOLE_ITEMS = [
  { href: "/", key: "chat", icon: "chat", match: chatPath },
  { href: "/dataworks/connections", key: "connections", icon: "connection", match: (path) => path.startsWith("/dataworks/connections") },
  { href: "/dataworks/explorer", key: "explorer", icon: "table", match: (path) => path.startsWith("/dataworks/explorer") },
  { href: "/dataworks/jobs", key: "jobs", icon: "job", match: (path) => path.startsWith("/dataworks/jobs") },
  { href: "/dataworks/mcp", key: "mcp", icon: "mcp", match: (path) => path.startsWith("/dataworks/mcp") },
  { href: "/dataworks/skills", key: "skills", icon: "skill", match: (path) => path.startsWith("/dataworks/skills") },
  { href: "/dataworks/knowledge", key: "knowledge", icon: "knowledge", match: (path) => path.startsWith("/dataworks/knowledge") },
  { href: "/dataworks/audit", key: "audit", icon: "audit", match: (path) => path.startsWith("/dataworks/audit") },
  { href: "/settings", key: "settings", icon: "settings", match: (path) => path.startsWith("/settings") },
] as const satisfies readonly DataWorksConsoleItem[]

export function activeDataWorksNavItem(pathname: string): DataWorksConsoleItem {
  return DATAWORKS_CONSOLE_ITEMS.find((item) => item.match(pathname)) ?? DATAWORKS_CONSOLE_ITEMS[0]
}

export function isDataWorksProtectedPath(pathname: string): boolean {
  if (isLoginPath(pathname)) return false
  return DATAWORKS_CONSOLE_ITEMS.some((item) => item.match(pathname))
}

/** Paths that require a signed-in DataWorks control-plane session. */
export function isDataWorksPath(pathname: string): boolean {
  if (pathname === "/dataworks" || pathname.startsWith("/dataworks/")) return true
  return false
}

export function isLoginPath(pathname: string): boolean {
  return pathname === "/login" || pathname.startsWith("/login/")
}

/** OpenCode session/chat routes that must keep rendering under the same providers. */
export function isSessionPath(pathname: string): boolean {
  if (pathname === "/new-session") return true
  if (pathname.includes("/session")) return true
  if (pathname.startsWith("/server/")) return true
  return false
}

export function dataWorksNavItems(): ReadonlyArray<{ href: DataWorksRoute; key: string }> {
  return [
    { href: "/dataworks/connections", key: "connections" },
    { href: "/dataworks/explorer", key: "explorer" },
    { href: "/dataworks/jobs", key: "jobs" },
    { href: "/dataworks/skills", key: "skills" },
    { href: "/dataworks/knowledge", key: "knowledge" },
    { href: "/dataworks/audit", key: "audit" },
  ]
}

/**
 * Display order mirrors DATAWORKS_CONSOLE_ITEMS; MCP is included to keep the
 * on-page horizontal nav consistent with the persistent sidebar pending
 * plan-driven migration. Shell consumers should read DATAWORKS_CONSOLE_ITEMS.
 */

/**
 * Auth gate for DataWorks pages.
 * - No user → redirect to /login
 * - Non-admin requesting all-users audit → forbidden
 * - Otherwise authenticated
 */
export function resolveAuthGate(input: {
  user: DataWorksUser | null | undefined
  pathname: string
  searchParams?: URLSearchParams | Record<string, string | undefined>
}): AuthGateResult {
  if (!input.user) {
    return { status: "anonymous", redirectTo: "/login" }
  }

  if (input.pathname.startsWith("/dataworks/audit") && wantsAllUsers(input.searchParams)) {
    if (input.user.role !== "admin") {
      return { status: "forbidden", reason: "audit_all_users" }
    }
  }

  return { status: "authenticated", user: input.user }
}

export function wantsAllUsers(
  searchParams?: URLSearchParams | Record<string, string | undefined>,
): boolean {
  if (!searchParams) return false
  if (searchParams instanceof URLSearchParams) {
    const scope = searchParams.get("scope")
    const all = searchParams.get("allUsers")
    return scope === "all" || all === "1" || all === "true"
  }
  return searchParams.scope === "all" || searchParams.allUsers === "1" || searchParams.allUsers === "true"
}

/** Default post-login landing: chat-first home, not the classic connections console. */
export const LOGIN_DEFAULT_TARGET = "/" as const

export function loginRedirectTarget(returnTo?: string): string {
  if (!returnTo || !returnTo.startsWith("/") || returnTo.startsWith("//")) return LOGIN_DEFAULT_TARGET
  if (isLoginPath(returnTo)) return LOGIN_DEFAULT_TARGET
  return returnTo
}
