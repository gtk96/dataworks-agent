import { For, Show, createMemo, type JSX } from "solid-js"
import { A } from "@solidjs/router"
import { ConnectionSelector } from "@/components/dataworks/connection-selector"
import { useDataWorks, type DataWorksProject } from "@/context/dataworks"
import { useLanguage } from "@/context/language"
import "./scope-bar.css"

export function projectKey(project: DataWorksProject): string {
  if (project.projectId !== undefined && project.projectId !== null && project.projectId !== "") {
    return String(project.projectId)
  }
  if (project.id !== undefined && project.id !== null && project.id !== "") {
    return String(project.id)
  }
  return ""
}

export function projectLabel(project: DataWorksProject): string {
  const id = projectKey(project)
  const name =
    typeof project.projectName === "string"
      ? project.projectName
      : typeof project.name === "string"
        ? project.name
        : undefined
  if (name && id) return `${name} (${id})`
  if (name) return name
  if (id) return id
  return "project"
}

export function DataWorksScopeBar(props: {
  compact?: boolean
  class?: string
}): JSX.Element {
  const dataworks = useDataWorks()
  const language = useLanguage()
  const projects = createMemo(() => dataworks.projects())
  const projectState = createMemo(() => dataworks.projectState())
  const writeEnabled = createMemo(() => dataworks.selectedConnection()?.writeEnabled === true)

  return (
    <div
      data-component="dataworks-scope-bar"
      data-state={dataworks.connectionState()}
      class={`dwa-scope dwa-scope-compact grid grid-cols-1 md:grid-cols-[2fr_2fr_1fr] gap-3 items-end min-w-0 ${props.class ?? ""}`}
    >
      <ConnectionSelector compact={props.compact} />
      <label class="flex flex-col gap-1 min-w-0">
        <Show when={!props.compact}>
          <span class="text-12-regular text-text-weak">{language.t("dataworks.scope.project")}</span>
        </Show>
        <select
          data-component="dataworks-project-selector"
          class="dwa-field text-14-regular"
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
        <span class="text-12-regular text-text-weak" data-slot="project-state">
          <Show when={projectState() === "loading"}>{language.t("dataworks.state.loading")}</Show>
          <Show when={projectState() === "error"}>{language.t("dataworks.state.error")}</Show>
          <Show when={projectState() === "rate_limit"}>{language.t("dataworks.state.rateLimit")}</Show>
        </span>
      </label>
      <div class="flex items-center gap-2 justify-between">
        <span
          data-slot="write-badge"
          class="dwa-status-tag"
          classList={{
            "dwa-status-tag-on": writeEnabled(),
            "dwa-status-warning": writeEnabled(),
          }}
        >
          {writeEnabled()
            ? language.t("dataworks.connection.write.on")
            : language.t("dataworks.connection.write.off")}
        </span>
        <A href="/dataworks/connections" class="dwa-toolbar-link text-12-regular">
          {language.t("dataworks.scope.manage")}
        </A>
      </div>
    </div>
  )
}
