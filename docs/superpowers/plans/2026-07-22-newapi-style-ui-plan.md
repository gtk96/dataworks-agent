# DataWorks Agent New API-Style UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unfinished marketing-style DataWorks chat surface with a New API-inspired console that keeps chat primary, exposes a persistent nine-item sidebar including MCP, and renders SQL output as a compact operational data card.

**Architecture:** Keep the existing OpenCode SolidJS provider/session stack and DataWorks control-plane pages. Introduce a route-aware `DataWorksConsoleLayout` at the new-layout root, make `/` an authenticated DataWorks dashboard that starts OpenCode draft sessions, keep actual draft/session routes inside the same shell, and reuse the existing `DataWorksShell` only as an auth/content gate for management pages. Share connection/project selection through `DataWorksProvider`, and consume the existing OpenCode MCP status/toggle APIs rather than adding a second MCP backend.

**Tech Stack:** SolidJS 1.9, `@solidjs/router`, OpenCode v2 UI components/Tailwind CSS 4, Bun test, TypeScript native preview (`tsgo`), Playwright, existing DataWorks control-plane APIs and OpenCode MCP SDK.

## Global Constraints

- Target repository and branch: `E:\dataworks_agent`, `chat-first-ui`; do not switch to `E:\dw-agent`.
- Preserve all existing uncommitted work; do not reset, checkout over, or delete unrelated changes.
- Visual direction is inspired by New API only: persistent sidebar, white content panels, compact controls, light gray canvas, blue active/action color; do not copy New API code, branding, or assets.
- Sidebar order is exactly: Chat, Connections, Explorer, Jobs, MCP, Skills, Knowledge, Audit, Settings.
- Keep login default target `/`; protect the chat dashboard and DataWorks management routes with the existing control-plane cookie session.
- Do not add a separate MCP control-plane API in P0. The MCP page consumes `serverSync().child(directory)[0].mcp` and `serverSync().mcp.toggle(directory, name)`.
- Reuse the OpenCode prompt/session submission path; do not introduce a parallel chat API or duplicate message store.
- DataWorks context belongs to `DataWorksProvider`; never write credentials, tokens, or raw connection secrets to browser storage.
- User-facing copy added by this plan must exist in both `packages/app/src/i18n/en.ts` and `packages/app/src/i18n/zh.ts`.
- Use Bun tests and run tests/typechecks from package directories; never run the guarded repository-root test command.
- Follow `AGENTS.md`: avoid `any`, import aliases, star imports, unnecessary helpers, and unnecessary `else` branches.
- Every code task follows TDD: first observe the specified failure, then implement only enough to pass.
- The approved design is `docs/superpowers/specs/2026-07-22-newapi-style-ui-design.md`.
- This plan lists suggested commits for normal execution, but do not actually commit unless the user explicitly authorizes commits.

---

## File Structure Map

### Route and navigation contract

- Modify `packages/app/src/pages/dataworks/route.ts` — canonical console route metadata, nine-item sidebar order, auth-path classification, active-item selection.
- Modify `packages/app/src/pages/dataworks/route.test.ts` — pure tests for route order, chat path, MCP path, active matching, and login redirect.
- Modify `packages/app/src/app.tsx` — lazy routes for the dashboard/MCP page and route registration under existing providers.

### Shared console shell

- Create `packages/app/src/components/dataworks/console-layout.tsx` — route-aware New API-style shell: fixed sidebar, compact topbar, mobile drawer, logout, settings-dialog action.
- Create `packages/app/src/components/dataworks/console-layout.css` — shell tokens, responsive layout, focus states, compact panels and controls.
- Create `packages/app/src/components/dataworks/console-layout.test.ts` — pure navigation/title/mobile-policy tests exported by the shell module.
- Modify `packages/app/src/pages/layout-new.tsx` — render `DataWorksConsoleLayout` once around all new-layout content; remove duplicate DataWorks top nav.
- Modify `packages/app/src/pages/dataworks/shell.tsx` — remove its duplicate header/nav; retain auth gate, forbidden state, scrollable content frame, and login form.
- Modify `packages/app/src/styles/dataworks-theme.css` — consolidate DataWorks tokens and management-page primitives; remove obsolete hero styles.

### Dashboard, scope, and draft entry

- Create `packages/app/src/components/dataworks/query-scope.tsx` — shared connection/project/mode selector with explicit project state and selected project ID.
- Create `packages/app/src/components/dataworks/query-scope.test.ts` — pure project-key/label/selection-state tests.
- Create `packages/app/src/pages/dataworks/dashboard.tsx` — authenticated `/` console dashboard with four status cards, query composer launch, and four quick actions.
- Create `packages/app/src/pages/dataworks/dashboard.test.ts` — pure query readiness and query-handoff tests.
- Modify `packages/app/src/pages/new-session.tsx` — replace `DataWorksChatHero` with compact scope strip + existing `PromptInputV2Composer`; consume query handoff and preserve project/worktree controls.
- Modify `packages/app/src/components/session/session-header.tsx` — show compact scope strip within active sessions without duplicating shell navigation.
- Delete `packages/app/src/components/dataworks/chat-hero.tsx` — obsolete marketing-style hero and duplicate scope implementation.
- Delete `packages/app/src/components/dataworks/chat-hero.css` — obsolete gradients/hero styling.
- Modify `packages/app/src/components/dataworks/scope-bar.tsx` — reduce to a thin wrapper around `QueryScope` for session headers.
- Modify `packages/app/src/components/dataworks/scope-bar.css` — compact square/rounded-6 controls; no pill/glass styling.

### MCP management

- Create `packages/app/src/pages/dataworks/mcp.tsx` — MCP list/status/toggle page backed by the active OpenCode directory context.
- Create `packages/app/src/pages/dataworks/mcp.test.ts` — pure status-summary/tone tests.
- Modify `packages/app/src/i18n/en.ts` — sidebar/dashboard/MCP/session copy.
- Modify `packages/app/src/i18n/zh.ts` — matching Chinese copy.

### SQL results

- Modify `packages/session-ui/src/components/sql-result.ts` — localized, structured view helpers and bounded displayed-row behavior.
- Modify `packages/session-ui/src/components/sql-result.test.ts` — structured/TSV/empty/long/copy tests.
- Modify `packages/session-ui/src/components/sql-result-card.tsx` — collapsible SQL, compact toolbar, copy SQL/TSV, bounded table, empty/truncated states.
- Modify `packages/session-ui/src/components/sql-result-card.css` — New API-like square card/table styling; remove pills and gradients.
- Modify `packages/session-ui/src/components/message-part.tsx` — keep `dw_run_sql` registry integration and pass localized labels to the result card.
- Modify `packages/ui/src/i18n/en.ts` and `packages/ui/src/i18n/zh.ts` — SQL result action/status labels used by `UiI18n`.

### Verification

- Create `packages/app/e2e/dataworks-console.spec.ts` — login → dashboard → sidebar → query handoff smoke flow using dry-run fixtures.
- Modify `packages/app/src/pages/dataworks/route.test.ts` and the focused tests listed above.
- Update `docs/superpowers/specs/2026-07-22-newapi-style-ui-design.md` status from approved design to implemented only after all verification passes.

---

### Task 1: Lock the nine-route console contract

**Files:**
- Modify: `packages/app/src/pages/dataworks/route.ts`
- Modify: `packages/app/src/pages/dataworks/route.test.ts`
- Modify: `packages/app/src/i18n/en.ts`
- Modify: `packages/app/src/i18n/zh.ts`

**Interfaces:**
- Consumes: `DataWorksUser`, `resolveAuthGate`, and existing management URLs.
- Produces:
  - `DATAWORKS_CONSOLE_ITEMS: readonly DataWorksConsoleItem[]`
  - `DataWorksConsoleItem = { href: string; key: DataWorksConsoleKey; icon: DataWorksConsoleIcon; match(pathname: string): boolean }`
  - `activeDataWorksNavItem(pathname: string): DataWorksConsoleItem`
  - `isDataWorksProtectedPath(pathname: string): boolean`
  - `LOGIN_DEFAULT_TARGET = "/"`

- [ ] **Step 1: Replace the old six-route expectation with the approved navigation contract test**

In `packages/app/src/pages/dataworks/route.test.ts`, add/replace the route test with:

```ts
import {
  DATAWORKS_CONSOLE_ITEMS,
  activeDataWorksNavItem,
  isDataWorksProtectedPath,
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
```

Keep the existing auth and safe-return tests, and update the old “six workspace routes” assertion to use the new constant.

- [ ] **Step 2: Run the focused route test and observe the contract failure**

Run from `packages/app`:

```bash
bun test src/pages/dataworks/route.test.ts
```

Expected: FAIL because `DATAWORKS_CONSOLE_ITEMS`, `activeDataWorksNavItem`, and `isDataWorksProtectedPath` do not exist.

- [ ] **Step 3: Implement the route metadata and matching rules**

In `packages/app/src/pages/dataworks/route.ts`, define:

```ts
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
  pathname === "/" || pathname === "/new-session" || pathname.includes("/session") || pathname.startsWith("/server/")

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
```

Make `dataWorksNavItems()` return the management subset only if legacy callers still require it; new shell code must consume `DATAWORKS_CONSOLE_ITEMS`.

- [ ] **Step 4: Add exact English and Chinese navigation copy**

Add these keys to `packages/app/src/i18n/en.ts`:

```ts
"dataworks.nav.chat": "Chat",
"dataworks.nav.mcp": "MCP",
"dataworks.nav.settings": "Settings",
"dataworks.shell.console": "Console",
```

Add matching keys to `packages/app/src/i18n/zh.ts`:

```ts
"dataworks.nav.chat": "对话",
"dataworks.nav.mcp": "MCP",
"dataworks.nav.settings": "设置",
"dataworks.shell.console": "控制台",
```

Keep existing route copy for connections/explorer/jobs/skills/knowledge/audit.

- [ ] **Step 5: Run tests and app typecheck**

Run from `packages/app`:

```bash
bun test src/pages/dataworks/route.test.ts
bun typecheck
```

Expected: route tests PASS; typecheck exits 0.

- [ ] **Step 6: Commit checkpoint (only with explicit user authorization)**

```bash
git add packages/app/src/pages/dataworks/route.ts packages/app/src/pages/dataworks/route.test.ts packages/app/src/i18n/en.ts packages/app/src/i18n/zh.ts
git commit -m "feat(app): define dataworks console navigation"
```

---

### Task 2: Build the New API-style console shell

**Files:**
- Create: `packages/app/src/components/dataworks/console-layout.tsx`
- Create: `packages/app/src/components/dataworks/console-layout.css`
- Create: `packages/app/src/components/dataworks/console-layout.test.ts`
- Modify: `packages/app/src/pages/layout-new.tsx`
- Modify: `packages/app/src/pages/dataworks/shell.tsx`
- Modify: `packages/app/src/styles/dataworks-theme.css`

**Interfaces:**
- Consumes: `DATAWORKS_CONSOLE_ITEMS`, `activeDataWorksNavItem`, `useDataWorks()`, `useSettingsDialog()`, router location/navigation, `Titlebar`.
- Produces:
  - `DataWorksConsoleLayout(props: ParentProps): JSX.Element`
  - `consolePageTitle(pathname: string, t: Translator): string`
  - `shouldUseConsoleShell(pathname: string): boolean`
  - DOM anchors: `[data-component="dataworks-console"]`, `[data-slot="console-sidebar"]`, `[data-slot="console-topbar"]`, `[data-slot="console-content"]`.

- [ ] **Step 1: Write pure shell policy tests**

Create `packages/app/src/components/dataworks/console-layout.test.ts`:

```ts
import { describe, expect, test } from "bun:test"
import { consolePageKey, shouldUseConsoleShell } from "./console-layout"

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
```

- [ ] **Step 2: Run the focused test and observe failure**

Run from `packages/app`:

```bash
bun test src/components/dataworks/console-layout.test.ts
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the shell component**

Create `packages/app/src/components/dataworks/console-layout.tsx`. It must:

- Export `shouldUseConsoleShell(pathname)` using `isDataWorksProtectedPath`.
- Export `consolePageKey(pathname)` using `activeDataWorksNavItem`.
- Render children unchanged for `/login`.
- On protected paths, wait for `dataworks.user()`; redirect anonymous users to `/login?returnTo=...` once bootstrap resolves.
- Render a 220px desktop sidebar, 56px topbar, and scroll-safe content body.
- Render all nine items in exact approved order.
- Treat `settings` as an action: call `useSettingsDialog()` instead of navigating to a nonexistent settings route; still set the button label/icon in the same sidebar position.
- Add a mobile menu button that toggles a sidebar drawer and closes after navigation.
- Put the product mark/name at the top and current user/logout at the bottom.

Use the existing UI icon system rather than Unicode glyphs. The navigation body should have this structural shape:

```tsx
<div data-component="dataworks-console" data-mobile-open={mobileOpen()}>
  <aside data-slot="console-sidebar">
    <A href="/" data-slot="console-brand">...</A>
    <nav aria-label={language.t("dataworks.shell.nav")}>...</nav>
    <div data-slot="console-account">...</div>
  </aside>
  <section data-slot="console-main">
    <header data-slot="console-topbar">...</header>
    <main data-slot="console-content">{props.children}</main>
  </section>
</div>
```

- [ ] **Step 4: Implement exact compact visual tokens**

Create `packages/app/src/components/dataworks/console-layout.css` with:

```css
[data-component="dataworks-console"] {
  --dwa-sidebar-width: 220px;
  --dwa-topbar-height: 56px;
  display: grid;
  grid-template-columns: var(--dwa-sidebar-width) minmax(0, 1fr);
  width: 100%;
  height: 100%;
  min-height: 0;
  background: #f7f8fa;
}

[data-slot="console-sidebar"] {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #fff;
  border-right: 1px solid #e8eaef;
}

[data-slot="console-topbar"] {
  height: var(--dwa-topbar-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  background: #fff;
  border-bottom: 1px solid #e8eaef;
}

[data-slot="console-content"] {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  padding: 16px 18px 20px;
}

[data-slot="console-nav-item"] {
  min-height: 36px;
  border-radius: 8px;
  color: #4b5563;
}

[data-slot="console-nav-item"][data-active="true"] {
  color: #1d4ed8;
  background: #eff6ff;
}

@media (max-width: 760px) {
  [data-component="dataworks-console"] { grid-template-columns: 1fr; }
  [data-slot="console-sidebar"] { position: fixed; inset: 0 auto 0 0; width: min(280px, 86vw); transform: translateX(-100%); z-index: 40; }
  [data-component="dataworks-console"][data-mobile-open="true"] [data-slot="console-sidebar"] { transform: translateX(0); }
  [data-slot="console-content"] { padding: 12px; }
}
```

Use CSS variables from `dataworks-theme.css` for dark mode equivalents; do not add gradients, glass blur, pill navigation, or large shadows.

- [ ] **Step 5: Install the shell once in `NewLayout` and remove duplicate nav**

In `packages/app/src/pages/layout-new.tsx`:

- Import `DataWorksConsoleLayout`.
- Keep the existing `Titlebar`, debug bar, toast region, and suspense behavior.
- Delete the existing `dataworks-layout-nav` horizontal link strip.
- Wrap only the `<main>` content area:

```tsx
<main class="flex-1 min-h-0 min-w-0 overflow-hidden flex flex-col items-start contain-strict">
  <Suspense>
    <DataWorksConsoleLayout>{props.children}</DataWorksConsoleLayout>
  </Suspense>
</main>
```

- [ ] **Step 6: Reduce `DataWorksShell` to auth/content responsibilities**

In `packages/app/src/pages/dataworks/shell.tsx`:

- Remove the current duplicate header/nav/logout block.
- Preserve auth redirect, forbidden audit state, `WriteConfirmationHost`, and `ListStateBanner`.
- Render authenticated children inside:

```tsx
<div data-component="dataworks-page" class="w-full min-h-full">
  {props.children}
  <WriteConfirmationHost />
</div>
```

- Keep `LoginPage` outside the console shell and retain the approved username/password wording.

- [ ] **Step 7: Consolidate theme primitives**

In `packages/app/src/styles/dataworks-theme.css`:

- Define `--dwa-primary: #2563eb`, `--dwa-page: #f7f8fa`, `--dwa-surface: #fff`, `--dwa-border: #e5e7eb`, success/warning/danger colors, and dark-mode overrides.
- Keep `.dwa-card` at 10px radius and subtle/no shadow.
- Add `.dwa-page-head`, `.dwa-panel`, `.dwa-toolbar`, `.dwa-field`, and `.dwa-status-tag` primitives for later management-page convergence.
- Delete the old `.dwa-chat-hero*` block.

- [ ] **Step 8: Run focused tests and typecheck**

Run from `packages/app`:

```bash
bun test src/components/dataworks/console-layout.test.ts src/pages/dataworks/route.test.ts
bun typecheck
```

Expected: tests PASS; typecheck exits 0.

- [ ] **Step 9: Commit checkpoint (only with explicit user authorization)**

```bash
git add packages/app/src/components/dataworks/console-layout.tsx packages/app/src/components/dataworks/console-layout.css packages/app/src/components/dataworks/console-layout.test.ts packages/app/src/pages/layout-new.tsx packages/app/src/pages/dataworks/shell.tsx packages/app/src/styles/dataworks-theme.css
git commit -m "feat(app): add dataworks console shell"
```

---

### Task 3: Create one shared connection/project query scope

**Files:**
- Create: `packages/app/src/components/dataworks/query-scope.tsx`
- Create: `packages/app/src/components/dataworks/query-scope.test.ts`
- Modify: `packages/app/src/context/dataworks.tsx`
- Modify: `packages/app/src/components/dataworks/scope-bar.tsx`
- Modify: `packages/app/src/components/dataworks/scope-bar.css`
- Modify: `packages/app/src/components/dataworks/connection-selector.tsx`

**Interfaces:**
- Consumes: `DataConnection`, `DataWorksProject`, `useDataWorks().listProjects()`.
- Produces:
  - DataWorks context signals `projects`, `projectState`, `selectedProjectID`, `selectedProject`, `setSelectedProjectID`, `refreshProjects`.
  - `projectKey(project: DataWorksProject): string`
  - `projectLabel(project: DataWorksProject): string`
  - `QueryScope(props: { compact?: boolean; showMode?: boolean; class?: string }): JSX.Element`
  - `DataWorksScopeBar` as a compatibility wrapper for active session headers.

- [ ] **Step 1: Write pure project identity tests**

Create `packages/app/src/components/dataworks/query-scope.test.ts`:

```ts
import { describe, expect, test } from "bun:test"
import { projectKey, projectLabel } from "./query-scope"

describe("dataworks query scope", () => {
  test("normalizes project identity and display", () => {
    expect(projectKey({ projectId: 7, projectName: "经营分析" })).toBe("7")
    expect(projectLabel({ projectId: 7, projectName: "经营分析" })).toBe("经营分析 (7)")
    expect(projectLabel({ projectId: "p1" })).toBe("p1")
  })
})
```

- [ ] **Step 2: Run the focused test and observe failure**

Run from `packages/app`:

```bash
bun test src/components/dataworks/query-scope.test.ts
```

Expected: FAIL because `query-scope.tsx` does not exist.

- [ ] **Step 3: Move project selection state into `DataWorksProvider`**

In `packages/app/src/context/dataworks.tsx`, add:

```ts
const [projects, setProjects] = createSignal<DataWorksProject[]>([])
const [projectState, setProjectState] = createSignal<ListState>("idle")
const [selectedProjectID, setSelectedProjectID] = createSignal<string | undefined>()
const selectedProject = createMemo(() =>
  projects().find((project) => String(project.projectId) === selectedProjectID()),
)
```

Implement `refreshProjects()`:

```ts
async function refreshProjects() {
  const connectionID = selectedConnectionID()
  if (!connectionID) {
    setProjects([])
    setSelectedProjectID(undefined)
    setProjectState("empty")
    return
  }
  setProjectState("loading")
  const result = await listProjects(connectionID, selectedConnection()?.region)
  if (!result.ok) {
    setProjects([])
    setSelectedProjectID(undefined)
    setProjectState(result.status === 429 ? "rate_limit" : "error")
    return result
  }
  setProjects(result.data)
  setProjectState(result.data.length ? "ready" : "empty")
  const current = selectedProjectID()
  if (!current || !result.data.some((project) => String(project.projectId) === current)) {
    setSelectedProjectID(result.data[0] ? String(result.data[0].projectId) : undefined)
  }
  return result
}
```

Call it when the selected connection changes after connections are loaded. Reset it during logout. Return every new signal/action from the context.

- [ ] **Step 4: Implement `QueryScope`**

Create `packages/app/src/components/dataworks/query-scope.tsx` with exported `projectKey` and `projectLabel`, then render:

- Existing `ConnectionSelector`.
- Project `<select>` bound to `selectedProjectID`.
- Optional read/write mode field derived from `selectedConnection()?.writeEnabled`.
- Inline loading/empty/error text using `ListState`.
- A management link to `/dataworks/connections` in non-compact mode.

The compact mode is one row and must use real labels (not uppercase microtext). The standard mode uses three grid columns above 760px and one column below.

- [ ] **Step 5: Make existing scope components wrappers, not duplicates**

Replace `packages/app/src/components/dataworks/scope-bar.tsx` with:

```tsx
import { QueryScope } from "@/components/dataworks/query-scope"

export function DataWorksScopeBar(props: { class?: string }) {
  return <QueryScope compact class={props.class} />
}
```

Rewrite `scope-bar.css` so compact fields use 6px radii, 32px controls, `#fff` background, and `#e5e7eb` borders. Remove pill, backdrop-filter, translucent surface, translated hover, and duplicated suggestions styles.

Update `ConnectionSelector` so its label can be hidden with `compact?: boolean`; retain its controlled change callback.

- [ ] **Step 6: Run focused tests and typecheck**

Run from `packages/app`:

```bash
bun test src/components/dataworks/query-scope.test.ts
bun typecheck
```

Expected: test PASS; typecheck exits 0.

- [ ] **Step 7: Commit checkpoint (only with explicit user authorization)**

```bash
git add packages/app/src/context/dataworks.tsx packages/app/src/components/dataworks/query-scope.tsx packages/app/src/components/dataworks/query-scope.test.ts packages/app/src/components/dataworks/scope-bar.tsx packages/app/src/components/dataworks/scope-bar.css packages/app/src/components/dataworks/connection-selector.tsx
git commit -m "feat(app): share dataworks query scope"
```

---

### Task 4: Build the chat-first console dashboard

**Files:**
- Create: `packages/app/src/pages/dataworks/dashboard.tsx`
- Create: `packages/app/src/pages/dataworks/dashboard.css`
- Create: `packages/app/src/pages/dataworks/dashboard.test.ts`
- Modify: `packages/app/src/app.tsx`
- Modify: `packages/app/src/i18n/en.ts`
- Modify: `packages/app/src/i18n/zh.ts`

**Interfaces:**
- Consumes: `QueryScope`, DataWorks selected connection/project, `useTabs().newDraft`, selected/fallback OpenCode server and project directory.
- Produces:
  - `queryDashboardState(input): { ready: boolean; reason?: "connection" | "project" | "prompt" }`
  - `quickActionPrompt(key: QuickActionKey): string`
  - `DataWorksDashboard` as the authenticated `/` route.
  - Query handoff via `tabs.newDraft({ server, directory }, prompt)`; no storage side channel.

- [ ] **Step 1: Write dashboard state and quick-action tests**

Create `packages/app/src/pages/dataworks/dashboard.test.ts`:

```ts
import { describe, expect, test } from "bun:test"
import { queryDashboardState, quickActionPrompt } from "./dashboard"

describe("dataworks dashboard", () => {
  test("requires connection, project, and prompt", () => {
    expect(queryDashboardState({ connectionID: undefined, projectID: undefined, prompt: "查表" })).toEqual({ ready: false, reason: "connection" })
    expect(queryDashboardState({ connectionID: "c1", projectID: undefined, prompt: "查表" })).toEqual({ ready: false, reason: "project" })
    expect(queryDashboardState({ connectionID: "c1", projectID: "7", prompt: " " })).toEqual({ ready: false, reason: "prompt" })
    expect(queryDashboardState({ connectionID: "c1", projectID: "7", prompt: "查表" })).toEqual({ ready: true })
  })

  test("uses actionable quick prompts", () => {
    expect(quickActionPrompt("tables")).toContain("业务表")
    expect(quickActionPrompt("jobs")).toContain("失败")
    expect(quickActionPrompt("orders")).toContain("订单")
    expect(quickActionPrompt("ping")).toContain("SELECT 1")
  })
})
```

- [ ] **Step 2: Run the focused test and observe failure**

Run from `packages/app`:

```bash
bun test src/pages/dataworks/dashboard.test.ts
```

Expected: FAIL because dashboard exports do not exist.

- [ ] **Step 3: Implement the dashboard view model and page**

Create `packages/app/src/pages/dataworks/dashboard.tsx` with:

- `queryDashboardState` exactly prioritizing missing connection → project → prompt.
- Four exact quick actions: `tables`, `jobs`, `orders`, `ping`.
- Four status cards: selected connection, selected project, today queries (`--` in P0), write permission.
- A white `开始查询`/`Start query` panel containing `QueryScope`, a native `<textarea>`, inline reason text, and primary send button.
- A 2×2 quick-action grid; clicking fills the textarea and focuses it, never auto-sends.
- Send path resolves the current OpenCode server/project from existing layout/global providers and calls:

```ts
await tabs.newDraft(
  { server: ServerConnection.key(connection), directory: project.worktree },
  prompt().trim(),
)
```

If no OpenCode project exists, show the existing project-open action rather than fabricating a directory.

- [ ] **Step 4: Add exact dashboard copy**

Add English keys:

```ts
"dataworks.dashboard.title": "Chat",
"dataworks.dashboard.newChat": "New chat",
"dataworks.dashboard.history": "History",
"dataworks.dashboard.currentConnection": "Current connection",
"dataworks.dashboard.currentProject": "Current project",
"dataworks.dashboard.todayQueries": "Queries today",
"dataworks.dashboard.writePermission": "Write access",
"dataworks.dashboard.start": "Start query",
"dataworks.dashboard.placeholder": "Ask about your data or enter SQL…",
"dataworks.dashboard.missingConnection": "Select a connection first.",
"dataworks.dashboard.missingProject": "Select a project first.",
"dataworks.dashboard.missingPrompt": "Enter a question or SQL.",
"dataworks.dashboard.quick": "Quick actions",
```

Add matching Chinese:

```ts
"dataworks.dashboard.title": "对话",
"dataworks.dashboard.newChat": "新建对话",
"dataworks.dashboard.history": "历史记录",
"dataworks.dashboard.currentConnection": "当前连接",
"dataworks.dashboard.currentProject": "当前项目",
"dataworks.dashboard.todayQueries": "今日查询",
"dataworks.dashboard.writePermission": "写权限",
"dataworks.dashboard.start": "开始查询",
"dataworks.dashboard.placeholder": "输入自然语言或 SQL，例如：查找物流成本异常订单…",
"dataworks.dashboard.missingConnection": "请先选择连接。",
"dataworks.dashboard.missingProject": "请先选择项目。",
"dataworks.dashboard.missingPrompt": "请输入问题或 SQL。",
"dataworks.dashboard.quick": "常用操作",
```

- [ ] **Step 5: Route `/` to the dashboard**

In `packages/app/src/app.tsx`:

- Add `const DataWorksDashboard = lazy(() => import("@/pages/dataworks/dashboard"))`.
- Under new layout, replace `<Route path="/" component={NewHome} />` with `<Route path="/" component={DataWorksDashboard} />`.
- Keep `LegacyHome` for old-layout mode.
- Remove `NewHome` from the import only if no other use remains.

- [ ] **Step 6: Implement compact New API-style dashboard CSS**

Create `packages/app/src/pages/dataworks/dashboard.css` using:

- Content max-width `1120px`; no centered hero.
- Status cards grid `repeat(4, minmax(0, 1fr))`, collapsing to two and one columns.
- White panels, 1px border, 10px radius, 12–16px padding.
- 36px primary button and 88px minimum textarea.
- Quick-action cards with border-color/background hover only; no translate or glow.

- [ ] **Step 7: Run dashboard and route tests plus typecheck**

Run from `packages/app`:

```bash
bun test src/pages/dataworks/dashboard.test.ts src/pages/dataworks/route.test.ts
bun typecheck
```

Expected: tests PASS; typecheck exits 0.

- [ ] **Step 8: Commit checkpoint (only with explicit user authorization)**

```bash
git add packages/app/src/pages/dataworks/dashboard.tsx packages/app/src/pages/dataworks/dashboard.css packages/app/src/pages/dataworks/dashboard.test.ts packages/app/src/app.tsx packages/app/src/i18n/en.ts packages/app/src/i18n/zh.ts
git commit -m "feat(app): add dataworks chat dashboard"
```

---

### Task 5: Replace the unfinished hero in draft and session views

**Files:**
- Modify: `packages/app/src/pages/new-session.tsx`
- Modify: `packages/app/src/components/session/session-header.tsx`
- Delete: `packages/app/src/components/dataworks/chat-hero.tsx`
- Delete: `packages/app/src/components/dataworks/chat-hero.css`
- Modify: `packages/app/src/components/dataworks/scope-bar.tsx`
- Modify: `packages/app/src/components/dataworks/scope-bar.css`

**Interfaces:**
- Consumes: `PromptInputV2Composer`, `QueryScope`, prompt prefill already handled by `searchParams.prompt`/draft memory, project/worktree controls.
- Produces: compact draft surface and compact session scope row; no `DataWorksChatHero` references.

- [ ] **Step 1: Add a source-level regression test for removed hero references**

Create `packages/app/src/pages/dataworks/hero-removal.test.ts`:

```ts
import { expect, test } from "bun:test"

const newSession = await Bun.file(new URL("../new-session.tsx", import.meta.url)).text()
const sessionHeader = await Bun.file(new URL("../../components/session/session-header.tsx", import.meta.url)).text()

test("draft and session surfaces no longer use the marketing hero", () => {
  expect(newSession).not.toContain("DataWorksChatHero")
  expect(newSession).not.toContain("dwa-hero")
  expect(sessionHeader).toContain("DataWorksScopeBar")
})
```

- [ ] **Step 2: Run the regression test and observe failure**

Run from `packages/app`:

```bash
bun test src/pages/dataworks/hero-removal.test.ts
```

Expected: FAIL because `new-session.tsx` still imports/renders `DataWorksChatHero` and `dwa-hero` classes.

- [ ] **Step 3: Replace the hero with a compact draft panel**

In `packages/app/src/pages/new-session.tsx`:

- Remove `DataWorksChatHero` and hero CSS imports.
- Keep `PromptInputV2Composer`, project selector/add button, workspace selector, status tip, and existing controller/submission wiring.
- Replace lines around the current malformed hero JSX with:

```tsx
<div class={`${NEW_SESSION_CONTENT_WIDTH} mx-auto w-full px-4 py-5`}>
  <div class="dwa-panel flex flex-col gap-3 p-4">
    <div class="flex items-center justify-between gap-3">
      <div>
        <div class="text-14-medium text-v2-text-text-base">{language.t("dataworks.dashboard.start")}</div>
        <div class="text-12-regular text-v2-text-text-muted">{language.t("dataworks.chat.hero.hint")}</div>
      </div>
    </div>
    <DataWorksScopeBar />
    <PromptInputV2Composer controller={promptInputV2Controller} />
  </div>
  {/* existing project/worktree controls, structurally balanced */}
</div>
```

Remove the stray indentation and `/*</Show>*/` marker. Ensure every `<Show>` has a clear matching close.

- [ ] **Step 4: Keep session scope compact and non-duplicative**

In `session-header.tsx`, keep one `DataWorksScopeBar` row under the titlebar only when the v2 session is active. Add `aria-label={language.t("dataworks.scope.current")}` and remove any full-width pill/glass assumptions from its CSS.

- [ ] **Step 5: Delete obsolete hero files and verify no references**

Delete:

```text
packages/app/src/components/dataworks/chat-hero.tsx
packages/app/src/components/dataworks/chat-hero.css
```

Run from `packages/app`:

```bash
bun test src/pages/dataworks/hero-removal.test.ts
bun typecheck
```

Expected: test PASS; typecheck exits 0, proving missing imports, duplicate aliases, undefined Solid primitives, unused variables, and malformed JSX are gone.

- [ ] **Step 6: Commit checkpoint (only with explicit user authorization)**

```bash
git add packages/app/src/pages/new-session.tsx packages/app/src/components/session/session-header.tsx packages/app/src/components/dataworks/scope-bar.tsx packages/app/src/components/dataworks/scope-bar.css packages/app/src/pages/dataworks/hero-removal.test.ts
git rm packages/app/src/components/dataworks/chat-hero.tsx packages/app/src/components/dataworks/chat-hero.css
git commit -m "refactor(app): simplify dataworks chat surface"
```

---

### Task 6: Add the MCP page using existing OpenCode status APIs

**Files:**
- Create: `packages/app/src/pages/dataworks/mcp.tsx`
- Create: `packages/app/src/pages/dataworks/mcp.test.ts`
- Modify: `packages/app/src/app.tsx`
- Modify: `packages/app/src/i18n/en.ts`
- Modify: `packages/app/src/i18n/zh.ts`

**Interfaces:**
- Consumes: `serverSync().child(directory)[0].mcp`, `serverSync().mcp.toggle(directory, name)`, active/fallback directory.
- Produces:
  - `/dataworks/mcp` route.
  - `summarizeMcp(entries): { total: number; connected: number; failed: number; needsAuth: number; disabled: number }`
  - `mcpTone(status): "success" | "warning" | "danger" | "neutral"`.

- [ ] **Step 1: Write MCP summary tests**

Create `packages/app/src/pages/dataworks/mcp.test.ts`:

```ts
import { describe, expect, test } from "bun:test"
import { mcpTone, summarizeMcp } from "./mcp"

describe("dataworks MCP page", () => {
  test("summarizes statuses", () => {
    expect(summarizeMcp([
      { name: "a", status: "connected" },
      { name: "b", status: "failed" },
      { name: "c", status: "needs_auth" },
      { name: "d", status: "disabled" },
    ])).toEqual({ total: 4, connected: 1, failed: 1, needsAuth: 1, disabled: 1 })
  })

  test("maps status tones", () => {
    expect(mcpTone("connected")).toBe("success")
    expect(mcpTone("failed")).toBe("danger")
    expect(mcpTone("needs_auth")).toBe("warning")
    expect(mcpTone("disabled")).toBe("neutral")
  })
})
```

- [ ] **Step 2: Run the focused test and observe failure**

Run from `packages/app`:

```bash
bun test src/pages/dataworks/mcp.test.ts
```

Expected: FAIL because `mcp.tsx` does not exist.

- [ ] **Step 3: Implement the MCP page**

Create `packages/app/src/pages/dataworks/mcp.tsx`:

- Resolve directory from selected OpenCode project/worktree; if absent, render a compact empty panel with the existing “open project” route/action.
- Read MCP entries via `const [child] = serverSync().child(directory)` and `Object.entries(child.mcp ?? {})`.
- Render four summary cards: total, connected, attention, disabled.
- Render one white row per MCP server with name, translated status tag, error detail for failed/client-registration states, and a switch.
- On switch call `serverSync().mcp.toggle(directory, name)`; disable only the active row while pending.
- Do not show secrets, raw configs, or add/edit forms in P0.

- [ ] **Step 4: Add exact MCP page copy**

English:

```ts
"dataworks.mcp.title": "MCP",
"dataworks.mcp.description": "View and control MCP services available to the active workspace.",
"dataworks.mcp.total": "Configured",
"dataworks.mcp.connected": "Connected",
"dataworks.mcp.attention": "Needs attention",
"dataworks.mcp.disabled": "Disabled",
"dataworks.mcp.noWorkspace": "Open a workspace to load MCP status.",
```

Chinese:

```ts
"dataworks.mcp.title": "MCP",
"dataworks.mcp.description": "查看并控制当前工作区可用的 MCP 服务。",
"dataworks.mcp.total": "已配置",
"dataworks.mcp.connected": "已连接",
"dataworks.mcp.attention": "需要处理",
"dataworks.mcp.disabled": "已禁用",
"dataworks.mcp.noWorkspace": "请先打开工作区，再加载 MCP 状态。",
```

- [ ] **Step 5: Register the route**

In `packages/app/src/app.tsx`, add:

```ts
const DataWorksMcp = lazy(() => import("@/pages/dataworks/mcp"))
```

and:

```tsx
<Route path="/dataworks/mcp" component={DataWorksMcp} />
```

Place it between jobs and skills to mirror the sidebar.

- [ ] **Step 6: Run MCP/route tests and typecheck**

Run from `packages/app`:

```bash
bun test src/pages/dataworks/mcp.test.ts src/pages/dataworks/route.test.ts
bun typecheck
```

Expected: tests PASS; typecheck exits 0.

- [ ] **Step 7: Commit checkpoint (only with explicit user authorization)**

```bash
git add packages/app/src/pages/dataworks/mcp.tsx packages/app/src/pages/dataworks/mcp.test.ts packages/app/src/app.tsx packages/app/src/i18n/en.ts packages/app/src/i18n/zh.ts
git commit -m "feat(app): add dataworks MCP console"
```

---

### Task 7: Polish SQL results into a compact data card

**Files:**
- Modify: `packages/session-ui/src/components/sql-result.ts`
- Modify: `packages/session-ui/src/components/sql-result.test.ts`
- Modify: `packages/session-ui/src/components/sql-result-card.tsx`
- Modify: `packages/session-ui/src/components/sql-result-card.css`
- Modify: `packages/session-ui/src/components/message-part.tsx`
- Modify: `packages/ui/src/i18n/en.ts`
- Modify: `packages/ui/src/i18n/zh.ts`

**Interfaces:**
- Consumes: existing `SqlResultView`, `dw_run_sql` ToolRegistry renderer, `UiI18n`.
- Produces:
  - `visibleSqlRows(view, expanded, collapsedLimit = 12): unknown[][]`
  - `SqlResultCard` with translated `labels` or `useI18n()` copy.
  - Copy SQL and Copy TSV actions, collapsible SQL source, bounded table preview.

- [ ] **Step 1: Extend pure SQL result tests**

In `packages/session-ui/src/components/sql-result.test.ts`, add:

```ts
import { visibleSqlRows } from "./sql-result"

test("bounds collapsed rows and exposes all rows when expanded", () => {
  const view = {
    columns: [{ name: "id" }],
    rows: Array.from({ length: 20 }, (_, index) => [index + 1]),
    rowCount: 20,
    truncated: false,
  }
  expect(visibleSqlRows(view, false)).toHaveLength(12)
  expect(visibleSqlRows(view, true)).toHaveLength(20)
})

test("subtitle includes row count duration and project", () => {
  expect(sqlResultSubtitle({
    columns: [],
    rows: [],
    rowCount: 0,
    truncated: false,
    durationMs: 18,
    projectID: 7,
  })).toBe("0 rows · 18ms · project 7")
})
```

- [ ] **Step 2: Run the focused test and observe failure**

Run from `packages/session-ui`:

```bash
bun test src/components/sql-result.test.ts
```

Expected: FAIL because `visibleSqlRows` does not exist.

- [ ] **Step 3: Add the bounded-row helper**

In `sql-result.ts`:

```ts
export function visibleSqlRows(view: SqlResultView, expanded: boolean, limit = 12): unknown[][] {
  if (expanded) return view.rows
  return view.rows.slice(0, limit)
}
```

Use it in `SqlResultTable` instead of duplicating row slicing.

- [ ] **Step 4: Refactor the result card interactions**

In `sql-result-card.tsx`:

- Track `sqlOpen`, `rowsExpanded`, `copiedSql`, and `copiedRows` separately.
- Hide SQL source by default behind “Show SQL”.
- Add “Copy SQL” only when SQL exists.
- Keep “Copy TSV”.
- Keep “Show all N” only when preview rows exceed 12.
- Set `data-active="true"` while a copy acknowledgement is visible.
- Keep the table region keyboard focusable and labelled.
- Use translated copy from `useI18n()`; do not hardcode `Copied`, `Copy TSV`, `No rows returned`, or truncation text.

Required UI keys in `packages/ui/src/i18n/en.ts`:

```ts
"ui.tool.sql.showSql": "Show SQL",
"ui.tool.sql.hideSql": "Hide SQL",
"ui.tool.sql.copySql": "Copy SQL",
"ui.tool.sql.copyRows": "Copy TSV",
"ui.tool.sql.copied": "Copied",
"ui.tool.sql.showAll": "Show all {{count}}",
"ui.tool.sql.collapse": "Collapse",
"ui.tool.sql.empty": "No rows returned.",
"ui.tool.sql.truncated": "Preview truncated — full result is retained server-side.",
```

Matching Chinese in `packages/ui/src/i18n/zh.ts`:

```ts
"ui.tool.sql.showSql": "查看 SQL",
"ui.tool.sql.hideSql": "收起 SQL",
"ui.tool.sql.copySql": "复制 SQL",
"ui.tool.sql.copyRows": "复制 TSV",
"ui.tool.sql.copied": "已复制",
"ui.tool.sql.showAll": "显示全部 {{count}} 行",
"ui.tool.sql.collapse": "收起",
"ui.tool.sql.empty": "查询未返回数据。",
"ui.tool.sql.truncated": "结果预览已截断，完整结果仍保留在服务端。",
```

- [ ] **Step 5: Apply New API-style result CSS**

In `sql-result-card.css`:

- Use 8px card/table radius, 1px `#e5e7eb` border, white base, and `#fafbfc` table header.
- Change action buttons from pills to 6px rounded compact buttons.
- Remove all gradient/glow/color-mix hover transforms.
- Keep sticky table header, horizontal scroll, max cell width, alternating row background, and 320px maximum viewport height.
- Ensure dark mode uses existing v2 variables rather than fixed white.

- [ ] **Step 6: Keep ToolRegistry integration localized**

In `message-part.tsx`, keep the `dw_run_sql` registration, compute the view once, and pass translated card title/action copy through the shared i18n context. Do not reintroduce generic `BasicTool` output when a structured view exists; fallback to `BasicTool` only when parsing returns `undefined`.

- [ ] **Step 7: Run session-ui tests and typechecks**

Run:

```bash
cd packages/session-ui && bun test src/components/sql-result.test.ts && bun typecheck
cd ../ui && bun typecheck
```

Expected: SQL tests PASS; both typechecks exit 0.

- [ ] **Step 8: Commit checkpoint (only with explicit user authorization)**

```bash
git add packages/session-ui/src/components/sql-result.ts packages/session-ui/src/components/sql-result.test.ts packages/session-ui/src/components/sql-result-card.tsx packages/session-ui/src/components/sql-result-card.css packages/session-ui/src/components/message-part.tsx packages/ui/src/i18n/en.ts packages/ui/src/i18n/zh.ts
git commit -m "feat(session-ui): polish SQL result cards"
```

---

### Task 8: Normalize management pages to the shared console primitives

**Files:**
- Modify: `packages/app/src/pages/dataworks/connections.tsx`
- Modify: `packages/app/src/pages/dataworks/explorer.tsx`
- Modify: `packages/app/src/pages/dataworks/jobs.tsx`
- Modify: `packages/app/src/pages/dataworks/skills.tsx`
- Modify: `packages/app/src/pages/dataworks/knowledge.tsx`
- Modify: `packages/app/src/pages/dataworks/audit.tsx`
- Modify: `packages/app/src/styles/dataworks-theme.css`

**Interfaces:**
- Consumes: simplified `DataWorksShell` and CSS primitives from Task 2.
- Produces: consistent page header/toolbars/panels without changing APIs or business behavior.

- [ ] **Step 1: Add a source contract test for shared page primitives**

Create `packages/app/src/pages/dataworks/page-style.test.ts`:

```ts
import { expect, test } from "bun:test"

const pages = ["connections", "explorer", "jobs", "skills", "knowledge", "audit"]

test("management pages use the shared page shell", async () => {
  for (const page of pages) {
    const source = await Bun.file(new URL(`./${page}.tsx`, import.meta.url)).text()
    expect(source).toContain("DataWorksShell")
    expect(source).toContain("dwa-page-head")
    expect(source).toContain("dwa-panel")
  }
})
```

- [ ] **Step 2: Run the source test and observe failure**

Run from `packages/app`:

```bash
bun test src/pages/dataworks/page-style.test.ts
```

Expected: FAIL because current pages use ad hoc flex wrappers and `.dwa-card` only.

- [ ] **Step 3: Normalize each management page without changing behavior**

For each page:

- Replace top wrapper with `class="dwa-page-stack"`.
- Add a `<header class="dwa-page-head">` containing existing h1 and a one-line description.
- Wrap filters/forms/lists/tables in `<section class="dwa-panel">`.
- Place page actions in `.dwa-toolbar`.
- Keep all request methods, response handling, write confirmation, role checks, and empty/error logic exactly as before.
- Do not combine or rewrite control-plane APIs.

Connections keeps create/test/delete behavior; Explorer keeps project/table/SQL flows; Jobs keeps status refresh; Skills/Knowledge/Audit keep existing calls.

- [ ] **Step 4: Add responsive shared styles**

In `dataworks-theme.css`, define:

```css
.dwa-page-stack { width: min(1120px, 100%); margin: 0 auto; display: flex; flex-direction: column; gap: 12px; }
.dwa-page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.dwa-panel { background: var(--dwa-surface); border: 1px solid var(--dwa-border); border-radius: 10px; padding: 16px; }
.dwa-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.dwa-field { min-height: 36px; border: 1px solid var(--dwa-border); border-radius: 6px; background: var(--dwa-surface); }
```

- [ ] **Step 5: Run management source test and typecheck**

Run from `packages/app`:

```bash
bun test src/pages/dataworks/page-style.test.ts
bun typecheck
```

Expected: test PASS; typecheck exits 0.

- [ ] **Step 6: Commit checkpoint (only with explicit user authorization)**

```bash
git add packages/app/src/pages/dataworks/connections.tsx packages/app/src/pages/dataworks/explorer.tsx packages/app/src/pages/dataworks/jobs.tsx packages/app/src/pages/dataworks/skills.tsx packages/app/src/pages/dataworks/knowledge.tsx packages/app/src/pages/dataworks/audit.tsx packages/app/src/pages/dataworks/page-style.test.ts packages/app/src/styles/dataworks-theme.css
git commit -m "refactor(app): align dataworks management pages"
```

---

### Task 9: Add browser regression coverage and perform final cleanup

**Files:**
- Create: `packages/app/e2e/dataworks-console.spec.ts`
- Modify: `packages/app/src/app.tsx`
- Modify: `packages/app/src/i18n/en.ts`
- Modify: `packages/app/src/i18n/zh.ts`
- Modify: `docs/superpowers/specs/2026-07-22-newapi-style-ui-design.md`

**Interfaces:**
- Consumes: completed console shell, dashboard, MCP page, draft handoff, SQL result card.
- Produces: automated critical-path evidence and final approved implementation status.

- [ ] **Step 1: Write the Playwright critical-path test**

Create `packages/app/e2e/dataworks-console.spec.ts` using the existing E2E fixtures/base URL conventions:

```ts
import { expect, test } from "@playwright/test"

test("DataWorks console supports the chat-first path", async ({ page }) => {
  await page.goto("/login")
  await page.getByLabel("用户名").fill("admin")
  await page.getByLabel("密码").fill(process.env.DATAWORKS_TEST_PASSWORD ?? "admin")
  await page.getByRole("button", { name: "登录" }).click()

  await expect(page).toHaveURL(/\/$/)
  await expect(page.locator('[data-component="dataworks-console"]')).toBeVisible()
  await expect(page.locator('[data-slot="console-nav-item"]')).toHaveCount(9)
  await expect(page.getByRole("link", { name: "MCP" })).toBeVisible()

  await page.getByPlaceholder(/自然语言或 SQL/).fill("SELECT 1")
  await page.getByRole("button", { name: /发送|开始查询/ }).click()
  await expect(page).toHaveURL(/new-session/)
  await expect(page.getByText("SELECT 1")).toBeVisible()
})
```

Use the project’s existing login seed/dry-run password fixture; if it is not `admin`, read it from the existing E2E environment helper rather than hardcoding a new credential.

- [ ] **Step 2: Run the E2E test and fix only real integration mismatches**

Run from `packages/app` with the project’s dry-run server active:

```bash
bun run test:e2e -- e2e/dataworks-console.spec.ts
```

Expected: PASS. If it fails, fix selectors/routing/state handoff in product code; do not weaken the assertions that the shell exists, nine items render, MCP is present, and query text reaches the draft.

- [ ] **Step 3: Run the full focused verification matrix**

Run:

```bash
cd E:/dataworks_agent/packages/app
bun test src/pages/dataworks/route.test.ts src/components/dataworks/console-layout.test.ts src/components/dataworks/query-scope.test.ts src/pages/dataworks/dashboard.test.ts src/pages/dataworks/hero-removal.test.ts src/pages/dataworks/mcp.test.ts src/pages/dataworks/page-style.test.ts
bun typecheck

cd E:/dataworks_agent/packages/session-ui
bun test src/components/sql-result.test.ts
bun typecheck

cd E:/dataworks_agent/packages/ui
bun typecheck
```

Expected: every command exits 0.

- [ ] **Step 4: Run changed-file hygiene checks**

Run from repository root:

```bash
rg -n "DataWorksChatHero|dwa-hero|ConnectionSelectorAlias|dataworks-layout-nav|TBD|TODO|FIXME" packages/app/src packages/session-ui/src/components/sql-result* docs/superpowers/specs/2026-07-22-newapi-style-ui-design.md
```

Expected: no obsolete hero/alias/layout-nav matches and no placeholders introduced by this work. Existing unrelated TODOs outside the targeted files are out of scope.

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 5: Perform manual responsive and UX acceptance**

Use the running app and verify at 1440×900, 1024×768, and 390×844:

- Desktop sidebar is fixed and all nine entries are visible.
- Mobile sidebar opens/closes as a drawer; no horizontal body overflow.
- Login is not wrapped in the console shell.
- Dashboard has no hero title, gradient glow, glass card, or pill-heavy navigation.
- Missing connection/project disables send and explains the next action.
- Quick actions fill but do not auto-send.
- Session retains selected DataWorks scope.
- SQL result card shows structured rows, copy actions, collapsible SQL, empty and truncated states.
- MCP page shows real OpenCode status and can toggle one server.
- Audit non-admin forbidden state and all existing management actions still work.

- [ ] **Step 6: Update design status only after evidence passes**

In `docs/superpowers/specs/2026-07-22-newapi-style-ui-design.md`, change:

```markdown
状态：待用户审阅
```

to:

```markdown
状态：已实现并通过 P0 验收
```

Add a final “Verification” section listing the exact passing commands from Step 3 and the Playwright result from Step 2.

- [ ] **Step 7: Final commit (only with explicit user authorization)**

```bash
git add packages/app/e2e/dataworks-console.spec.ts docs/superpowers/specs/2026-07-22-newapi-style-ui-design.md
git commit -m "test(app): cover dataworks console flow"
```

---

## Plan Self-Review

### Spec coverage

- New API shell + nine-item sidebar including MCP: Tasks 1–2.
- Authenticated chat-first `/` dashboard: Task 4.
- Shared connection/project/mode context: Task 3.
- Existing OpenCode draft/session flow preserved: Tasks 4–5.
- Marketing hero, duplicate styles, broken imports/JSX removed: Task 5.
- MCP status/enablement page without a duplicate backend: Task 6.
- Structured SQL card: Task 7.
- Existing management pages visually unified without business rewrites: Task 8.
- Login default `/`, responsive states, errors, regression checks: Tasks 1, 2, and 9.
- Skill-specific result-card redesign is P1 in the approved spec and is intentionally not added to P0.
- Real “today query” metrics and data-explorer deep link are P2 and remain `--`/absent in P0 rather than being fabricated.

### Placeholder scan

The implementation instructions contain no `TBD`, deferred code placeholder, unspecified “add tests”, or undefined interface. Any conditional adjustment in Task 9 is limited to reading the repository’s existing E2E credential fixture.

### Type consistency

- `selectedProjectID` is consistently a `string | undefined`; project API calls convert as needed.
- `QueryScope` is the single project-selection owner; `DataWorksScopeBar` is only a wrapper.
- Dashboard handoff uses the existing `tabs.newDraft(draft, prompt)` signature.
- MCP page uses the existing `serverSync().mcp.toggle(directory, name)` signature.
- SQL result helpers continue to consume and return `SqlResultView`/`unknown[][]`.
