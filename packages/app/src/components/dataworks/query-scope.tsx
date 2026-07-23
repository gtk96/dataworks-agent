import { For, Show, createMemo, type JSX } from "solid-js"
import { A } from "@solidjs/router"
import { ConnectionSelector } from "@/components/dataworks/connection-selector"
import { useDataWorks } from "@/context/dataworks"
import { useLanguage } from "@/context/language"
import { projectKey, projectLabel } from "./query-scope-utils"
import "./scope-bar.css"

export { projectKey, projectLabel }

export function QueryScope(props: {
  compact?: boolean
  showMode?: boolean
  class?: string
}): JSX.Element {
  const dataworks = useDataWorks()
  const language = useLanguage()
  const projectState = createMemo(() => dataworks.projectState())
  const writeEnabled = createMemo(() => dataworks.selectedConnection()?.writeEnabled === true)
  const projects = createMemo(() => dataworks.projects())

  return (
    <div
      data-component="dataworks-query-scope"
      data-mode={props.compact ? "compact" : "standard"}
      data-state={projectState()}
      class={`dwa-scope ${props.compact ? "dwa-scope-compact" : "dwa-scope-standard"} ${props.class ?? ""}`}
    >
      <ConnectionSelector compact={props.compact} />
      <label class="dwa-scope-field">
        <span class="dwa-scope-label">{language.t("dataworks.scope.project")}</span>
        <select
          data-component="dataworks-project-selector"
          class="dwa-select"
          disabled={projectState() === "loading" || !dataworks.selectedConnectionID()}
          value={dataworks.selectedProjectID() ?? ""}
          onChange={(event) => {
            const id = event.currentTarget.value || undefined
            dataworks.setSelectedProjectID(id)
          }}
        >
          <Show when={projects().length === 0}>
            <option value="">{language.t("dataworks.scope.project.empty")}</option>
          </Show>
          <For each={projects()}>
            {(item) => <option value={projectKey(item)}>{projectLabel(item)}</option>}
          </For>
        </select>
        <Show when={projectState() === "loading" || projectState() === "error" || projectState() === "rate_limit"}>
          <span class="dwa-scope-hint" data-slot="project-state">
            <Show when={projectState() === "loading"}>{language.t("dataworks.state.loading")}</Show>
            <Show when={projectState() === "error"}>{language.t("dataworks.state.error")}</Show>
            <Show when={projectState() === "rate_limit"}>{language.t("dataworks.state.rateLimit")}</Show>
          </span>
        </Show>
      </label>
      <Show when={!props.compact || props.showMode}>
        <div class="dwa-scope-meta">
          <span
            data-slot="write-badge"
            class="dwa-chip"
            data-tone={writeEnabled() ? "warning" : "neutral"}
          >
            {writeEnabled()
              ? language.t("dataworks.connection.write.on")
              : language.t("dataworks.connection.write.off")}
          </span>
          <Show when={!props.compact}>
            <A href="/dataworks/connections" class="dwa-link">
              {language.t("dataworks.scope.manage")}
            </A>
          </Show>
        </div>
      </Show>
    </div>
  )
}
