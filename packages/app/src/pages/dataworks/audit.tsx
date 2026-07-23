import { For, Show, createSignal } from "solid-js"
import { Button } from "@opencode-ai/ui/button"
import { useSearchParams } from "@solidjs/router"
import { useDataWorks, type AuditEvent, type ListState } from "@/context/dataworks"
import { useLanguage } from "@/context/language"
import { DataWorksShell, ListStateBanner } from "@/pages/dataworks/shell"
import { wantsAllUsers } from "@/pages/dataworks/route"

export default function AuditPage() {
  const dataworks = useDataWorks()
  const language = useLanguage()
  const [search, setSearch] = useSearchParams<{ scope?: string; allUsers?: string; userID?: string }>()
  const [events, setEvents] = createSignal<AuditEvent[]>([])
  const [state, setState] = createSignal<ListState>("idle")
  const [userFilter, setUserFilter] = createSignal(search.userID ?? "")

  const isAdmin = () => dataworks.user()?.role === "admin"
  const allUsers = () => wantsAllUsers(search)

  async function load() {
    setState("loading")
    const result = await dataworks.listAudit({
      limit: 100,
      userID: isAdmin() && allUsers() && userFilter().trim() ? userFilter().trim() : undefined,
    })
    if (!result.ok) {
      setState(result.status === 429 ? "rate_limit" : "error")
      return
    }
    setEvents(result.data)
    setState(result.data.length ? "ready" : "empty")
  }

  function enableAllUsers() {
    if (!isAdmin()) return
    setSearch({ scope: "all" })
  }

  function disableAllUsers() {
    setSearch({ scope: undefined, allUsers: undefined })
  }

  return (
    <DataWorksShell>
      <div class="flex flex-col gap-4 max-w-4xl" data-page="dataworks-audit">
        <h1 class="text-16-medium text-text-strong">{language.t("dataworks.nav.audit")}</h1>
        <p class="text-12-regular text-text-weak">
          {allUsers() && isAdmin()
            ? language.t("dataworks.audit.scope.all")
            : language.t("dataworks.audit.scope.me")}
        </p>
        <div class="flex flex-wrap gap-2 items-end">
          <Show when={isAdmin()}>
            <Show
              when={allUsers()}
              fallback={
                <Button variant="secondary" size="small" onClick={enableAllUsers}>
                  {language.t("dataworks.audit.filter.allUsers")}
                </Button>
              }
            >
              <label class="flex flex-col gap-1">
                <span class="text-12-regular text-text-weak">{language.t("dataworks.audit.filter.userId")}</span>
                <input
                  class="text-14-regular px-3 py-2 rounded-md border border-[color:var(--dwa-border)] bg-transparent"
                  value={userFilter()}
                  onInput={(e) => setUserFilter(e.currentTarget.value)}
                />
              </label>
              <Button variant="ghost" size="small" onClick={disableAllUsers}>
                {language.t("dataworks.audit.filter.mine")}
              </Button>
            </Show>
          </Show>
          <Button variant="secondary" size="small" onClick={() => void load()}>
            {language.t("dataworks.audit.refresh")}
          </Button>
        </div>
        <ListStateBanner state={state} onRetry={() => void load()} />
        <Show when={state() === "ready"}>
          <table class="w-full text-12-regular border-collapse" data-list="audit">
            <thead>
              <tr class="text-left text-text-weak border-b border-[color:var(--dwa-border)]">
                <th class="py-2 pr-2">{language.t("dataworks.audit.col.time")}</th>
                <th class="py-2 pr-2">{language.t("dataworks.audit.col.tool")}</th>
                <th class="py-2 pr-2">{language.t("dataworks.audit.col.outcome")}</th>
                <th class="py-2 pr-2">{language.t("dataworks.audit.col.reason")}</th>
              </tr>
            </thead>
            <tbody>
              <For each={events()}>
                {(item) => (
                  <tr class="border-b border-[color:var(--dwa-border)]">
                    <td class="py-2 pr-2 font-mono">{new Date(item.timeCreated).toISOString()}</td>
                    <td class="py-2 pr-2 font-mono">{item.tool}</td>
                    <td class="py-2 pr-2">{item.outcome}</td>
                    <td class="py-2 pr-2 break-all">{item.reason ?? "—"}</td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </Show>
      </div>
    </DataWorksShell>
  )
}
