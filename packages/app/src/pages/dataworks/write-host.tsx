import { Show, createMemo, createSignal } from "solid-js"
import type { PermissionRequest } from "@opencode-ai/sdk/v2/client"
import { useServerSync } from "@/context/server-sync"
import { usePermission } from "@/context/permission"
import { isDwWritePermission, WriteConfirmation } from "@/components/dataworks/write-confirmation"

/**
 * Scans pending OpenCode permission requests for dw_write and renders the
 * specialized confirmation UI. Non-dw_write permissions stay on the session dock.
 */
export function WriteConfirmationHost() {
  const sync = useServerSync()
  const permission = usePermission()
  const [dismissed, setDismissed] = createSignal<Record<string, true>>({})

  const pending = createMemo((): PermissionRequest | undefined => {
    const data = sync().session.data.permission
    for (const list of Object.values(data)) {
      if (!list) continue
      for (const item of list) {
        if (!isDwWritePermission(item)) continue
        if (dismissed()[item.id]) continue
        if (permission.autoResponds(item)) continue
        return item
      }
    }
    return
  })

  return (
    <Show when={pending()} keyed>
      {(request) => (
        <div class="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 p-4">
          <WriteConfirmation
            request={request}
            onClose={() => setDismissed((prev) => ({ ...prev, [request.id]: true }))}
          />
        </div>
      )}
    </Show>
  )
}
