import { For, Match, Show, Switch, type JSX } from "solid-js"
import type { DataWorksTableDescription, ListState } from "@/context/dataworks"
import { useLanguage } from "@/context/language"
import { ResultsGrid } from "./results-grid"
import {
  createResultPreview,
  resultIsStale,
  type ScopedSqlResult,
  type SqlDocument,
  type WorkbenchTab,
} from "./workbench-state"

const WORKBENCH_TABS = ["plan", "sql", "results", "schema"] as const
const WORKBENCH_TAB_LABELS = {
  plan: "dataworks.workbench.tab.plan",
  sql: "dataworks.workbench.tab.sql",
  results: "dataworks.workbench.tab.results",
  schema: "dataworks.workbench.tab.schema",
} as const

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

export function ArtifactWorkspace(props: ArtifactWorkspaceProps): JSX.Element {
  const language = useLanguage()
  const stale = () => !!props.result && resultIsStale(props.document, props.result)

  return (
    <main data-component="artifact-workspace">
      <div role="tablist" aria-label={language.t("dataworks.workbench.workspace")} data-slot="artifact-tabs">
        <For each={WORKBENCH_TABS}>
          {(tab) => (
            <button
              id={`workbench-tab-${tab}`}
              type="button"
              role="tab"
              aria-controls={`workbench-panel-${tab}`}
              aria-selected={props.activeTab === tab}
              tabindex={props.activeTab === tab ? 0 : -1}
              onClick={() => props.onTabChange(tab)}
              onKeyDown={(event) => {
                const next = keyboardTab(tab, event.key)
                if (!next) return
                event.preventDefault()
                props.onTabChange(next)
                queueMicrotask(() => document.getElementById(`workbench-tab-${next}`)?.focus())
              }}
            >
              {language.t(WORKBENCH_TAB_LABELS[tab])}
            </button>
          )}
        </For>
      </div>

      <section
        id={`workbench-panel-${props.activeTab}`}
        role="tabpanel"
        aria-labelledby={`workbench-tab-${props.activeTab}`}
        data-panel={props.activeTab}
      >
        <Switch>
          <Match when={props.activeTab === "plan"}>
            <Show when={props.plan} fallback={<p>{language.t("dataworks.workbench.noPlan")}</p>}>
              {props.plan}
            </Show>
          </Match>

          <Match when={props.activeTab === "sql"}>
            <div data-slot="sql-toolbar">
              <span>{props.document.title ?? language.t("dataworks.workbench.sqlScratchpad")}</span>
              <button
                type="button"
                data-action="run-sql"
                disabled={!props.runEnabled || props.running}
                aria-busy={props.running}
                onClick={() => props.onRun()}
              >
                {props.running
                  ? language.t("dataworks.workbench.running")
                  : language.t("dataworks.workbench.run")}
              </button>
            </div>
            <textarea
              aria-label={language.t("dataworks.workbench.sqlEditor")}
              spellcheck={false}
              value={props.document.sql}
              onInput={(event) => props.onSqlChange(event.currentTarget.value)}
            />
          </Match>

          <Match when={props.activeTab === "results"}>
            <Show when={props.result} fallback={<p>{language.t("dataworks.workbench.emptyResults")}</p>}>
              {(result) => (
                <>
                  <ResultsGrid result={result().result} stale={stale()} />
                  <button
                    type="button"
                    data-action="attach-result-preview"
                    onClick={() => props.onAttachPreview(createResultPreview(result().result))}
                  >
                    {language.t("dataworks.workbench.attachPreview")}
                  </button>
                </>
              )}
            </Show>
          </Match>

          <Match when={props.activeTab === "schema"}>
            <section data-component="workbench-schema" data-state={props.schemaState}>
              <Show when={props.schema}>
                {(schema) => (
                  <>
                    <header>
                      <strong>{schema().name}</strong>
                      <Show when={schema().projectName}>
                        <span>{schema().projectName}</span>
                      </Show>
                    </header>
                    <Show when={schema().comment}>
                      <p>{schema().comment}</p>
                    </Show>
                    <Show when={schema().columns.length > 0}>
                      <table>
                        <thead>
                          <tr>
                            <th scope="col">{language.t("dataworks.workbench.column")}</th>
                            <th scope="col">{language.t("dataworks.workbench.type")}</th>
                            <th scope="col">{language.t("dataworks.workbench.comment")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          <For each={schema().columns}>
                            {(column) => (
                              <tr>
                                <td>{column.name}</td>
                                <td>{column.type}</td>
                                <td>{column.comment ?? ""}</td>
                              </tr>
                            )}
                          </For>
                        </tbody>
                      </table>
                    </Show>
                  </>
                )}
              </Show>
              <Switch>
                <Match when={props.schemaState === "loading"}>
                  <p role="status">{language.t("dataworks.workbench.schemaLoading")}</p>
                </Match>
                <Match when={props.schemaState === "partial" || props.schema?.incomplete === true}>
                  <p role="status">{language.t("dataworks.workbench.schemaPartial")}</p>
                </Match>
                <Match when={props.schemaState === "rate_limit"}>
                  <p role="status">{language.t("dataworks.workbench.schemaRateLimit")}</p>
                </Match>
                <Match when={props.schemaState === "error"}>
                  <p role="alert">{language.t("dataworks.workbench.schemaError")}</p>
                </Match>
                <Match when={!props.schema && (props.schemaState === "idle" || props.schemaState === "empty")}>
                  <p>{language.t("dataworks.workbench.schemaEmpty")}</p>
                </Match>
              </Switch>
            </section>
          </Match>
        </Switch>
      </section>
    </main>
  )
}

function keyboardTab(tab: WorkbenchTab, key: string) {
  if (key === "Home") return WORKBENCH_TABS[0]
  if (key === "End") return WORKBENCH_TABS.at(-1)
  const index = WORKBENCH_TABS.indexOf(tab)
  if (key === "ArrowLeft") return WORKBENCH_TABS[(index - 1 + WORKBENCH_TABS.length) % WORKBENCH_TABS.length]
  if (key === "ArrowRight") return WORKBENCH_TABS[(index + 1) % WORKBENCH_TABS.length]
}
