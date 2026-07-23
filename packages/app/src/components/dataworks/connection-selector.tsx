import { For, Show, createMemo, type JSX } from "solid-js"
import { useDataWorks, type DataConnection } from "@/context/dataworks"
import { useLanguage } from "@/context/language"

export function ConnectionSelector(props: {
  id?: string
  class?: string
  compact?: boolean
  disabled?: boolean
  onChange?: (connection: DataConnection | undefined) => void
}): JSX.Element {
  const dataworks = useDataWorks()
  const language = useLanguage()
  const options = createMemo(() => dataworks.connections())

  return (
    <label class={`dwa-scope-field ${props.class ?? ""}`}>
      <Show when={!props.compact}>
        <span class="dwa-scope-label">{language.t("dataworks.connection.selector.label")}</span>
      </Show>
      <select
        id={props.id}
        data-component="dataworks-connection-selector"
        class="dwa-select"
        disabled={props.disabled || dataworks.connectionState() === "loading"}
        value={dataworks.selectedConnectionID() ?? ""}
        onChange={(event) => {
          const id = event.currentTarget.value || undefined
          dataworks.setSelectedConnectionID(id)
          props.onChange?.(options().find((item) => item.id === id))
        }}
      >
        <Show when={options().length === 0}>
          <option value="">{language.t("dataworks.connection.selector.empty")}</option>
        </Show>
        <For each={options()}>
          {(item) => (
            <option value={item.id}>
              {item.name} · {item.accessKeyDisplay} · {item.region}
            </option>
          )}
        </For>
      </select>
    </label>
  )
}
