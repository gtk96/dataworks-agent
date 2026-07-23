import { For, Show, createSignal, onMount } from "solid-js"
import { Button } from "@opencode-ai/ui/button"
import { type KnowledgeDocument, type ListState } from "@/context/dataworks"
import { useLanguage } from "@/context/language"
import { DataWorksShell, ListStateBanner } from "@/pages/dataworks/shell"

type KnowledgeBase = {
  id: string
  name: string
  egressPolicy: "local_only" | "approved_providers"
  approvedProviders: string[]
}

export default function KnowledgePage() {
  const language = useLanguage()
  const [docs, setDocs] = createSignal<KnowledgeDocument[]>([])
  const [bases, setBases] = createSignal<KnowledgeBase[]>([])
  const [activeBase, setActiveBase] = createSignal<string>("")
  const [state, setState] = createSignal<ListState>("empty")
  const [uploading, setUploading] = createSignal(false)
  const [pendingProvider, setPendingProvider] = createSignal("")
  const [confirmRemote, setConfirmRemote] = createSignal(false)

  async function refresh() {
    setState("loading")
    try {
      const basesRes = await fetch("/api/knowledge/bases", { credentials: "include" })
      if (basesRes.ok) {
        const body = (await basesRes.json()) as { bases: KnowledgeBase[] }
        setBases(body.bases ?? [])
        if (!activeBase() && body.bases?.[0]) setActiveBase(body.bases[0].id)
      }
      const kbId = activeBase()
      if (!kbId) {
        setDocs([])
        setState("empty")
        return
      }
      const res = await fetch(`/api/knowledge/bases/${kbId}/documents`, { credentials: "include" })
      if (!res.ok) {
        setState("error")
        return
      }
      const body = (await res.json()) as {
        documents: Array<KnowledgeDocument & { filename?: string }>
      }
      const mapped = (body.documents ?? []).map((d) => ({
        ...d,
        name: d.name || d.filename || d.id,
      }))
      setDocs(mapped)
      setState(mapped.length > 0 ? "ready" : "empty")
    } catch {
      setState("error")
    }
  }

  onMount(() => {
    void refresh()
  })

  async function onUpload(event: Event) {
    const input = event.currentTarget as HTMLInputElement
    const file = input.files?.[0]
    if (!file) return
    let kbId = activeBase()
    if (!kbId) {
      const created = await fetch("/api/knowledge/bases", {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: "default", egressPolicy: "local_only" }),
      })
      if (!created.ok) {
        setState("error")
        return
      }
      const base = (await created.json()) as KnowledgeBase
      setBases((prev) => [base, ...prev])
      setActiveBase(base.id)
      kbId = base.id
    }
    setUploading(true)
    setState("loading")
    const form = new FormData()
    form.append("file", file)
    const res = await fetch(`/api/knowledge/bases/${kbId}/documents`, {
      method: "POST",
      credentials: "include",
      body: form,
    })
    setUploading(false)
    input.value = ""
    if (!res.ok) {
      setState("error")
      return
    }
    await refresh()
  }

  async function approveProvider() {
    const kbId = activeBase()
    const provider = pendingProvider().trim()
    if (!kbId || !provider || !confirmRemote()) return
    const res = await fetch(`/api/knowledge/bases/${kbId}/approve-provider`, {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ providerId: provider }),
    })
    if (res.ok) {
      setConfirmRemote(false)
      setPendingProvider("")
      await refresh()
    }
  }

  return (
    <DataWorksShell>
      <div class="flex flex-col gap-4 max-w-3xl" data-page="dataworks-knowledge">
        <h1 class="text-16-medium text-text-strong">{language.t("dataworks.nav.knowledge")}</h1>
        <label class="flex flex-col gap-1 max-w-sm">
          <span class="text-12-regular text-text-weak">{language.t("dataworks.knowledge.upload")}</span>
          <input type="file" accept=".pdf,.docx,.md,.txt,.markdown" disabled={uploading()} onChange={(e) => void onUpload(e)} />
        </label>
        <Button variant="secondary" size="small" class="self-start" onClick={() => void refresh()}>
          {language.t("dataworks.knowledge.refresh")}
        </Button>

        <div class="dwa-card p-3 flex flex-col gap-2" data-section="egress-policy">
          <span class="text-14-medium">Provider egress</span>
          <span class="text-12-regular text-text-weak">
            Default is local_only. Approving a remote Provider requires explicit confirmation and is audited.
          </span>
          <input
            class="border px-2 py-1 text-12-regular"
            placeholder="Provider id (e.g. dashscope)"
            value={pendingProvider()}
            onInput={(e) => setPendingProvider(e.currentTarget.value)}
            data-testid="knowledge-provider-id"
          />
          <label class="flex items-center gap-2 text-12-regular">
            <input
              type="checkbox"
              checked={confirmRemote()}
              onChange={(e) => setConfirmRemote(e.currentTarget.checked)}
              data-testid="knowledge-provider-confirm"
            />
            I understand chunks may be sent to this Provider
          </label>
          <Button
            variant="primary"
            size="small"
            class="self-start"
            disabled={!confirmRemote() || !pendingProvider().trim()}
            onClick={() => void approveProvider()}
            data-testid="knowledge-provider-approve"
          >
            Approve Provider
          </Button>
          <Show when={bases().find((b) => b.id === activeBase())}>
            {(b) => (
              <span class="text-12-regular text-text-weak">
                Active: {b().name} · {b().egressPolicy}
                <Show when={b().approvedProviders.length}>
                  {" "}
                  · approved: {b().approvedProviders.join(", ")}
                </Show>
              </span>
            )}
          </Show>
        </div>

        <ListStateBanner state={state} onRetry={() => void refresh()} emptyKey="dataworks.knowledge.empty" />
        <Show when={state() === "ready" || state() === "loading"}>
          <ul class="flex flex-col gap-2" data-list="knowledge">
            <For each={docs()}>
              {(doc) => (
                <li class="dwa-card p-3 flex flex-col gap-1">
                  <span class="text-14-medium">{doc.name}</span>
                  <span class="text-12-regular text-text-weak">
                    {language.t("dataworks.knowledge.status")}: {doc.status}
                    <Show when={doc.progress !== undefined}> · {doc.progress}%</Show>
                  </span>
                  <Show when={doc.status === "uploading"}>
                    <progress max="100" value={doc.progress ?? 0} class="w-full" />
                  </Show>
                </li>
              )}
            </For>
          </ul>
        </Show>
      </div>
    </DataWorksShell>
  )
}
