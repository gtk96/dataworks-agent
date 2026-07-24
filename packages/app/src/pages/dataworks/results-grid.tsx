import { For, Show, createMemo, type JSX } from "solid-js"
import type { DataWorksSqlResult } from "@/context/dataworks"
import { useLanguage } from "@/context/language"

export function normalizeResultColumns(columns: DataWorksSqlResult["columns"]) {
  return columns.map((column, index) =>
    typeof column === "string"
      ? { name: column, type: "" }
      : { name: column.name || `col_${index + 1}`, type: column.type },
  )
}

export function visibleResultRows(rows: DataWorksSqlResult["rows"]) {
  return rows.slice(0, 1000)
}

export function ResultsGrid(props: { result: DataWorksSqlResult; stale: boolean }): JSX.Element {
  const language = useLanguage()
  const columns = createMemo(() => normalizeResultColumns(props.result.columns))
  const rows = createMemo(() => visibleResultRows(props.result.rows))
  const truncated = createMemo(() => props.result.truncated || props.result.rows.length > rows().length)

  return (
    <section data-component="workbench-results" data-stale={props.stale ? "true" : "false"}>
      <Show when={props.stale}>
        <div role="status">{language.t("dataworks.workbench.resultsStale")}</div>
      </Show>
      <div data-slot="result-meta">
        <span>{language.t("dataworks.workbench.rowCount", { count: props.result.rows.length })}</span>
        <Show when={props.result.durationMs !== undefined}>
          <span>{props.result.durationMs} ms</span>
        </Show>
        <Show when={props.result.instanceId}>
          <span>{props.result.instanceId}</span>
        </Show>
      </div>
      <div
        data-slot="result-scroll"
        role="region"
        aria-label={language.t("dataworks.workbench.sqlResults")}
        tabindex="0"
      >
        <table>
          <thead>
            <tr>
              <For each={columns()}>
                {(column) => (
                  <th scope="col" title={column.type}>
                    {column.name}
                  </th>
                )}
              </For>
            </tr>
          </thead>
          <tbody>
            <For each={rows()}>
              {(row) => (
                <tr>
                  <For each={columns()}>{(_, index) => <td>{String(row[index()] ?? "")}</td>}</For>
                </tr>
              )}
            </For>
          </tbody>
        </table>
      </div>
      <Show when={truncated()}>
        <div role="status">{language.t("dataworks.workbench.previewTruncated")}</div>
      </Show>
    </section>
  )
}
