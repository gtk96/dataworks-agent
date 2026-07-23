import { For, Match, Show, Switch, type JSX } from "solid-js"
import type { DataWorksTableDescription, ListState } from "@/context/dataworks"
import { ResultsGrid } from "./results-grid"
import {
  createResultPreview,
  type ScopedSqlResult,
  type SqlDocument,
  type WorkbenchTab,
} from "./workbench-state"

const WORKBENCH_TABS = ["plan", "sql", "results", "schema"] as const

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
  const stale = () => !!props.result && props.document.editedVersion !== props.result.sqlVersion

  return (
    <main data-component="artifact-workspace">
      <div role="tablist" aria-label="Artifact workspace" data-slot="artifact-tabs">
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
            >
              {tab}
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
            <Show when={props.plan} fallback={<p>No active plan for this session.</p>}>
              {props.plan}
            </Show>
          </Match>

          <Match when={props.activeTab === "sql"}>
            <div data-slot="sql-toolbar">
              <span>{props.document.title ?? "SQL scratchpad"}</span>
              <button
                type="button"
                data-action="run-sql"
                disabled={!props.runEnabled || props.running}
                aria-busy={props.running}
                onClick={() => props.onRun()}
              >
                {props.running ? "Running..." : "Run"}
              </button>
            </div>
            <textarea
              aria-label="SQL editor"
              spellcheck={false}
              value={props.document.sql}
              onInput={(event) => props.onSqlChange(event.currentTarget.value)}
            />
          </Match>

          <Match when={props.activeTab === "results"}>
            <Show when={props.result} fallback={<p>Run a read-only query to see results.</p>}>
              {(result) => (
                <>
                  <ResultsGrid result={result().result} stale={stale()} />
                  <button
                    type="button"
                    data-action="attach-result-preview"
                    onClick={() => props.onAttachPreview(createResultPreview(result().result))}
                  >
                    Attach preview to Agent
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
                            <th scope="col">Column</th>
                            <th scope="col">Type</th>
                            <th scope="col">Comment</th>
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
                  <p role="status">Loading Schema...</p>
                </Match>
                <Match when={props.schemaState === "partial" || props.schema?.incomplete === true}>
                  <p role="status">Schema details are incomplete.</p>
                </Match>
                <Match when={props.schemaState === "rate_limit"}>
                  <p role="status">Schema requests are rate limited.</p>
                </Match>
                <Match when={props.schemaState === "error"}>
                  <p role="alert">Schema could not be loaded.</p>
                </Match>
                <Match when={!props.schema && (props.schemaState === "idle" || props.schemaState === "empty")}>
                  <p>Select a table to inspect its Schema.</p>
                </Match>
              </Switch>
            </section>
          </Match>
        </Switch>
      </section>
    </main>
  )
}
