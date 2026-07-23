import { createMemo, createSignal, For, Show, type JSX } from "solid-js"
import { BasicTool } from "./basic-tool"
import {
  formatSqlCell,
  parseSqlResultView,
  sqlResultSubtitle,
  sqlResultToTsv,
  type SqlResultView,
} from "./sql-result"
import "./sql-result-card.css"

const COLLAPSED_ROW_LIMIT = 12

async function writeClipboard(text: string): Promise<boolean> {
  const body = typeof document === "undefined" ? undefined : document.body
  if (body) {
    const textarea = document.createElement("textarea")
    textarea.value = text
    textarea.setAttribute("readonly", "")
    textarea.style.position = "fixed"
    textarea.style.opacity = "0"
    textarea.style.pointerEvents = "none"
    body.appendChild(textarea)
    textarea.select()
    const copied = document.execCommand("copy")
    body.removeChild(textarea)
    if (copied) return true
  }
  const clipboard = typeof navigator === "undefined" ? undefined : navigator.clipboard
  if (!clipboard?.writeText) return false
  return clipboard.writeText(text).then(
    () => true,
    () => false,
  )
}

export function SqlResultTable(props: { view: SqlResultView; expanded?: boolean }): JSX.Element {
  const rows = createMemo(() => {
    if (props.expanded) return props.view.rows
    return props.view.rows.slice(0, COLLAPSED_ROW_LIMIT)
  })
  const columns = createMemo(() =>
    props.view.columns.length > 0
      ? props.view.columns
      : props.view.rows[0]
        ? props.view.rows[0].map((_, index) => ({ name: `col_${index + 1}` }))
        : [],
  )

  return (
    <div data-slot="sql-result-scroll" data-scrollable tabIndex={0} role="region" aria-label="SQL result table">
      <table data-slot="sql-result-table">
        <Show when={columns().length > 0}>
          <thead>
            <tr>
              <For each={columns()}>{(column) => <th scope="col">{column.name}</th>}</For>
            </tr>
          </thead>
        </Show>
        <tbody>
          <For each={rows()}>
            {(row) => (
              <tr>
                <For each={columns()}>
                  {(column, index) => <td>{formatSqlCell(row[index()] ?? null)}</td>}
                </For>
              </tr>
            )}
          </For>
        </tbody>
      </table>
    </div>
  )
}

export function SqlResultCardBody(props: {
  view: SqlResultView
  sql?: string
  onCopy?: () => void
}): JSX.Element {
  const [expanded, setExpanded] = createSignal(false)
  const [copied, setCopied] = createSignal(false)
  const canExpand = createMemo(() => props.view.rows.length > COLLAPSED_ROW_LIMIT)

  const copy = async () => {
    const ok = await writeClipboard(sqlResultToTsv(props.view))
    if (!ok) return
    setCopied(true)
    props.onCopy?.()
    setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div data-slot="sql-result-body">
      <Show when={props.sql}>
        {(sql) => (
          <pre data-slot="sql-result-sql">
            <code>{sql()}</code>
          </pre>
        )}
      </Show>
      <div data-slot="sql-result-toolbar">
        <span data-slot="sql-result-meta">{sqlResultSubtitle(props.view)}</span>
        <div data-slot="sql-result-actions">
          <button type="button" data-slot="sql-result-action" onClick={() => void copy()}>
            {copied() ? "Copied" : "Copy TSV"}
          </button>
          <Show when={canExpand()}>
            <button type="button" data-slot="sql-result-action" onClick={() => setExpanded((value) => !value)}>
              {expanded() ? "Collapse" : `Show all ${props.view.rows.length}`}
            </button>
          </Show>
        </div>
      </div>
      <Show
        when={props.view.rowCount > 0}
        fallback={<div data-slot="sql-result-empty">No rows returned.</div>}
      >
        <SqlResultTable view={props.view} expanded={expanded()} />
      </Show>
      <Show when={props.view.truncated}>
        <div data-slot="sql-result-truncated">Preview truncated — full result retained server-side.</div>
      </Show>
    </div>
  )
}

/** Presentational SQL tool card used by ToolRegistry.render("dw_run_sql"). */
export function SqlResultCard(props: {
  status?: string
  hideDetails?: boolean
  defaultOpen?: boolean
  open?: boolean
  onOpenChange?: (open: boolean) => void
  title: string
  subtitle?: string
  view?: SqlResultView
  sql?: string
}): JSX.Element {
  return (
    <div data-component="sql-result-card">
      <BasicTool
        icon="console"
        status={props.status}
        hideDetails={props.hideDetails}
        defaultOpen={props.defaultOpen ?? true}
        open={props.open}
        onOpenChange={props.onOpenChange}
        trigger={{
          title: props.title,
          subtitle: props.subtitle,
        }}
      >
        <Show when={props.view}>{(view) => <SqlResultCardBody view={view()} sql={props.sql} />}</Show>
      </BasicTool>
    </div>
  )
}
