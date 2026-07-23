import { For, Show, createEffect, createMemo, createSignal, onCleanup, onMount, type JSX } from "solid-js"
import { createStore } from "solid-js/store"
import { useParams } from "@solidjs/router"
import type { Todo } from "@opencode-ai/sdk/v2"
import {
  SQL_ARTIFACT_EVENT,
  isSqlArtifactDetail,
} from "@opencode-ai/session-ui/sql-artifact-event"
import {
  useDataWorks,
  type DataWorksProject,
  type DataWorksTable,
  type DataWorksTableDescription,
  type ListState,
} from "@/context/dataworks"
import { useLanguage } from "@/context/language"
import { StudioPromptProvider } from "@/context/studio-prompt"
import { useServerSync } from "@/context/server-sync"
import { useServerSDK } from "@/context/server-sdk"
import { Persist, persisted } from "@/utils/persist"
import { ArtifactWorkspace } from "./artifact-workspace"
import { ResourceExplorer } from "./resource-explorer"
import {
  acceptScopedResult,
  clampAgentWidth,
  clampResourceWidth,
  createResultPreview,
  createSqlRequest,
  editSqlDocument,
  openSqlArtifact,
  requiresSqlOverwriteConfirmation,
  resizeAgentWidth,
  resizeResourceWidth,
  responsiveWorkbench,
  serializeResultPreviewContext,
  sqlRequestIsCurrent,
  scopeKey,
  type ScopedSqlResult,
  type SqlArtifact,
  type SqlDocument,
  type WorkbenchScope,
  type WorkbenchTab,
} from "./workbench-state"
import "./studio-workbench.css"

export function StudioWorkbench(props: { agent: JSX.Element; onMenu?: () => void }): JSX.Element {
  const dataworks = useDataWorks()
  const language = useLanguage()
  const params = useParams()
  const serverSync = useServerSync()
  const serverSDK = useServerSDK()
  const [ui, setUi] = persisted(
    Persist.window("dataworks.workbench"),
    createStore({
      activeTab: "sql" as WorkbenchTab,
      resourceWidth: 240,
      agentWidth: 420,
      resourceCollapsed: false,
      agentCollapsed: false,
    }),
  )
  const [document, setDocument] = createSignal<SqlDocument>(
    openSqlArtifact(undefined, { sql: "", title: language.t("dataworks.workbench.untitledQuery") }),
  )
  const [result, setResult] = createSignal<ScopedSqlResult>()
  const [selectedTable, setSelectedTable] = createSignal<DataWorksTable>()
  const [schema, setSchema] = createSignal<DataWorksTableDescription>()
  const [schemaState, setSchemaState] = createSignal<ListState>("idle")
  const [sqlState, setSqlState] = createSignal<ListState>("idle")
  const [running, setRunning] = createSignal(false)
  const [attachedPreview, setAttachedPreview] = createSignal<ReturnType<typeof createResultPreview>>()
  const [plan, setPlan] = createSignal<Todo[]>([])
  const [workbenchWidth, setWorkbenchWidth] = createSignal(1440)
  const [resourceOverlayOpen, setResourceOverlayOpen] = createSignal(false)
  const [agentOverlayOpen, setAgentOverlayOpen] = createSignal(false)
  const scope = createMemo<WorkbenchScope>(() => ({
    connectionID: dataworks.selectedConnectionID(),
    projectID: dataworks.selectedProjectID(),
    projectName: selectedProjectName(dataworks.selectedProject()),
    region: dataworks.selectedConnection()?.region,
  }))
  const responsive = createMemo(() => responsiveWorkbench(workbenchWidth()))
  const runEnabled = createMemo(() => !!createSqlRequest(document(), scope()) && !running())
  const resizeCleanups = new Set<() => void>()
  let previousScope = scopeKey(scope())
  let previousOverlay = false
  let sqlRequest = 0
  let workbench!: HTMLElement

  createEffect(() => {
    const sessionID = params.id
    if (!sessionID) {
      setPlan([])
      return
    }
    const session = serverSync().session.get(sessionID)
    if (!session) {
      setPlan([])
      return
    }
    const current = serverSDK()
    void current
      .createClient({ directory: session.directory, throwOnError: true })
      .session.todo({ sessionID })
      .then((result) => {
        if (params.id !== sessionID || serverSDK() !== current) return
        setPlan(result.data ?? [])
      })
      .catch(() => {
        if (params.id === sessionID && serverSDK() === current) setPlan([])
      })
  })

  createEffect(() => {
    const current = scopeKey(scope())
    if (current === previousScope) return
    sqlRequest++
    setRunning(false)
    setSqlState("idle")
    previousScope = current
    setResult(undefined)
    setSelectedTable(undefined)
    setSchema(undefined)
    setSchemaState("idle")
    setAttachedPreview(undefined)
  })

  createEffect(() => {
    const overlay = responsive().agentOverlay
    if (overlay && !previousOverlay) {
      setResourceOverlayOpen(false)
      setAgentOverlayOpen(false)
    }
    previousOverlay = overlay
  })

  onMount(() => {
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width
      if (width) setWorkbenchWidth(width)
    })
    const openSql = (event: Event) => {
      if (!(event instanceof CustomEvent) || !isSqlArtifactDetail(event.detail)) return
      openArtifact({ sql: event.detail.sql, sourceMessageID: event.detail.sourceMessageID })
    }
    setWorkbenchWidth(workbench.clientWidth || window.innerWidth)
    observer.observe(workbench)
    window.addEventListener(SQL_ARTIFACT_EVENT, openSql)
    onCleanup(() => {
      observer.disconnect()
      window.removeEventListener(SQL_ARTIFACT_EVENT, openSql)
    })
  })

  onCleanup(() => resizeCleanups.forEach((cleanup) => cleanup()))

  function openArtifact(artifact: SqlArtifact) {
    const current = document()
    if (
      requiresSqlOverwriteConfirmation(current, artifact) &&
      !window.confirm(language.t("dataworks.workbench.overwriteConfirm"))
    )
      return
    sqlRequest++
    setRunning(false)
    setSqlState("idle")
    setDocument(openSqlArtifact(current, artifact))
    setResult(undefined)
    setAttachedPreview(undefined)
    setUi("activeTab", "sql")
  }

  async function runSql() {
    const current = document()
    const requested = scope()
    const request = createSqlRequest(current, requested)
    if (!request) return
    const requestID = ++sqlRequest
    setRunning(true)
    setSqlState("loading")
    const response = await dataworks.runSql(request).catch(() => undefined)
    if (!sqlRequestIsCurrent(current.id, document().id, requested, scope(), requestID, sqlRequest)) return
    setRunning(false)
    if (!response) {
      setSqlState("error")
      return
    }
    if (!response.ok) {
      setSqlState(response.status === 429 ? "rate_limit" : "error")
      return
    }
    const accepted = acceptScopedResult(scope(), requested, response.data)
    if (!accepted) {
      setSqlState("idle")
      return
    }
    setResult({ documentID: current.id, scope: requested, result: accepted, sqlVersion: current.editedVersion })
    setDocument((value) => ({ ...value, executedVersion: current.editedVersion }))
    setUi("activeTab", "results")
    setSqlState("ready")
  }

  function selectTable(table: DataWorksTable, description: DataWorksTableDescription) {
    setSelectedTable(table)
    setSchema(description)
    const state = description.state
    setSchemaState(
      state === "loading"
        ? "loading"
        : state === "rate_limit"
          ? "rate_limit"
          : state === "incomplete" || description.incomplete === true
            ? "partial"
            : "ready",
    )
    setUi("activeTab", "schema")
  }

  function toggleResource() {
    if (responsive().resourceOverlay) {
      setResourceOverlayOpen((value) => !value)
      return
    }
    setUi("resourceCollapsed", (value) => !value)
  }

  function toggleAgent() {
    if (responsive().agentOverlay) {
      setAgentOverlayOpen((value) => !value)
      return
    }
    setUi("agentCollapsed", (value) => !value)
  }

  function startResize(panel: "resource" | "agent", event: PointerEvent) {
    event.preventDefault()
    const originX = event.clientX
    const originWidth = panel === "resource" ? ui.resourceWidth : ui.agentWidth
    const move = (next: PointerEvent) => {
      const delta = panel === "resource" ? next.clientX - originX : originX - next.clientX
      if (panel === "resource") {
        setUi("resourceWidth", clampResourceWidth(originWidth + delta))
        return
      }
      setUi("agentWidth", clampAgentWidth(originWidth + delta))
    }
    const cleanup = () => {
      window.removeEventListener("pointermove", move)
      window.removeEventListener("pointerup", cleanup)
      resizeCleanups.delete(cleanup)
    }
    resizeCleanups.add(cleanup)
    window.addEventListener("pointermove", move)
    window.addEventListener("pointerup", cleanup)
  }

  const resourceExpanded = () =>
    responsive().resourceOverlay ? resourceOverlayOpen() : !ui.resourceCollapsed
  const agentExpanded = () => (responsive().agentOverlay ? agentOverlayOpen() : !ui.agentCollapsed)
  const agentPrompt = {
    peek: () => {
      const preview = attachedPreview()
      if (!preview) return
      return { key: preview, text: serializeResultPreviewContext(scope(), preview) }
    },
    consume: (key: unknown) => {
      if (attachedPreview() !== key) return
      setAttachedPreview(undefined)
    },
  }

  return (
    <section
      ref={workbench}
      data-component="studio-workbench"
      data-resource-expanded={resourceExpanded() ? "true" : "false"}
      data-agent-expanded={agentExpanded() ? "true" : "false"}
      data-resource-overlay={responsive().resourceOverlay ? "true" : "false"}
      data-agent-overlay={responsive().agentOverlay ? "true" : "false"}
      style={`--studio-resource-width:${ui.resourceWidth}px;--studio-agent-width:${ui.agentWidth}px`}
    >
      <header data-slot="workbench-toolbar">
        <Show when={props.onMenu}>
          <button
            type="button"
            data-slot="workbench-menu"
            aria-label={language.t("dataworks.workbench.navigation")}
            onClick={() => props.onMenu?.()}
          >
            {language.t("dataworks.workbench.menu")}
          </button>
        </Show>
        <button type="button" aria-expanded={resourceExpanded()} onClick={toggleResource}>
          {language.t("dataworks.workbench.resources")}
        </button>
        <div data-slot="workbench-scope">
          <span>{dataworks.selectedConnection()?.name ?? language.t("dataworks.workbench.noConnection")}</span>
          <span>{scope().projectName ?? language.t("dataworks.workbench.noProject")}</span>
          <span>{scope().region ?? language.t("dataworks.workbench.noRegion")}</span>
        </div>
        <button type="button" aria-expanded={agentExpanded()} onClick={toggleAgent}>
          {language.t("dataworks.workbench.agent")}
        </button>
      </header>

      <div data-slot="workbench-body">
        <div data-slot="resource-panel">
          <ResourceExplorer selectedTable={selectedTable()} onSelectTable={selectTable} onOpenSql={openArtifact} />
        </div>
        <div
          data-slot="resource-resizer"
          role="separator"
          aria-label={language.t("dataworks.workbench.resizeResources")}
          aria-orientation="vertical"
          aria-valuemin="200"
          aria-valuemax="360"
          aria-valuenow={ui.resourceWidth}
          tabindex={resourceExpanded() && !responsive().resourceOverlay ? 0 : -1}
          onPointerDown={(event) => startResize("resource", event)}
          onKeyDown={(event) => {
            const width = resizeResourceWidth(ui.resourceWidth, event.key)
            if (width === ui.resourceWidth) return
            event.preventDefault()
            setUi("resourceWidth", width)
          }}
        />

        <ArtifactWorkspace
          activeTab={ui.activeTab}
          document={document()}
          result={result()}
          schema={schema()}
          schemaState={schemaState()}
          running={running()}
          runEnabled={runEnabled()}
          plan={
            <Show when={plan().length > 0} fallback={<p>{language.t("dataworks.workbench.noPlan")}</p>}>
              <ol data-component="workbench-plan">
                <For each={plan()}>
                  {(item) => (
                    <li data-state={item.status}>
                      <span aria-hidden="true">{item.status === "completed" ? "✓" : item.status === "in_progress" ? "•" : "○"}</span>
                      <span>{item.content}</span>
                    </li>
                  )}
                </For>
              </ol>
            </Show>
          }
          onTabChange={(tab) => setUi("activeTab", tab)}
          onSqlChange={(sql) => setDocument((current) => editSqlDocument(current, sql))}
          onRun={() => void runSql()}
          onAttachPreview={(preview) => setAttachedPreview(preview)}
        />

        <div
          data-slot="agent-resizer"
          role="separator"
          aria-label={language.t("dataworks.workbench.resizeAgent")}
          aria-orientation="vertical"
          aria-valuemin="320"
          aria-valuemax="600"
          aria-valuenow={ui.agentWidth}
          tabindex={agentExpanded() && !responsive().agentOverlay ? 0 : -1}
          onPointerDown={(event) => startResize("agent", event)}
          onKeyDown={(event) => {
            const width = resizeAgentWidth(ui.agentWidth, event.key)
            if (width === ui.agentWidth) return
            event.preventDefault()
            setUi("agentWidth", width)
          }}
        />
        <aside data-slot="agent-panel" aria-label={language.t("dataworks.workbench.agent")}>
          <div data-slot="agent-context">
            <span>{scope().projectName ?? language.t("dataworks.workbench.noProjectSelected")}</span>
            <Show when={attachedPreview()}>
              {(preview) => (
                <button
                  type="button"
                  data-component="agent-context-chip"
                  data-rows={preview().rows.length}
                  data-columns={preview().columns.length}
                  onClick={() => setAttachedPreview(undefined)}
                >
                  {language.t("dataworks.workbench.resultPreview", {
                    rows: preview().rows.length,
                    columns: preview().columns.length,
                  })}
                </button>
              )}
            </Show>
          </div>
          <StudioPromptProvider value={agentPrompt}>
            <div data-slot="agent-content">{props.agent}</div>
          </StudioPromptProvider>
        </aside>
      </div>

      <footer data-slot="workbench-status" data-state={sqlState()}>
        <span>
          {scope().connectionID
            ? language.t("dataworks.workbench.connectedScope")
            : language.t("dataworks.workbench.selectConnection")}
        </span>
        <span>{language.t(`dataworks.workbench.status.${sqlState()}` as "dataworks.workbench.status.idle")}</span>
      </footer>
    </section>
  )
}

function selectedProjectName(project: DataWorksProject | undefined) {
  const value = project?.projectName ?? project?.name
  return typeof value === "string" && value.trim() ? value : undefined
}
