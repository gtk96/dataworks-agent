import { Show, createMemo, createSignal, type JSX } from "solid-js"
import { useNavigate } from "@solidjs/router"
import { useDataWorks } from "@/context/dataworks"
import { useLanguage } from "@/context/language"
import { useTabs } from "@/context/tabs"
import { useGlobal } from "@/context/global"
import { useServerSync } from "@/context/server-sync"
import { ServerConnection } from "@/context/server"
import { showToast } from "@/utils/toast"
import { ChatHero, type EnvTone } from "./dashboard-chat-hero"
import { ChatError, type ChatError as ChatErrorState } from "./dashboard-chat-error"
import "./dashboard.css"

function deriveEnvTone(projectName: string, envType?: string): EnvTone {
  const probe = `${projectName} ${envType ?? ""}`.toLowerCase()
  if (probe.includes("prod") || probe.includes("生产")) return "prod"
  if (probe.includes("stg") || probe.includes("staging") || probe.includes("预发")) return "staging"
  if (probe.includes("dev") || probe.includes("开发")) return "dev"
  return "unknown"
}

export function DataWorksDashboard(): JSX.Element {
  const dataworks = useDataWorks()
  const language = useLanguage()
  const tabs = useTabs()
  const globalCtx = useGlobal()
  const serverSync = useServerSync()
  const navigate = useNavigate()
  const [sending, setSending] = createSignal(false)
  const [error, setError] = createSignal<ChatErrorState | undefined>(undefined)

  const connectionReady = createMemo(() => Boolean(dataworks.selectedConnectionID()))
  const projectReady = createMemo(() => Boolean(dataworks.selectedProjectID()))
  const runtimeReady = createMemo(() => {
    const serverEntry = globalCtx.servers.list()[0]
    const projectEntry = serverSync().data.project?.[0]
    return Boolean(serverEntry && projectEntry)
  })

  const scopeLabel = createMemo(() => {
    const conn = dataworks.selectedConnection()
    const project = dataworks.selectedProject()
    if (!conn && !project) return language.t("dataworks.chat.scope.none")
    const connName = conn?.name ?? "—"
    const projectName =
      project?.projectName ?? project?.name ?? (project?.projectId != null ? String(project.projectId) : "—")
    return `${connName} · ${projectName}`
  })

  const scopeEnv = createMemo<EnvTone>(() => {
    const project = dataworks.selectedProject()
    const name = project?.projectName ?? project?.name ?? ""
    return deriveEnvTone(name, project?.envType)
  })

  const modelLabel = createMemo(() => {
    const serverEntry = globalCtx.servers.list()[0]
    return serverEntry?.name ? serverEntry.name : language.t("dataworks.chat.model.default")
  })

  const visibleError = createMemo<ChatErrorState | undefined>(() => {
    if (!connectionReady()) return { kind: "connection" }
    if (!projectReady()) return { kind: "project" }
    return undefined
  })

  async function submit(text: string) {
    if (!runtimeReady()) {
      setError({ kind: "runtime" })
      showToast({
        title: language.t("dataworks.dashboard.runtimeMissingTitle"),
        description: language.t("dataworks.dashboard.runtimeMissingBody"),
        variant: "error",
      })
      return
    }
    const serverEntry = globalCtx.servers.list()[0]
    const projectEntry = serverSync().data.project?.[0]
    if (!serverEntry || !projectEntry) {
      setError({ kind: "runtime" })
      return
    }
    setSending(true)
    setError(undefined)
    try {
      const created = await tabs.newDraft(
        {
          server: ServerConnection.key(serverEntry),
          directory: projectEntry.worktree,
        },
        text,
      )
      // The /new-session route reads `?prompt=` from the URL to prefill its
      // composer. Without this search param the page navigates successfully
      // but renders an empty composer and the submitted text vanishes.
      if (created?.draftID) {
        const params = new URLSearchParams()
        params.set("draftId", created.draftID)
        params.set("prompt", text)
        navigate(`/new-session?${params.toString()}`, { replace: true })
      }
    } catch (sendError) {
      const message = sendError instanceof Error ? sendError.message : undefined
      setError({ kind: "send", message })
      showToast({
        title: language.t("dataworks.dashboard.sendFailedTitle"),
        description: message ?? language.t("dataworks.dashboard.sendFailedBody"),
        variant: "error",
      })
    } finally {
      setSending(false)
    }
  }

  function onAddConnection() {
    navigate("/dataworks/connections")
  }

  function onRefreshProjects() {
    void dataworks.refreshProjects()
  }

  function onRetry() {
    setError(undefined)
  }

  return (
    <main class="dwa-page-stack" data-component="dataworks-dashboard">
      <ChatHero
        onSubmit={submit}
        disabled={sending()}
        scopeLabel={scopeLabel()}
        scopeEnv={scopeEnv()}
        modelLabel={modelLabel()}
      />

      <Show when={visibleError()}>
        <ChatError
          error={visibleError()}
          onAddConnection={onAddConnection}
          onRefreshProjects={onRefreshProjects}
          t={(key) => language.t(key)}
        />
      </Show>

      <Show when={!visibleError() && error()}>
        <ChatError
          error={error()}
          onRetry={onRetry}
          t={(key) => language.t(key)}
        />
      </Show>
    </main>
  )
}