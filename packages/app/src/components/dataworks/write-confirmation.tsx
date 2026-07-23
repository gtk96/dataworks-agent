import { Show, createMemo, createSignal, type JSX } from "solid-js"
import type { PermissionRequest } from "@opencode-ai/sdk/v2/client"
import { Button } from "@opencode-ai/ui/button"
import { useDataWorks } from "@/context/dataworks"
import { useLanguage } from "@/context/language"
import { usePermission } from "@/context/permission"

export type WriteConfirmationMeta = {
  tool?: string
  argsHash?: string
  connectionID?: string
  operationTarget?: string
  accessKeyDisplay?: string
}

function metaOf(request: PermissionRequest): WriteConfirmationMeta {
  const metadata = request.metadata ?? {}
  return {
    tool: typeof metadata.tool === "string" ? metadata.tool : undefined,
    argsHash: typeof metadata.argsHash === "string" ? metadata.argsHash : undefined,
    connectionID: typeof metadata.connectionID === "string" ? metadata.connectionID : request.patterns[0],
    operationTarget:
      typeof metadata.operationTarget === "string" ? metadata.operationTarget : request.patterns[1],
    accessKeyDisplay: typeof metadata.accessKeyDisplay === "string" ? metadata.accessKeyDisplay : undefined,
  }
}

/**
 * Shown when OpenCode emits permission.asked for dw_write.
 * Approval: reason → control plane write ticket, then OpenCode permission once.
 * Rejection: OpenCode reject immediately + rejection audit record.
 */
export function WriteConfirmation(props: {
  request: PermissionRequest
  directory?: string
  onClose?: () => void
}): JSX.Element {
  const language = useLanguage()
  const dataworks = useDataWorks()
  const permission = usePermission()
  const [reason, setReason] = createSignal("")
  const [busy, setBusy] = createSignal(false)
  const [error, setError] = createSignal<string | undefined>()

  const meta = createMemo(() => metaOf(props.request))
  const connectionLabel = createMemo(() => {
    const m = meta()
    const conn = dataworks.connections().find((item) => item.id === m.connectionID)
    if (conn) return `${conn.name} (${conn.accessKeyDisplay})`
    if (m.accessKeyDisplay) return m.accessKeyDisplay
    return m.connectionID ?? language.t("dataworks.write.connection.unknown")
  })

  const canApprove = createMemo(() => reason().trim().length > 0 && !busy())

  async function approve() {
    const text = reason().trim()
    if (!text || busy()) return
    setBusy(true)
    setError(undefined)
    const m = meta()
    const ticket = await dataworks.issueWriteTicket({
      connectionID: m.connectionID ?? "",
      sessionID: props.request.sessionID,
      tool: m.tool ?? "dw_write",
      argsHash: m.argsHash ?? "",
      reason: text,
    })
    if (!ticket.ok) {
      setError(ticket.error)
      setBusy(false)
      return
    }
    permission.respond({
      sessionID: props.request.sessionID,
      permissionID: props.request.id,
      response: "once",
      directory: props.directory,
    })
    setBusy(false)
    props.onClose?.()
  }

  async function reject() {
    if (busy()) return
    setBusy(true)
    setError(undefined)
    const m = meta()
    permission.respond({
      sessionID: props.request.sessionID,
      permissionID: props.request.id,
      response: "reject",
      directory: props.directory,
    })
    void dataworks.recordWriteRejection({
      connectionID: m.connectionID ?? "",
      sessionID: props.request.sessionID,
      tool: m.tool ?? "dw_write",
      argsHash: m.argsHash ?? "",
    })
    setBusy(false)
    props.onClose?.()
  }

  return (
    <div
      data-component="dataworks-write-confirmation"
      role="dialog"
      aria-modal="true"
      aria-labelledby="dwa-write-title"
      class="dwa-card p-4 flex flex-col gap-3 shadow-lg max-w-lg w-full"
    >
      <h2 id="dwa-write-title" class="text-14-medium text-text-strong">
        {language.t("dataworks.write.title")}
      </h2>
      <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-12-regular">
        <dt class="text-text-weak">{language.t("dataworks.write.tool")}</dt>
        <dd class="text-text-strong font-mono break-all">{meta().tool ?? props.request.permission}</dd>
        <dt class="text-text-weak">{language.t("dataworks.write.target")}</dt>
        <dd class="text-text-strong font-mono break-all">
          {meta().operationTarget ?? props.request.patterns.join(", ")}
        </dd>
        <dt class="text-text-weak">{language.t("dataworks.write.connection")}</dt>
        <dd class="text-text-strong break-all">{connectionLabel()}</dd>
      </dl>
      <label class="flex flex-col gap-1">
        <span class="text-12-regular text-text-weak">{language.t("dataworks.write.reason.label")}</span>
        <textarea
          data-component="dataworks-write-reason"
          class="text-14-regular px-3 py-2 rounded-md border border-[color:var(--dwa-border)] bg-transparent min-h-20"
          required
          value={reason()}
          onInput={(event) => setReason(event.currentTarget.value)}
          placeholder={language.t("dataworks.write.reason.placeholder")}
        />
      </label>
      <Show when={error()}>
        <p class="text-12-regular dwa-status-danger" role="alert">
          {error()}
        </p>
      </Show>
      <div class="flex justify-end gap-2">
        <Button variant="ghost" size="normal" disabled={busy()} onClick={() => void reject()}>
          {language.t("dataworks.write.reject")}
        </Button>
        <Button
          variant="primary"
          size="normal"
          class="dwa-btn-primary"
          disabled={!canApprove()}
          onClick={() => void approve()}
        >
          {language.t("dataworks.write.approve")}
        </Button>
      </div>
    </div>
  )
}

export function isDwWritePermission(request: PermissionRequest): boolean {
  return request.permission === "dw_write"
}
