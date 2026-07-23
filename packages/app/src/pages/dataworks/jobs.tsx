import { For, Show, createSignal } from "solid-js"
import { Button } from "@opencode-ai/ui/button"
import { ConnectionSelector } from "@/components/dataworks/connection-selector"
import { useDataWorks, type DataWorksJob, type ListState } from "@/context/dataworks"
import { useLanguage } from "@/context/language"
import { DataWorksShell, ListStateBanner } from "@/pages/dataworks/shell"

type JobAction = "rerun" | "supplement" | "pause"

function actionTool(kind: JobAction): "dw_rerun_job" | "dw_trigger_supplement" | "dw_pause_schedule" {
  if (kind === "rerun") return "dw_rerun_job"
  if (kind === "supplement") return "dw_trigger_supplement"
  return "dw_pause_schedule"
}

/**
 * Canonical args hash must match control-plane hashAuditArgs (sorted JSON keys).
 * Keep browser-side hashing in sync with packages/dataworks-core/src/audit.ts.
 * (App package does not depend on @dataworks-agent/core; Web Crypto is the browser equivalent.)
 */
async function hashArgs(args: Record<string, unknown>): Promise<string> {
  const canonical = canonicalJson(args)
  const data = new TextEncoder().encode(canonical)
  const digest = await crypto.subtle.digest("SHA-256", data)
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value)
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("args must contain finite numbers")
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`
  if (typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .filter((entry) => entry[1] !== undefined)
      .sort((left, right) => (left[0] < right[0] ? -1 : left[0] > right[0] ? 1 : 0))
      .map((entry) => `${JSON.stringify(entry[0])}:${canonicalJson(entry[1])}`)
      .join(",")}}`
  }
  throw new Error("args must be JSON serializable")
}

function todayBizDate(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

function asPositiveInt(value: unknown): number | null {
  if (typeof value === "number" && Number.isInteger(value) && value > 0) return value
  if (typeof value === "string" && /^\d+$/.test(value.trim())) {
    const n = Number(value.trim())
    if (Number.isInteger(n) && n > 0) return n
  }
  return null
}

/** Rerun needs a real instance id — never fall back to node id / job id. */
function resolveInstanceId(job: DataWorksJob): number | null {
  return asPositiveInt(job.instanceId)
}

/** Supplement / pause use node (schedule) id; fall back to explicit jobId only, not instanceId. */
function resolveNodeId(job: DataWorksJob): number | null {
  return asPositiveInt(job.nodeId) ?? asPositiveInt(job.scheduleId) ?? asPositiveInt(job.jobId)
}

function canRerun(job: DataWorksJob): boolean {
  return resolveInstanceId(job) !== null
}

function canNodeAction(job: DataWorksJob): boolean {
  return resolveNodeId(job) !== null
}

function buildActionArgs(
  kind: JobAction,
  job: DataWorksJob,
  projectID: number,
): Record<string, unknown> | null {
  if (kind === "rerun") {
    const instanceID = resolveInstanceId(job)
    if (instanceID === null) return null
    return { connectionID: "", projectID, instanceID }
  }
  if (kind === "supplement") {
    const nodeID = resolveNodeId(job)
    if (nodeID === null) return null
    return { connectionID: "", projectID, nodeID, bizDate: todayBizDate() }
  }
  const scheduleID = resolveNodeId(job)
  if (scheduleID === null) return null
  return { connectionID: "", projectID, scheduleID, paused: true }
}

function targetLabel(kind: JobAction, job: DataWorksJob): string {
  if (kind === "rerun") {
    const id = resolveInstanceId(job)
    return id !== null ? `instance:${id}` : "instance:—"
  }
  const nodeID = resolveNodeId(job)
  return nodeID !== null ? `node:${nodeID}` : "node:—"
}

export default function JobsPage() {
  const dataworks = useDataWorks()
  const language = useLanguage()
  const [projectID, setProjectID] = createSignal("")
  const [statusFilter, setStatusFilter] = createSignal("")
  const [jobs, setJobs] = createSignal<DataWorksJob[]>([])
  const [state, setState] = createSignal<ListState>("idle")
  const [message, setMessage] = createSignal<string | undefined>()
  const [pending, setPending] = createSignal<{
    kind: JobAction
    job: DataWorksJob
    args: Record<string, unknown>
    tool: string
  } | null>(null)
  const [reason, setReason] = createSignal("")
  const [busy, setBusy] = createSignal(false)
  const [actionError, setActionError] = createSignal<string | undefined>()

  async function load() {
    const connectionID = dataworks.selectedConnectionID()
    if (!connectionID || !projectID().trim()) {
      setState("empty")
      setJobs([])
      return
    }
    setState("loading")
    const result = await dataworks.listJobs(connectionID, projectID().trim())
    if (!result.ok) {
      setState(result.status === 429 ? "rate_limit" : "error")
      return
    }
    const filtered = statusFilter()
      ? result.data.filter((job) => String(job.status ?? "").toLowerCase() === statusFilter().toLowerCase())
      : result.data
    setJobs(filtered)
    setState(filtered.length ? (filtered.length < result.data.length ? "partial" : "ready") : "empty")
  }

  function openAction(kind: JobAction, job: DataWorksJob) {
    const connectionID = dataworks.selectedConnectionID()
    const pid = Number(projectID().trim())
    if (!connectionID || !Number.isInteger(pid)) {
      setMessage(language.t("dataworks.jobs.action.needProject"))
      return
    }
    if (!dataworks.selectedConnection()?.writeEnabled) {
      setMessage(language.t("dataworks.jobs.action.writeDisabled"))
      return
    }
    if (kind === "rerun" && resolveInstanceId(job) === null) {
      setMessage(language.t("dataworks.jobs.action.needInstanceId"))
      return
    }
    const raw = buildActionArgs(kind, job, pid)
    if (!raw) {
      setMessage(
        kind === "rerun"
          ? language.t("dataworks.jobs.action.needInstanceId")
          : language.t("dataworks.jobs.action.badTarget"),
      )
      return
    }
    raw.connectionID = connectionID
    setPending({ kind, job, args: raw, tool: actionTool(kind) })
    setReason("")
    setActionError(undefined)
  }

  async function confirmAction() {
    const p = pending()
    const text = reason().trim()
    if (!p || !text || busy()) return
    setBusy(true)
    setActionError(undefined)
    const connectionID = String(p.args.connectionID)
    try {
      const argsHash = await hashArgs(p.args)
      const ticket = await dataworks.issueWriteTicket({
        connectionID,
        tool: p.tool,
        argsHash,
        reason: text,
      })
      if (!ticket.ok) {
        setActionError(ticket.error)
        setBusy(false)
        return
      }
      const result = await dataworks.executeWrite({
        ticket: ticket.data.ticket,
        connectionID,
        tool: p.tool,
        args: p.args,
      })
      if (!result.ok) {
        setActionError(result.error)
        setBusy(false)
        return
      }
      setMessage(
        language.t("dataworks.jobs.action.success", {
          action: p.kind,
          id: targetLabel(p.kind, p.job),
          status: String(result.data.status ?? "ok"),
        }),
      )
      setPending(null)
      setReason("")
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "write_failed")
    } finally {
      setBusy(false)
    }
  }

  async function cancelAction() {
    if (busy()) return
    const p = pending()
    setBusy(true)
    setActionError(undefined)
    try {
      if (p) {
        // Same reject audit path as WriteConfirmation — do not only clear local state.
        const connectionID = String(p.args.connectionID ?? dataworks.selectedConnectionID() ?? "")
        const argsHash = await hashArgs(p.args)
        void dataworks.recordWriteRejection({
          connectionID,
          tool: p.tool,
          argsHash,
        })
      }
    } catch {
      // Best-effort audit; still close the dialog.
    } finally {
      setPending(null)
      setReason("")
      setActionError(undefined)
      setBusy(false)
    }
  }

  return (
    <DataWorksShell>
      <div class="flex flex-col gap-4 max-w-4xl" data-page="dataworks-jobs">
        <h1 class="text-16-medium text-text-strong">{language.t("dataworks.nav.jobs")}</h1>
        <p class="text-12-regular text-text-weak" data-component="jobs-list-hint">
          {language.t("dataworks.jobs.listHint")}
        </p>
        <div class="flex flex-wrap gap-3 items-end">
          <ConnectionSelector />
          <label class="flex flex-col gap-1">
            <span class="text-12-regular text-text-weak">{language.t("dataworks.jobs.projectId")}</span>
            <input
              class="text-14-regular px-3 py-2 rounded-md border border-[color:var(--dwa-border)] bg-transparent"
              value={projectID()}
              onInput={(e) => setProjectID(e.currentTarget.value)}
            />
          </label>
          <label class="flex flex-col gap-1">
            <span class="text-12-regular text-text-weak">{language.t("dataworks.jobs.statusFilter")}</span>
            <input
              class="text-14-regular px-3 py-2 rounded-md border border-[color:var(--dwa-border)] bg-transparent"
              value={statusFilter()}
              onInput={(e) => setStatusFilter(e.currentTarget.value)}
              placeholder="SUCCESS"
            />
          </label>
          <Button variant="secondary" size="small" onClick={() => void load()}>
            {language.t("dataworks.jobs.refresh")}
          </Button>
        </div>
        <ListStateBanner state={state} onRetry={() => void load()} />
        <Show when={state() === "ready" || state() === "partial"}>
          <ul class="flex flex-col gap-2" data-list="jobs">
            <For each={jobs()}>
              {(job) => {
                const instanceID = resolveInstanceId(job)
                const nodeID = resolveNodeId(job)
                return (
                  <li class="dwa-card p-3 flex flex-wrap gap-2 items-center">
                    <div class="flex flex-col min-w-0 flex-1">
                      <span class="text-14-medium font-mono">
                        {instanceID !== null
                          ? language.t("dataworks.jobs.row.instance", { id: String(instanceID) })
                          : language.t("dataworks.jobs.row.noInstance")}
                      </span>
                      <span class="text-12-regular text-text-weak font-mono">
                        {nodeID !== null
                          ? language.t("dataworks.jobs.row.node", { id: String(nodeID) })
                          : language.t("dataworks.jobs.row.noNode")}
                        {" · "}
                        {language.t("dataworks.jobs.status")}: {String(job.status ?? "unknown")}
                        {job.name ? ` · ${String(job.name)}` : ""}
                      </span>
                    </div>
                    <Button
                      variant="ghost"
                      size="small"
                      disabled={!canRerun(job)}
                      title={
                        canRerun(job) ? undefined : language.t("dataworks.jobs.action.needInstanceId")
                      }
                      onClick={() => openAction("rerun", job)}
                    >
                      {language.t("dataworks.jobs.rerun")}
                    </Button>
                    <Button
                      variant="ghost"
                      size="small"
                      disabled={!canNodeAction(job)}
                      onClick={() => openAction("supplement", job)}
                    >
                      {language.t("dataworks.jobs.supplement")}
                    </Button>
                    <Button
                      variant="ghost"
                      size="small"
                      disabled={!canNodeAction(job)}
                      onClick={() => openAction("pause", job)}
                    >
                      {language.t("dataworks.jobs.pause")}
                    </Button>
                  </li>
                )
              }}
            </For>
          </ul>
        </Show>
        <Show when={message()}>
          <p class="text-12-regular" role="status">
            {message()}
          </p>
        </Show>

        <Show when={pending()}>
          {(p) => (
            <div
              data-component="dataworks-jobs-write-confirm"
              role="dialog"
              aria-modal="true"
              class="dwa-card p-4 flex flex-col gap-3 max-w-lg"
            >
              <h2 class="text-14-medium text-text-strong">{language.t("dataworks.write.title")}</h2>
              <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-12-regular">
                <dt class="text-text-weak">{language.t("dataworks.write.tool")}</dt>
                <dd class="text-text-strong font-mono">{p().tool}</dd>
                <dt class="text-text-weak">{language.t("dataworks.write.target")}</dt>
                <dd class="text-text-strong font-mono break-all">{targetLabel(p().kind, p().job)}</dd>
              </dl>
              <label class="flex flex-col gap-1">
                <span class="text-12-regular text-text-weak">{language.t("dataworks.write.reason.label")}</span>
                <textarea
                  class="text-14-regular px-3 py-2 rounded-md border border-[color:var(--dwa-border)] bg-transparent min-h-20"
                  required
                  value={reason()}
                  onInput={(e) => setReason(e.currentTarget.value)}
                  placeholder={language.t("dataworks.write.reason.placeholder")}
                />
              </label>
              <Show when={actionError()}>
                <p class="text-12-regular dwa-status-danger" role="alert">
                  {actionError()}
                </p>
              </Show>
              <div class="flex justify-end gap-2">
                <Button variant="ghost" size="normal" disabled={busy()} onClick={() => void cancelAction()}>
                  {language.t("dataworks.write.reject")}
                </Button>
                <Button
                  variant="primary"
                  size="normal"
                  class="dwa-btn-primary"
                  disabled={busy() || !reason().trim()}
                  onClick={() => void confirmAction()}
                >
                  {language.t("dataworks.write.approve")}
                </Button>
              </div>
            </div>
          )}
        </Show>
      </div>
    </DataWorksShell>
  )
}
