import { For, Show, createSignal } from "solid-js"
import { Button } from "@opencode-ai/ui/button"
import { ConnectionSelector } from "@/components/dataworks/connection-selector"
import {
  useDataWorks,
  type DataWorksProject,
  type DataWorksTable,
  type DataWorksTableDescription,
  type ListState,
} from "@/context/dataworks"
import { useLanguage } from "@/context/language"
import { DataWorksShell, ListStateBanner } from "@/pages/dataworks/shell"

const MAX_SQL_CHARS = 4000

export default function ExplorerPage() {
  const dataworks = useDataWorks()
  const language = useLanguage()
  const [projects, setProjects] = createSignal<DataWorksProject[]>([])
  const [projectState, setProjectState] = createSignal<ListState>("idle")
  const [projectID, setProjectID] = createSignal("")
  const [tableQuery, setTableQuery] = createSignal("")
  const [tables, setTables] = createSignal<DataWorksTable[]>([])
  const [tableState, setTableState] = createSignal<ListState>("idle")
  const [selectedTable, setSelectedTable] = createSignal<DataWorksTable | undefined>()
  const [tableDetail, setTableDetail] = createSignal<DataWorksTableDescription | undefined>()
  const [sql, setSql] = createSignal("SELECT 1 LIMIT 10")
  const [sqlResult, setSqlResult] = createSignal<string>("")
  const [sqlState, setSqlState] = createSignal<ListState>("idle")

  function selectedProject(): DataWorksProject | undefined {
    const id = projectID()
    return projects().find((p) => String(p.projectId ?? p.projectID ?? p.id ?? "") === id)
  }

  function projectNameOf(project: DataWorksProject | undefined): string | undefined {
    if (!project) return undefined
    const name = project.projectName ?? project.name
    return typeof name === "string" && name ? name : undefined
  }

  async function loadProjects() {
    const connectionID = dataworks.selectedConnectionID()
    if (!connectionID) {
      setProjectState("empty")
      setProjects([])
      return
    }
    setProjectState("loading")
    const region = dataworks.selectedConnection()?.region
    const result = await dataworks.listProjects(connectionID, region)
    if (!result.ok) {
      setProjectState(result.status === 429 ? "rate_limit" : "error")
      return
    }
    setProjects(result.data)
    setProjectState(result.data.length ? "ready" : "empty")
    if (result.data[0]) {
      const id = String(result.data[0].projectId ?? result.data[0].projectID ?? result.data[0].id ?? "")
      setProjectID(id)
    }
  }

  async function searchTables() {
    const connectionID = dataworks.selectedConnectionID()
    const pid = projectID()
    if (!connectionID || !pid) {
      setTableState("empty")
      setTables([])
      setSelectedTable(undefined)
      setTableDetail(undefined)
      return
    }
    setTableState("loading")
    const project = selectedProject()
    const result = await dataworks.listTables(connectionID, pid, {
      keyword: tableQuery().trim() || undefined,
      projectName: projectNameOf(project),
      region: dataworks.selectedConnection()?.region,
    })
    if (!result.ok) {
      setTables([])
      setSelectedTable(undefined)
      setTableDetail(undefined)
      setTableState(result.status === 429 ? "rate_limit" : "error")
      return
    }
    setTables(result.data)
    setTableState(result.data.length ? "ready" : "empty")
    const first = result.data[0]
    setSelectedTable(first)
    if (first) void loadTableDetail(first)
    else setTableDetail(undefined)
  }

  async function loadTableDetail(row: DataWorksTable) {
    const connectionID = dataworks.selectedConnectionID()
    const pid = projectID()
    if (!connectionID || !pid) return
    setSelectedTable(row)
    const project = selectedProject()
    const result = await dataworks.describeTable(connectionID, pid, row.name, {
      projectName: projectNameOf(project) ?? (typeof row.projectName === "string" ? row.projectName : undefined),
      region: dataworks.selectedConnection()?.region,
    })
    if (!result.ok) {
      // Keep list selection; surface schema as best-effort from list row.
      setTableDetail({
        name: row.name,
        schema: row.schema,
        partition: row.partition,
        columns: [],
      })
      return
    }
    setTableDetail(result.data)
  }

  async function runSql() {
    const text = sql().trim()
    if (!text) return
    if (text.length > MAX_SQL_CHARS) {
      setSqlState("error")
      setSqlResult(language.t("dataworks.explorer.sql.tooLong", { max: String(MAX_SQL_CHARS) }))
      return
    }
    const connectionID = dataworks.selectedConnectionID()
    const pid = projectID()
    const project = selectedProject()
    const name = projectNameOf(project)
    if (!connectionID || !pid) {
      setSqlState("error")
      setSqlResult("connection and project required")
      return
    }
    if (!name) {
      setSqlState("error")
      setSqlResult(
        "project name required for live SQL (select a project from listProjects that includes MaxCompute project name, not only numeric id)",
      )
      return
    }
    setSqlState("loading")
    const result = await dataworks.runSql({
      connectionID,
      projectID: pid,
      sql: text,
      projectName: name,
      region: dataworks.selectedConnection()?.region,
      maxRows: 1000,
      timeoutMs: 30_000,
    })
    if (!result.ok) {
      setSqlState(result.status === 429 ? "rate_limit" : "error")
      setSqlResult(result.error)
      return
    }
    setSqlResult(JSON.stringify(result.data, null, 2))
    setSqlState("ready")
  }

  return (
    <DataWorksShell>
      <div class="flex flex-col gap-4 max-w-5xl" data-page="dataworks-explorer">
        <h1 class="text-16-medium text-text-strong">{language.t("dataworks.nav.explorer")}</h1>
        <div class="flex flex-wrap gap-3 items-end">
          <ConnectionSelector onChange={() => void loadProjects()} />
          <Button variant="secondary" size="small" onClick={() => void loadProjects()}>
            {language.t("dataworks.explorer.projects.load")}
          </Button>
        </div>
        <ListStateBanner state={projectState} onRetry={() => void loadProjects()} />
        <Show when={projectState() === "ready"}>
          <label class="flex flex-col gap-1 max-w-sm">
            <span class="text-12-regular text-text-weak">{language.t("dataworks.explorer.project")}</span>
            <select
              class="text-14-regular px-3 py-2 rounded-md border border-[color:var(--dwa-border)] bg-transparent"
              value={projectID()}
              onChange={(e) => setProjectID(e.currentTarget.value)}
            >
              <For each={projects()}>
                {(item) => (
                  <option value={String(item.projectId ?? item.projectID ?? item.id ?? "")}>
                    {String(item.projectName ?? item.name ?? item.projectId ?? item.id)}
                  </option>
                )}
              </For>
            </select>
          </label>
        </Show>

        <div class="flex flex-wrap gap-2 items-end">
          <label class="flex flex-col gap-1 flex-1 min-w-40">
            <span class="text-12-regular text-text-weak">{language.t("dataworks.explorer.tables.search")}</span>
            <input
              class="text-14-regular px-3 py-2 rounded-md border border-[color:var(--dwa-border)] bg-transparent"
              value={tableQuery()}
              onInput={(e) => setTableQuery(e.currentTarget.value)}
            />
          </label>
          <Button variant="secondary" size="small" onClick={() => void searchTables()}>
            {language.t("dataworks.explorer.tables.submit")}
          </Button>
        </div>
        <ListStateBanner state={tableState} onRetry={() => void searchTables()} />
        <Show when={tableState() === "ready"}>
          <div class="grid md:grid-cols-2 gap-3">
            <ul class="dwa-card p-2 flex flex-col gap-1 max-h-64 overflow-auto" data-list="tables">
              <For each={tables()}>
                {(row) => (
                  <li>
                    <button
                      type="button"
                      class="w-full text-left text-14-regular px-2 py-1 rounded hover:bg-black/5"
                      data-active={selectedTable()?.name === row.name ? "true" : "false"}
                      onClick={() => void loadTableDetail(row)}
                    >
                      {row.name}
                    </button>
                  </li>
                )}
              </For>
            </ul>
            <Show when={tableDetail() ?? selectedTable()}>
              {(table) => (
                <div class="dwa-card p-3 flex flex-col gap-1 text-12-regular" data-panel="schema">
                  <div>
                    <span class="text-text-weak">{language.t("dataworks.explorer.schema")}: </span>
                    {table().schema}
                  </div>
                  <div>
                    <span class="text-text-weak">{language.t("dataworks.explorer.partition")}: </span>
                    {table().partition}
                  </div>
                  <Show when={"columns" in table() && Array.isArray((table() as DataWorksTableDescription).columns)}>
                    <ul class="mt-2 flex flex-col gap-0.5 max-h-40 overflow-auto" data-list="columns">
                      <For each={(table() as DataWorksTableDescription).columns ?? []}>
                        {(col) => (
                          <li>
                            {col.name}
                            <span class="text-text-weak"> {col.type}</span>
                          </li>
                        )}
                      </For>
                    </ul>
                  </Show>
                </div>
              )}
            </Show>
          </div>
        </Show>

        <section class="flex flex-col gap-2">
          <h2 class="text-14-medium">{language.t("dataworks.explorer.sql.title")}</h2>
          <textarea
            class="text-14-regular font-mono px-3 py-2 rounded-md border border-[color:var(--dwa-border)] bg-transparent min-h-28"
            value={sql()}
            maxlength={MAX_SQL_CHARS}
            onInput={(e) => setSql(e.currentTarget.value)}
          />
          <Button variant="primary" class="dwa-btn-primary self-start" size="small" onClick={() => void runSql()}>
            {language.t("dataworks.explorer.sql.run")}
          </Button>
          <ListStateBanner state={sqlState} />
          <Show when={sqlResult()}>
            <pre
              class="dwa-card p-3 text-12-regular font-mono overflow-auto max-h-64"
              data-panel="sql-results"
              tabindex="0"
            >
              {sqlResult()}
            </pre>
          </Show>
        </section>
      </div>
    </DataWorksShell>
  )
}
