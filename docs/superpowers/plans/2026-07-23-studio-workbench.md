# DataWorks Studio Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Query Studio-style DataWorks workbench that keeps the Agent on the right, exposes real Plan/SQL/Results/Schema views in the center, shares one connection/project scope, and never auto-runs Agent-generated SQL.

**Architecture:** Upgrade the existing `DataWorksConsoleLayout` into a route-aware shell. Chat and Session routes render a persistent `StudioWorkbench` around the existing route content; management routes keep a compact console shell. A pure workbench state module owns SQL documents, result freshness, scope request identity, result previews, and geometry rules, while `DataWorksContext` remains the only connection/project data source.

**Tech Stack:** SolidJS, TypeScript, Bun tests, `@solid-primitives/storage` through the existing `persisted` helper, existing DataWorks control-plane APIs, existing OpenCode Session UI, CSS container/media queries, Playwright for browser acceptance.

## Global Constraints

- Work on branch `studio-workbench`; branch names may contain at most three hyphen-separated words and no slash/type prefix.
- Create the implementation branch in an isolated worktree with `using-git-worktrees` before changing production code.
- Run tests and `bun typecheck` from package directories, never from the repository root and never by invoking `tsc` directly.
- Use `C:\Users\Administrator\.bun\bin\bun.exe` because the PATH `bun.ps1` shim is broken on this machine.
- Do not edit generated Client files; if a public Protocol or Server `HttpApi` changes, run `bun run generate` from `packages/client`. This plan does not require a Protocol or `HttpApi` change.
- Keep runtime dependencies directed Schema → Core/Protocol → Server. App/Client code may depend on Schema and Protocol, never Core or Server. `session-ui` must not import from `app`.
- Follow the repository style guide: no import aliases, no star imports, no `any`, prefer `const`, early returns, dot notation, and no speculative single-use helpers.
- Preserve one shared DataWorks scope: `connectionID`, `projectID`, `projectName`, and `region` come from `DataWorksContext`.
- Agent-generated SQL may open or update the SQL editor but must never call `runSql`; only the amber Run button may execute.
- SQL execution stays on the existing read-only endpoint with `maxRows: 1000` and `timeoutMs: 30_000`; browser-side checks are hints, not the security boundary.
- Persist only panel geometry, collapse state, the active workbench tab, safe Session-backed artifact identifiers, and validated connection/project IDs. Never persist credentials, SQL text, query results, Result Preview payloads, Agent messages, tickets, or full Schema responses.
- Result Preview is limited to the first 20 rows and first 50 columns.
- Visual tokens are fixed: background `#0C1118`, panel `#101720`, elevated `#151E29`, divider `#263445`, text `#EDF6FB`, muted `#8DA1B2`, context cyan `#5FC9D5`, action amber `#E8AD46`, error coral `#F07878`.
- Default validation uses controlled fixtures and read-only probes. Do not perform real DataWorks writes.

## File Map

- Create `packages/app/src/pages/dataworks/workbench-state.ts`: pure state transitions, scope identity, result preview, and panel geometry.
- Create `packages/app/src/pages/dataworks/workbench-state.test.ts`: exhaustive unit tests for the pure workbench model.
- Create `packages/session-ui/src/components/sql-artifact-event.ts`: dependency-safe browser event contract for SQL code artifacts.
- Create `packages/session-ui/src/components/sql-artifact-event.test.ts`: event contract tests.
- Modify `packages/session-ui/src/components/markdown.tsx`: add an explicit “open SQL” action only to complete `sql`/`odps` fenced blocks.
- Modify `packages/session-ui/package.json`: export the SQL artifact event module.
- Create `packages/app/src/pages/dataworks/studio-workbench.tsx`: persistent shell owner, resource loading, SQL execution, and Agent child slot.
- Create `packages/app/src/pages/dataworks/studio-workbench.css`: all four-column workbench and responsive styling.
- Create `packages/app/src/pages/dataworks/resource-explorer.tsx`: connection/project/table tree and Schema selection.
- Create `packages/app/src/pages/dataworks/artifact-workspace.tsx`: Plan, SQL, Results, and Schema tabs.
- Create `packages/app/src/pages/dataworks/results-grid.tsx`: structured bounded SQL result table.
- Modify `packages/app/src/components/dataworks/console-layout.tsx`: narrow global rail and route-aware workbench composition.
- Modify `packages/app/src/components/dataworks/console-layout.css`: management-shell compatibility and global rail styling.
- Modify `packages/app/src/pages/dataworks/dashboard.tsx`: compact Agent landing surface and `ServerConnection.Any` label fix.
- Modify `packages/app/src/pages/dataworks/dashboard-chat-hero.tsx`: compact mode appropriate for the Agent panel.
- Modify `packages/app/src/pages/dataworks/dashboard.css`: remove marketing hero treatment and constrain the landing surface.
- Modify `packages/app/src/styles/dataworks-theme.css`: scope the approved dark tokens to the workbench.
- Modify `packages/app/src/components/dataworks/console-layout.test.ts`: route composition and shell classification.
- Create `packages/app/src/pages/dataworks/studio-workbench.test.ts`: integration-facing pure contract tests.
- Create `packages/app/e2e/dataworks/studio-workbench.spec.ts`: target-width and critical-flow browser acceptance.

---

### Task 1: Pure Workbench State Model

**Files:**
- Create: `packages/app/src/pages/dataworks/workbench-state.ts`
- Create: `packages/app/src/pages/dataworks/workbench-state.test.ts`

**Interfaces:**
- Produces: `WorkbenchTab`, `WorkbenchScope`, `SqlDocument`, `SqlArtifact`, `ScopedSqlResult`, `scopeKey`, `openSqlArtifact`, `editSqlDocument`, `acceptScopedResult`, `createResultPreview`, `clampResourceWidth`, `clampAgentWidth`, and `responsiveWorkbench`.
- Consumes: `DataWorksSqlResult` from `@/context/dataworks` as a type-only import.

- [ ] **Step 1: Write the failing state tests**

```ts
import { describe, expect, test } from "bun:test"
import {
  acceptScopedResult,
  clampAgentWidth,
  clampResourceWidth,
  createResultPreview,
  editSqlDocument,
  openSqlArtifact,
  responsiveWorkbench,
  scopeKey,
} from "./workbench-state"

const scope = {
  connectionID: "conn-1",
  projectID: "100",
  projectName: "analytics",
  region: "cn-hangzhou",
}

describe("workbench state", () => {
  test("opens Agent SQL without marking it executed", () => {
    expect(openSqlArtifact(undefined, { sql: "SELECT 1", title: "Health", sourceMessageID: "msg-1" })).toMatchObject({
      sql: "SELECT 1",
      editedVersion: 0,
      executedVersion: undefined,
    })
  })

  test("does not overwrite a dirty SQL document", () => {
    const dirty = editSqlDocument(openSqlArtifact(undefined, { sql: "SELECT 1" }), "SELECT 2")
    expect(openSqlArtifact(dirty, { sql: "SELECT 3" }).id).not.toBe(dirty.id)
  })

  test("rejects results completed under an old scope", () => {
    expect(acceptScopedResult(scope, { ...scope, projectID: "200" }, { columns: [], rows: [], truncated: false })).toBeUndefined()
  })

  test("limits Agent preview to twenty rows and fifty columns", () => {
    const result = {
      columns: Array.from({ length: 60 }, (_, index) => ({ name: `c${index}`, type: "string" })),
      rows: Array.from({ length: 30 }, () => Array.from({ length: 60 }, (_, index) => index)),
      truncated: true,
    }
    expect(createResultPreview(result).columns).toHaveLength(50)
    expect(createResultPreview(result).rows).toHaveLength(20)
    expect(createResultPreview(result).rows[0]).toHaveLength(50)
  })

  test("uses deterministic scope identity and bounded panel widths", () => {
    expect(scopeKey(scope)).toBe("conn-1\n100\nanalytics\ncn-hangzhou")
    expect(clampResourceWidth(120)).toBe(200)
    expect(clampResourceWidth(500)).toBe(360)
    expect(clampAgentWidth(200)).toBe(320)
    expect(clampAgentWidth(900)).toBe(600)
  })

  test("prioritizes the editor below 960px", () => {
    expect(responsiveWorkbench(1440)).toEqual({ resourceOverlay: false, agentOverlay: false })
    expect(responsiveWorkbench(1024)).toEqual({ resourceOverlay: false, agentOverlay: false })
    expect(responsiveWorkbench(768)).toEqual({ resourceOverlay: true, agentOverlay: true })
  })
})
```

- [ ] **Step 2: Run the state test and verify RED**

Run from `packages/app`:

```powershell
& 'C:\Users\Administrator\.bun\bin\bun.exe' test --preload ./happydom.ts ./src/pages/dataworks/workbench-state.test.ts
```

Expected: FAIL because `workbench-state.ts` does not exist.

- [ ] **Step 3: Implement the minimal pure state model**

```ts
import type { DataWorksSqlResult } from "@/context/dataworks"
import { uuid } from "@/utils/uuid"

export type WorkbenchTab = "plan" | "sql" | "results" | "schema"
export type WorkbenchScope = {
  connectionID?: string
  projectID?: string
  projectName?: string
  region?: string
}
export type SqlArtifact = { sql: string; title?: string; sourceMessageID?: string }
export type SqlDocument = SqlArtifact & {
  id: string
  baseSql: string
  editedVersion: number
  executedVersion?: number
}
export type ScopedSqlResult = { scope: WorkbenchScope; result: DataWorksSqlResult; sqlVersion: number }

export function scopeKey(scope: WorkbenchScope) {
  return [scope.connectionID, scope.projectID, scope.projectName, scope.region].map((value) => value ?? "").join("\n")
}

export function openSqlArtifact(current: SqlDocument | undefined, artifact: SqlArtifact): SqlDocument {
  const dirty = current && current.sql !== current.baseSql
  if (!current || dirty) return { ...artifact, id: uuid(), baseSql: artifact.sql, editedVersion: 0 }
  return {
    ...artifact,
    id: current.id,
    baseSql: artifact.sql,
    editedVersion: current.editedVersion + 1,
  }
}

export function editSqlDocument(document: SqlDocument, sql: string): SqlDocument {
  if (document.sql === sql) return document
  return { ...document, sql, editedVersion: document.editedVersion + 1 }
}

export function acceptScopedResult(scope: WorkbenchScope, requested: WorkbenchScope, result: DataWorksSqlResult) {
  if (scopeKey(scope) !== scopeKey(requested)) return
  return result
}

export function createResultPreview(result: DataWorksSqlResult) {
  const columns = result.columns.slice(0, 50)
  return {
    columns,
    rows: result.rows.slice(0, 20).map((row) => row.slice(0, columns.length)),
    truncated: result.truncated || result.columns.length > columns.length || result.rows.length > 20,
    durationMs: result.durationMs,
  }
}

export const clampResourceWidth = (width: number) => Math.min(360, Math.max(200, width))
export const clampAgentWidth = (width: number) => Math.min(600, Math.max(320, width))
export const responsiveWorkbench = (width: number) => ({ resourceOverlay: width < 960, agentOverlay: width < 960 })
```

Import `uuid` from `@/utils/uuid`; do not mock `globalThis`.

- [ ] **Step 4: Run the state test and verify GREEN**

Run the Step 2 command. Expected: all workbench-state tests PASS.

- [ ] **Step 5: Commit the state model**

```powershell
git add packages/app/src/pages/dataworks/workbench-state.ts packages/app/src/pages/dataworks/workbench-state.test.ts
git commit -m "feat(app): add workbench state model"
```

---

### Task 2: Agent SQL Artifact Bridge

**Files:**
- Create: `packages/session-ui/src/components/sql-artifact-event.ts`
- Create: `packages/session-ui/src/components/sql-artifact-event.test.ts`
- Modify: `packages/session-ui/src/components/markdown.tsx`
- Modify: `packages/session-ui/package.json`

**Interfaces:**
- Produces: `SQL_ARTIFACT_EVENT`, `SqlArtifactDetail`, `emitSqlArtifact`, and `isSqlArtifactDetail` exported as `@opencode-ai/session-ui/sql-artifact-event`.
- Consumes: complete fenced code blocks whose normalized language is `sql`, `odps`, or `maxcompute`.
- Safety: dispatching the event never performs a fetch or invokes a tool.

- [ ] **Step 1: Write the failing event contract test**

```ts
import { expect, test } from "bun:test"
import { emitSqlArtifact, isSqlArtifactDetail, SQL_ARTIFACT_EVENT } from "./sql-artifact-event"

test("emits a bounded typed SQL artifact without execution", () => {
  const target = new EventTarget()
  let detail: unknown
  target.addEventListener(SQL_ARTIFACT_EVENT, (event) => {
    detail = (event as CustomEvent).detail
  })
  emitSqlArtifact(target, { sql: "SELECT 1", source: "agent-markdown" })
  expect(isSqlArtifactDetail(detail)).toBe(true)
  expect(detail).toEqual({ sql: "SELECT 1", source: "agent-markdown" })
})

test("rejects empty and oversized payloads", () => {
  expect(isSqlArtifactDetail({ sql: "", source: "agent-markdown" })).toBe(false)
  expect(isSqlArtifactDetail({ sql: "x".repeat(4001), source: "agent-markdown" })).toBe(false)
})
```

- [ ] **Step 2: Run the event test and verify RED**

Run from `packages/session-ui`:

```powershell
& 'C:\Users\Administrator\.bun\bin\bun.exe' test src/components/sql-artifact-event.test.ts
```

Expected: FAIL because the event module does not exist.

- [ ] **Step 3: Implement and export the dependency-safe event contract**

```ts
export const SQL_ARTIFACT_EVENT = "opencode:sql-artifact"
export type SqlArtifactDetail = { sql: string; source: "agent-markdown" | "sql-tool"; sourceMessageID?: string }

export function isSqlArtifactDetail(value: unknown): value is SqlArtifactDetail {
  if (!value || typeof value !== "object") return false
  const detail = value as Record<string, unknown>
  if (typeof detail.sql !== "string" || !detail.sql.trim() || detail.sql.length > 4000) return false
  return detail.source === "agent-markdown" || detail.source === "sql-tool"
}

export function emitSqlArtifact(target: EventTarget, detail: SqlArtifactDetail) {
  if (!isSqlArtifactDetail(detail)) return false
  return target.dispatchEvent(new CustomEvent(SQL_ARTIFACT_EVENT, { detail }))
}
```

Add this explicit export to `packages/session-ui/package.json`:

```json
"./sql-artifact-event": "./src/components/sql-artifact-event.ts"
```

- [ ] **Step 4: Add an explicit SQL action to completed fenced blocks**

In `markdown.tsx`, keep copy behavior unchanged. Add a sibling button only when `data-language` is `sql`, `odps`, or `maxcompute` and the block is complete. Its click handler reads the block’s text and calls:

```ts
emitSqlArtifact(window, { sql: content, source: "agent-markdown" })
```

The button must use `type="button"`, `data-slot="markdown-open-sql"`, and `aria-label="Open in SQL"`. Streaming/incomplete blocks do not receive the action. The event is the only side effect.

- [ ] **Step 5: Run Session UI tests and typecheck**

Run from `packages/session-ui`:

```powershell
& 'C:\Users\Administrator\.bun\bin\bun.exe' test src/components/sql-artifact-event.test.ts src/components/markdown-code-state.test.ts src/components/markdown-stream.test.ts
& 'C:\Users\Administrator\.bun\bin\bun.exe' typecheck
```

Expected: targeted tests PASS and typecheck exits 0.

- [ ] **Step 6: Commit the artifact bridge**

```powershell
git add packages/session-ui/package.json packages/session-ui/src/components/sql-artifact-event.ts packages/session-ui/src/components/sql-artifact-event.test.ts packages/session-ui/src/components/markdown.tsx
git commit -m "feat(session-ui): expose SQL artifacts"
```

---

### Task 3: Real Resource Explorer and Shared Scope

**Files:**
- Create: `packages/app/src/pages/dataworks/resource-explorer.tsx`
- Create: `packages/app/src/pages/dataworks/studio-workbench.test.ts`
- Modify: `packages/app/src/context/dataworks.tsx`

**Interfaces:**
- Consumes: `connections`, `projects`, `selectedConnectionID`, `selectedProjectID`, `listTables`, and `describeTable` from `DataWorksContext`.
- Produces: `ResourceExplorer` props `{ selectedTable, onSelectTable, onOpenSql }` and validated persisted scope IDs.
- Emits: table selection with the exact `DataWorksTable` and optional loaded `DataWorksTableDescription`.

- [ ] **Step 1: Write failing scope validation tests**

Add pure exports in `dataworks.tsx` and test them from `studio-workbench.test.ts`:

```ts
import { describe, expect, test } from "bun:test"
import { validConnectionID, validProjectID } from "@/context/dataworks"

describe("workbench scope restore", () => {
  test("restores only IDs present in fresh server lists", () => {
    expect(validConnectionID("conn-2", [{ id: "conn-1" }, { id: "conn-2" }])).toBe("conn-2")
    expect(validConnectionID("stale", [{ id: "conn-1" }])).toBe("conn-1")
    expect(validProjectID("2", [{ projectId: 1 }, { projectId: 2 }])).toBe("2")
    expect(validProjectID("stale", [])).toBeUndefined()
  })
})
```

Use structurally complete fixtures matching exported types; do not weaken types with `any`.

- [ ] **Step 2: Run the test and verify RED**

Run from `packages/app`:

```powershell
& 'C:\Users\Administrator\.bun\bin\bun.exe' test --preload ./happydom.ts ./src/pages/dataworks/studio-workbench.test.ts
```

Expected: FAIL because the validation functions do not exist.

- [ ] **Step 3: Implement validated scope restore in `DataWorksContext`**

Export pure helpers:

```ts
export function validConnectionID(saved: string | undefined, connections: Array<Pick<DataConnection, "id">>) {
  if (saved && connections.some((item) => item.id === saved)) return saved
  return connections[0]?.id
}

export function validProjectID(
  saved: string | undefined,
  projects: Array<Pick<DataWorksProject, "projectId" | "id">>,
) {
  if (saved && projects.some((item) => String(item.projectId ?? item.id) === saved)) return saved
  const first = projects[0]
  return first ? String(first.projectId ?? first.id) : undefined
}
```

Persist only `{ connectionID, projectID }` through `Persist.window("dataworks.scope")`. Wait until persistence and fetched lists are ready, validate IDs, then call the existing setters. Never add connection objects, project objects, regions, names, or credentials to the persisted store.

- [ ] **Step 4: Implement `ResourceExplorer` with existing APIs**

The component must:

- render the shared connection and project selectors;
- call `listTables(connectionID, projectID, { projectName, region })` when the validated scope changes;
- keep `ListState` local to the table list;
- call `describeTable` on table selection and pass the result upward;
- retain the selected row and emit an incomplete fallback description when describe fails;
- on double click, call `onOpenSql({ sql: `SELECT * FROM ${table.name} LIMIT 100`, title: table.name })` and never call `runSql`.

Use this public boundary and keep request ownership inside the component:

```ts
export function ResourceExplorer(props: {
  selectedTable?: DataWorksTable
  onSelectTable: (table: DataWorksTable, description: DataWorksTableDescription) => void
  onOpenSql: (artifact: SqlArtifact) => void
}): JSX.Element
```

Capture scope before every async request and ignore stale completions:

```ts
const requested = scopeKey(scope())
const result = await dataworks.listTables(connectionID, projectID, { projectName, region })
if (requested !== scopeKey(scope())) return
if (!result.ok) {
  setTableState(result.status === 429 ? "rate_limit" : "error")
  return
}
setTables(result.data)
setTableState(result.data.length ? "ready" : "empty")
```

- [ ] **Step 5: Add resource behavior tests and run GREEN**

Add pure tests for the SQL template and stale async scope comparison to `studio-workbench.test.ts`. Run the Step 2 command and the existing `scope-bar`/query-scope tests. Expected: PASS.

- [ ] **Step 6: Commit shared scope and resources**

```powershell
git add packages/app/src/context/dataworks.tsx packages/app/src/pages/dataworks/resource-explorer.tsx packages/app/src/pages/dataworks/studio-workbench.test.ts
git commit -m "feat(app): add workbench resources"
```

---

### Task 4: Plan, SQL, Results, and Schema Workspace

**Files:**
- Create: `packages/app/src/pages/dataworks/artifact-workspace.tsx`
- Create: `packages/app/src/pages/dataworks/results-grid.tsx`
- Modify: `packages/app/src/pages/dataworks/workbench-state.test.ts`
- Modify: `packages/app/src/pages/dataworks/studio-workbench.test.ts`

**Interfaces:**
- Consumes: `SqlDocument`, `ScopedSqlResult`, `DataWorksTableDescription`, `ListState`, and callbacks supplied by `StudioWorkbench`.
- Produces: `ArtifactWorkspace` with fixed tabs `plan`, `sql`, `results`, `schema`; `ResultsGrid` with structured columns and rows.
- Safety: the SQL text area’s input path cannot invoke `runSql`; only the Run button callback can.

- [ ] **Step 1: Add failing SQL/result transition tests**

```ts
test("editing after a run marks the result stale", () => {
  const opened = openSqlArtifact(undefined, { sql: "SELECT 1" })
  const executed = { ...opened, executedVersion: opened.editedVersion }
  expect(editSqlDocument(executed, "SELECT 2").editedVersion).toBeGreaterThan(executed.executedVersion!)
})

test("a successful scoped result requests the Results tab", () => {
  expect(nextTabAfterRun({ ok: true })).toBe("results")
  expect(nextTabAfterRun({ ok: false })).toBe("sql")
})
```

Add `nextTabAfterRun` to the pure model rather than embedding this decision in JSX.

- [ ] **Step 2: Run targeted tests and verify RED**

Run from `packages/app`:

```powershell
& 'C:\Users\Administrator\.bun\bin\bun.exe' test --preload ./happydom.ts ./src/pages/dataworks/workbench-state.test.ts ./src/pages/dataworks/studio-workbench.test.ts
```

Expected: FAIL for the missing tab transition.

- [ ] **Step 3: Implement `ResultsGrid`**

Normalize string and object columns once, render semantic `<table>` markup, and show duration, instance ID, row count, and truncation state. Limit DOM rows to the response’s already bounded 1000 rows and use `@tanstack/solid-virtual` only if browser profiling shows 1000 rows breach the acceptance threshold. Do not introduce pagination state without a server pagination API.

The component boundary and core table rendering are:

```tsx
export function ResultsGrid(props: { result: DataWorksSqlResult; stale: boolean }): JSX.Element {
  const columns = () =>
    props.result.columns.map((column, index) =>
      typeof column === "string" ? { name: column, type: "" } : { name: column.name || `col_${index + 1}`, type: column.type },
    )
  return (
    <section data-component="workbench-results" data-stale={props.stale ? "true" : "false"}>
      <Show when={props.stale}><div role="status">Results are based on an older SQL revision.</div></Show>
      <div data-slot="result-meta">
        <span>{props.result.rows.length} rows</span>
        <Show when={props.result.durationMs !== undefined}><span>{props.result.durationMs} ms</span></Show>
        <Show when={props.result.instanceId}><span>{props.result.instanceId}</span></Show>
      </div>
      <div data-slot="result-scroll" role="region" aria-label="SQL results" tabindex="0">
        <table>
          <thead><tr><For each={columns()}>{(column) => <th scope="col">{column.name}</th>}</For></tr></thead>
          <tbody>
            <For each={props.result.rows}>{(row) => <tr><For each={columns()}>{(_, index) => <td>{String(row[index()] ?? "")}</td>}</For></tr>}</For>
          </tbody>
        </table>
      </div>
      <Show when={props.result.truncated}><div role="status">Preview truncated.</div></Show>
    </section>
  )
}
```

- [ ] **Step 4: Implement `ArtifactWorkspace`**

Required behavior:

- fixed accessible tablist with Plan, SQL, Results, Schema;
- Plan projects existing Session/Todo content supplied by the shell, otherwise an honest empty state;
- SQL is editable and reports `onEdit(sql)` only;
- amber Run calls `onRun()` only when scope/project name/text are valid and no request is running;
- Results auto-activates after a successful accepted result;
- stale Results remain visible with a stale banner after SQL edits;
- Schema shows loading, ready, incomplete, rate-limit, and error states without clearing table identity;
- Context attachment calls `onAttachPreview(createResultPreview(result))` only after a user click.

Use one explicit prop contract; do not read `DataWorksContext` again inside this component:

```ts
export type ArtifactWorkspaceProps = {
  activeTab: WorkbenchTab
  document: SqlDocument
  result?: ScopedSqlResult
  schema?: DataWorksTableDescription
  schemaState: ListState
  running: boolean
  runEnabled: boolean
  plan: JSX.Element
  onTabChange: (tab: WorkbenchTab) => void
  onSqlChange: (sql: string) => void
  onRun: () => void
  onAttachPreview: (preview: ReturnType<typeof createResultPreview>) => void
}
```

Render the four tabs from a typed constant and wire only the Run button to `onRun`:

```tsx
const WORKBENCH_TABS = ["plan", "sql", "results", "schema"] as const
<div role="tablist" aria-label="Artifact workspace">
  <For each={WORKBENCH_TABS}>
    {(tab) => <button type="button" role="tab" aria-selected={props.activeTab === tab} onClick={() => props.onTabChange(tab)}>{tab}</button>}
  </For>
</div>
```

- [ ] **Step 5: Run tests and typecheck the App package**

Run the Step 2 tests, then from `packages/app`:

```powershell
& 'C:\Users\Administrator\.bun\bin\bun.exe' typecheck
```

Expected: targeted tests PASS. Record any pre-existing unrelated typecheck failure separately; do not suppress it.

- [ ] **Step 6: Commit the artifact workspace**

```powershell
git add packages/app/src/pages/dataworks/artifact-workspace.tsx packages/app/src/pages/dataworks/results-grid.tsx packages/app/src/pages/dataworks/workbench-state.ts packages/app/src/pages/dataworks/workbench-state.test.ts packages/app/src/pages/dataworks/studio-workbench.test.ts
git commit -m "feat(app): add artifact workspace"
```

---

### Task 5: Persistent Workbench Shell and SQL Execution

**Files:**
- Create: `packages/app/src/pages/dataworks/studio-workbench.tsx`
- Create: `packages/app/src/pages/dataworks/studio-workbench.css`
- Modify: `packages/app/src/components/dataworks/console-layout.tsx`
- Modify: `packages/app/src/components/dataworks/console-layout.css`
- Modify: `packages/app/src/components/dataworks/console-layout.test.ts`

**Interfaces:**
- Consumes: the existing route child as the Agent surface, the SQL artifact event, `DataWorksContext`, `ResourceExplorer`, and `ArtifactWorkspace`.
- Produces: persistent four-column layout for `chatPath` routes and compact management shell elsewhere.
- Owns: safe UI persistence, scoped SQL request lifecycle, resource/Agent collapse state, and status bar.

- [ ] **Step 1: Add failing route/layout tests**

Extend `console-layout.test.ts` with pure exported route decisions:

```ts
expect(consoleSurface("/")).toBe("workbench")
expect(consoleSurface("/new-session")).toBe("workbench")
expect(consoleSurface("/server/local/session/ses_1")).toBe("workbench")
expect(consoleSurface("/dataworks/connections")).toBe("management")
expect(consoleSurface("/login")).toBe("none")
```

Add geometry assertions for keyboard resize increments of 16px and clamping.

- [ ] **Step 2: Run shell tests and verify RED**

Run from `packages/app`:

```powershell
& 'C:\Users\Administrator\.bun\bin\bun.exe' test --preload ./happydom.ts ./src/components/dataworks/console-layout.test.ts ./src/pages/dataworks/workbench-state.test.ts
```

Expected: FAIL because `consoleSurface` and workbench composition do not exist.

- [ ] **Step 3: Implement `StudioWorkbench` ownership and persistence**

Use `persisted(Persist.window("dataworks.workbench"), createStore(...))` with this exact safe shape:

```ts
{
  activeTab: "sql" as WorkbenchTab,
  resourceWidth: 240,
  agentWidth: 420,
  resourceCollapsed: false,
  agentCollapsed: false,
}
```

Do not place SQL documents, results, previews, selected table data, or Schema data in that store.

Listen for `SQL_ARTIFACT_EVENT` on `window`, validate the event detail, call `openSqlArtifact`, and activate SQL. The listener must not call `runSql`.

For Run:

1. capture an immutable `WorkbenchScope` and current SQL version;
2. call `dataworks.runSql` exactly once with `maxRows: 1000` and `timeoutMs: 30_000`;
3. compare the captured scope to the current scope before accepting the result;
4. mark the document executed and activate Results only for an accepted success;
5. retain SQL and show an error/rate-limit state for failures.

Implement the request boundary as one function with no retry loop:

```ts
async function runSql() {
  const current = document()
  const requested = scope()
  if (!current.sql.trim() || !requested.connectionID || !requested.projectID || !requested.projectName) return
  setRunning(true)
  setSqlState("loading")
  const response = await dataworks.runSql({
    connectionID: requested.connectionID,
    projectID: requested.projectID,
    projectName: requested.projectName,
    region: requested.region,
    sql: current.sql,
    maxRows: 1000,
    timeoutMs: 30_000,
  })
  setRunning(false)
  if (!response.ok) {
    setSqlState(response.status === 429 ? "rate_limit" : "error")
    return
  }
  const accepted = acceptScopedResult(scope(), requested, response.data)
  if (!accepted) return
  setResult({ scope: requested, result: accepted, sqlVersion: current.editedVersion })
  setDocument("executedVersion", current.editedVersion)
  setUi("activeTab", "results")
  setSqlState("ready")
}
```

- [ ] **Step 4: Implement accessible panel controls**

Each resizer must have `role="separator"`, `aria-orientation="vertical"`, `aria-valuemin`, `aria-valuemax`, and `aria-valuenow`. Arrow keys adjust 16px; Home/End select min/max. Collapse buttons expose `aria-expanded` and remain visible when the panel is closed.

- [ ] **Step 5: Make `DataWorksConsoleLayout` route-aware**

Export:

```ts
export function consoleSurface(pathname: string) {
  if (!shouldUseConsoleShell(pathname)) return "none" as const
  if (activeDataWorksNavItem(pathname).key === "chat") return "workbench" as const
  return "management" as const
}
```

For `workbench`, render the narrow global rail and `<StudioWorkbench agent={props.children} />`. For `management`, render the rail/topbar and original route child. Keep auth redirect and `returnTo` unchanged.

- [ ] **Step 6: Run shell, state, and route tests**

Run from `packages/app`:

```powershell
& 'C:\Users\Administrator\.bun\bin\bun.exe' test --preload ./happydom.ts ./src/components/dataworks/console-layout.test.ts ./src/pages/dataworks/workbench-state.test.ts ./src/pages/dataworks/route.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit the workbench shell**

```powershell
git add packages/app/src/pages/dataworks/studio-workbench.tsx packages/app/src/pages/dataworks/studio-workbench.css packages/app/src/components/dataworks/console-layout.tsx packages/app/src/components/dataworks/console-layout.css packages/app/src/components/dataworks/console-layout.test.ts
git commit -m "feat(app): build studio workbench shell"
```

---

### Task 6: Agent Panel Fit and Approved Visual System

**Files:**
- Modify: `packages/app/src/pages/dataworks/dashboard.tsx`
- Modify: `packages/app/src/pages/dataworks/dashboard-chat-hero.tsx`
- Modify: `packages/app/src/pages/dataworks/dashboard.css`
- Modify: `packages/app/src/styles/dataworks-theme.css`
- Modify: `packages/app/src/pages/dataworks/dashboard.test.ts`
- Modify: `packages/app/src/pages/dataworks/dashboard-i18n.test.ts` only if existing keys change.

**Interfaces:**
- Consumes: the existing `tabs.newDraft`, Session/NewSession route components, and workbench Agent slot.
- Produces: a compact no-duplicate Agent landing surface; existing Session route content remains the real ongoing conversation UI.

- [ ] **Step 1: Add failing Dashboard label and compactness tests**

Move the server label decision into `dashboard-utils.ts`:

```ts
test("uses the supported server display label", () => {
  expect(serverModelLabel({ type: "http", http: { url: "http://localhost:4096" } }, "DataWorks AI")).toBe("localhost:4096")
})
```

The helper must use supported `ServerConnection` fields or existing `serverName`, never `.name` on `ServerConnection.Any`.

- [ ] **Step 2: Run Dashboard tests and verify RED**

Run from `packages/app`:

```powershell
& 'C:\Users\Administrator\.bun\bin\bun.exe' test --preload ./happydom.ts ./src/pages/dataworks/dashboard.test.ts ./src/pages/dataworks/dashboard-i18n.test.ts
```

Expected: FAIL for the missing helper.

- [ ] **Step 3: Refactor the Agent landing surface**

Keep draft creation, runtime checks, prompt preservation, and errors. Remove the large greeting, radial glow, grid decoration, hint-card grid, and duplicate central dashboard framing. Add a compact `mode="panel"` presentation to `ChatHero` or rename it only if every call site is updated in the same commit. The panel must show current scope, model, prompt, send, and actionable connection/project errors.

- [ ] **Step 4: Apply exact scoped dark tokens**

Set the approved tokens only under `[data-component="studio-workbench"]`. The Agent child inherits panel surface colors without rewriting global OpenCode theme variables. Use existing Inter and mono tokens; no new font dependency. Add `prefers-reduced-motion` handling and a 2px cyan focus ring.

Responsive CSS must enforce:

- four columns at `>=1280px`;
- collapsible resource panel at `960–1279px`;
- resource and Agent overlays below `960px`;
- center workspace minimum 480px when panels are inline;
- no horizontal page overflow at 768px.

The token scope starts exactly as follows:

```css
[data-component="studio-workbench"] {
  --studio-background: #0c1118;
  --studio-panel: #101720;
  --studio-elevated: #151e29;
  --studio-divider: #263445;
  --studio-text: #edf6fb;
  --studio-muted: #8da1b2;
  --studio-context: #5fc9d5;
  --studio-action: #e8ad46;
  --studio-error: #f07878;
  background: var(--studio-background);
  color: var(--studio-text);
}

[data-component="studio-workbench"] :focus-visible {
  outline: 2px solid var(--studio-context);
  outline-offset: 1px;
}
```

- [ ] **Step 5: Run Dashboard tests and App typecheck**

Run the Step 2 tests, then:

```powershell
& 'C:\Users\Administrator\.bun\bin\bun.exe' typecheck
```

Expected: Dashboard tests PASS and the former `ServerConnection.Any.name` error is absent. Fix only errors caused by or directly touched by this work; report unrelated upstream failures with exact evidence.

- [ ] **Step 6: Commit visual and Agent integration**

```powershell
git add packages/app/src/pages/dataworks/dashboard.tsx packages/app/src/pages/dataworks/dashboard-chat-hero.tsx packages/app/src/pages/dataworks/dashboard.css packages/app/src/pages/dataworks/dashboard-utils.ts packages/app/src/pages/dataworks/dashboard.test.ts packages/app/src/styles/dataworks-theme.css
git commit -m "feat(app): fit agent studio panel"
```

---

### Task 7: Browser Acceptance and Final Gates

**Files:**
- Create: `packages/app/e2e/dataworks/studio-workbench.spec.ts`
- Modify only if tests expose defects: files from Tasks 1–6.

**Interfaces:**
- Consumes: local App server plus controlled auth/DataWorks fixtures.
- Produces: repeatable acceptance evidence for layout, scope, no-auto-run, read-only execution, results, responsive behavior, and accessibility.

- [ ] **Step 1: Add the browser acceptance spec**

The spec must verify, with request counters at the HTTP boundary:

1. 1440px shows rail, resource tree, center workspace, and Agent panel;
2. clicking an Agent SQL action activates SQL and leaves `/api/dataworks/sql` call count at zero;
3. clicking Run increments the call count once and activates Results;
4. Results render columns/rows and an explicit truncation state;
5. switching project clears Results and Schema but retains SQL text;
6. attaching a preview exposes at most 20 rows and 50 columns;
7. 1024px can collapse/restore resources;
8. 768px auto-collapses Agent and restores it as an overlay;
9. keyboard focus reaches tabs, Run, collapse buttons, and resizers;
10. no browser console errors or credential/result payloads appear in persisted browser storage.

Use the existing E2E mock-server utilities or a local fixture server. Do not mock `globalThis` and do not connect to a real write-enabled DataWorks environment.

Start from this executable Playwright structure and fill fixture route bodies with the exact `DataConnection`, `DataWorksProject`, `DataWorksTable`, and `DataWorksSqlResult` shapes:

```ts
import { expect, test } from "@playwright/test"

test("opens Agent SQL without execution and runs only on explicit click", async ({ page }) => {
  let sqlCalls = 0
  await page.route("**/api/dataworks/sql", async (route) => {
    sqlCalls += 1
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ columns: [{ name: "value", type: "bigint" }], rows: [[1]], truncated: false, durationMs: 3 }),
    })
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/")
  await page.getByRole("button", { name: "Open in SQL" }).click()
  await expect(page.getByRole("tab", { name: "sql" })).toHaveAttribute("aria-selected", "true")
  expect(sqlCalls).toBe(0)
  await page.getByRole("button", { name: "Run" }).click()
  await expect.poll(() => sqlCalls).toBe(1)
  await expect(page.getByRole("tab", { name: "results" })).toHaveAttribute("aria-selected", "true")
})
```

- [ ] **Step 2: Run all targeted package tests**

From `packages/session-ui`:

```powershell
& 'C:\Users\Administrator\.bun\bin\bun.exe' test src/components/sql-artifact-event.test.ts src/components/markdown-code-state.test.ts src/components/sql-result.test.ts
& 'C:\Users\Administrator\.bun\bin\bun.exe' typecheck
```

From `packages/app`:

```powershell
& 'C:\Users\Administrator\.bun\bin\bun.exe' test --preload ./happydom.ts ./src/pages/dataworks ./src/components/dataworks
& 'C:\Users\Administrator\.bun\bin\bun.exe' typecheck
```

Expected: targeted suites PASS and both package typechecks exit 0.

- [ ] **Step 3: Run browser acceptance at all target widths**

From `packages/app`:

```powershell
& 'C:\Users\Administrator\.bun\bin\bun.exe' run test:e2e -- e2e/dataworks/studio-workbench.spec.ts
```

Expected: all acceptance cases PASS at 1440, 1024, and 768 widths.

- [ ] **Step 4: Build and smoke the application**

From `packages/app`:

```powershell
& 'C:\Users\Administrator\.bun\bin\bun.exe' run build
```

Expected: build exits 0. Start the local dev server, exercise the authenticated workbench with read-only fixtures, inspect browser console/network, and capture final screenshots for the three target widths.

- [ ] **Step 5: Review the complete diff**

Run:

```powershell
git diff --check master...HEAD
git status --short
git log --oneline master..HEAD
```

Confirm no generated files, secrets, `.superpowers` artifacts, SQL results, screenshots outside the intended evidence directory, or unrelated user changes are staged.

- [ ] **Step 6: Request code review and fix findings**

Use `requesting-code-review`. Review against the design spec and this plan, then fix every high/medium issue with a focused test. Re-run the affected targeted tests after each fix.

- [ ] **Step 7: Run final verification and commit acceptance fixes**

Re-run Steps 2–4 from fresh commands. If review required code changes, commit them:

```powershell
git add -- packages/app/src/pages/dataworks packages/app/src/components/dataworks packages/app/src/styles/dataworks-theme.css packages/app/e2e/dataworks/studio-workbench.spec.ts packages/session-ui/src/components/markdown.tsx packages/session-ui/src/components/sql-artifact-event.ts packages/session-ui/package.json
git commit -m "fix(app): address workbench review"
```

Do not claim completion from prior or partial output; record the fresh exit codes and test counts.

## Plan Self-Review Checklist

- Every design acceptance item maps to Tasks 1–7.
- SQL artifact opening and SQL execution are separate paths with a request-count test.
- Scope is not duplicated outside `DataWorksContext`; persisted IDs are validated against fresh lists.
- SQL text, results, previews, Schema payloads, credentials, and tickets never enter persisted state.
- Session UI exports an event contract without importing App code, preserving dependency direction.
- The Dashboard type error is fixed through supported server naming rather than a cast.
- Management pages remain reachable and are not forced into the four-column Studio surface.
- No Protocol, `HttpApi`, or generated Client edit is required.
- All commands run from package directories with the known-good Bun executable.
