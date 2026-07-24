import { For, Show, createEffect, createMemo, createSignal, type JSX } from "solid-js"
import { ConnectionSelector } from "@/components/dataworks/connection-selector"
import {
  useDataWorks,
  type DataWorksProject,
  type DataWorksTable,
  type DataWorksTableDescription,
  type ListState,
} from "@/context/dataworks"
import { useLanguage } from "@/context/language"
import type { SqlArtifact, WorkbenchScope } from "./workbench-state"
import { scopeKey } from "./workbench-state"

export function tableSqlArtifact(table: Pick<DataWorksTable, "name">): SqlArtifact {
  return { sql: `SELECT * FROM ${table.name} LIMIT 100`, title: table.name }
}

export function scopeRequestIsCurrent(
  requested: string,
  current: WorkbenchScope,
  requestID: number,
  currentRequestID: number,
) {
  if (requested !== scopeKey(current)) return false
  return requestID === currentRequestID
}

export function ResourceExplorer(props: {
  selectedTable?: DataWorksTable
  onSelectTable: (table: DataWorksTable, description: DataWorksTableDescription) => void
  onOpenSql: (artifact: SqlArtifact) => void
}): JSX.Element {
  const dataworks = useDataWorks()
  const language = useLanguage()
  const [tables, setTables] = createSignal<DataWorksTable[]>([])
  const [tableState, setTableState] = createSignal<ListState>("idle")
  let tableRequest = 0
  let schemaRequest = 0
  const scope = createMemo<WorkbenchScope>(() => ({
    connectionID: dataworks.selectedConnectionID(),
    projectID: dataworks.selectedProjectID(),
    projectName: projectName(dataworks.selectedProject()),
    region: dataworks.selectedConnection()?.region,
  }))

  createEffect(() => {
    const requested = scope()
    const requestID = ++tableRequest
    schemaRequest += 1
    setTables([])
    if (!requested.connectionID || !requested.projectID || !requested.projectName) {
      setTableState("empty")
      return
    }
    setTableState("loading")
    void loadTables(requested, requestID)
  })

  async function loadTables(requested: WorkbenchScope, requestID: number) {
    const result = await dataworks.listTables(requested.connectionID!, requested.projectID!, {
      projectName: requested.projectName,
      region: requested.region,
    })
    if (!scopeRequestIsCurrent(scopeKey(requested), scope(), requestID, tableRequest)) return
    if (!result.ok) {
      setTableState(result.status === 429 ? "rate_limit" : "error")
      return
    }
    setTables(result.data)
    setTableState(result.data.length ? "ready" : "empty")
  }

  async function selectTable(table: DataWorksTable) {
    const requested = scope()
    if (!requested.connectionID || !requested.projectID) return
    const requestID = ++schemaRequest
    const fallback: DataWorksTableDescription = {
      name: table.name,
      schema: table.schema,
      projectName: table.projectName ?? requested.projectName,
      tableGuid: table.tableGuid,
      partition: table.partition,
      columns: [],
      incomplete: true,
      state: "loading",
    }
    props.onSelectTable(table, fallback)
    const result = await dataworks.describeTable(requested.connectionID, requested.projectID, table.name, {
      projectName: requested.projectName,
      region: requested.region,
    })
    if (!scopeRequestIsCurrent(scopeKey(requested), scope(), requestID, schemaRequest)) return
    if (!result.ok) {
      props.onSelectTable(table, { ...fallback, state: result.status === 429 ? "rate_limit" : "incomplete" })
      return
    }
    props.onSelectTable(table, result.data)
  }

  return (
    <aside data-component="workbench-resources" aria-label={language.t("dataworks.workbench.dataResources")}>
      <div data-slot="resource-scope">
        <ConnectionSelector compact />
        <label>
          <span>{language.t("dataworks.scope.project")}</span>
          <select
            data-component="dataworks-project-selector"
            disabled={dataworks.projectState() === "loading" || !dataworks.selectedConnectionID()}
            value={dataworks.selectedProjectID() ?? ""}
            onChange={(event) => dataworks.setSelectedProjectID(event.currentTarget.value || undefined)}
          >
            <Show when={dataworks.projects().length === 0}>
              <option value="">{language.t("dataworks.scope.project.empty")}</option>
            </Show>
            <For each={dataworks.projects()}>
              {(project) => (
                <option value={String(project.projectId ?? project.id)}>
                  {projectName(project) ?? String(project.projectId ?? project.id)}
                </option>
              )}
            </For>
          </select>
        </label>
      </div>

      <div data-slot="resource-tree" data-state={tableState()}>
        <Show when={tableState() === "loading"}>
          <p role="status">{language.t("dataworks.workbench.tablesLoading")}</p>
        </Show>
        <Show when={tableState() === "empty"}>
          <p>{language.t("dataworks.workbench.tablesEmpty")}</p>
        </Show>
        <Show when={tableState() === "rate_limit"}>
          <p role="status">{language.t("dataworks.workbench.tablesRateLimit")}</p>
        </Show>
        <Show when={tableState() === "error"}>
          <p role="alert">{language.t("dataworks.workbench.tablesError")}</p>
        </Show>
        <Show when={tableState() === "ready"}>
          <ul aria-label={language.t("dataworks.workbench.tables")}>
            <For each={tables()}>
              {(table) => (
                <li>
                  <button
                    type="button"
                    data-active={props.selectedTable?.name === table.name ? "true" : "false"}
                    onClick={() => void selectTable(table)}
                    onDblClick={() => props.onOpenSql(tableSqlArtifact(table))}
                  >
                    <span>{table.name}</span>
                    <Show when={table.type}>
                      <small>{table.type}</small>
                    </Show>
                  </button>
                </li>
              )}
            </For>
          </ul>
        </Show>
      </div>
    </aside>
  )
}

function projectName(project: DataWorksProject | undefined) {
  const value = project?.projectName ?? project?.name
  return typeof value === "string" && value.trim() ? value : undefined
}
