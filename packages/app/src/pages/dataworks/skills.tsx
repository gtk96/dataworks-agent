import { For, Show, createSignal, onMount } from "solid-js"
import { Button } from "@opencode-ai/ui/button"
import { useLanguage } from "@/context/language"
import { DataWorksShell, ListStateBanner } from "@/pages/dataworks/shell"
import type { ListState } from "@/context/dataworks"

type SkillItem = {
  name: string
  description?: string
  scope: "system" | "user"
  writeEnabled: boolean
  forbiddenTools: string[]
  allowedTools: string[]
  content: string
}

export default function SkillsPage() {
  const language = useLanguage()
  const [system, setSystem] = createSignal<SkillItem[]>([])
  const [userSkills, setUserSkills] = createSignal<SkillItem[]>([])
  const [state, setState] = createSignal<ListState>("loading")
  const [name, setName] = createSignal("")
  const [markdown, setMarkdown] = createSignal(defaultMarkdown())
  const [message, setMessage] = createSignal<string | undefined>()

  async function refresh() {
    setState("loading")
    setMessage(undefined)
    try {
      const res = await fetch("/api/skills", { credentials: "include" })
      if (!res.ok) {
        setState("error")
        return
      }
      const body = (await res.json()) as { system: SkillItem[]; user: SkillItem[] }
      setSystem(body.system ?? [])
      setUserSkills(body.user ?? [])
      setState(body.system?.length || body.user?.length ? "ready" : "empty")
    } catch {
      setState("error")
    }
  }

  async function onCreate(event: Event) {
    event.preventDefault()
    setMessage(undefined)
    const skillName = name().trim()
    if (!skillName) return
    const res = await fetch("/api/skills", {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: skillName, markdown: markdown() }),
    })
    if (!res.ok) {
      setMessage(language.t("dataworks.skills.error"))
      return
    }
    setName("")
    setMarkdown(defaultMarkdown())
    setMessage(language.t("dataworks.skills.saved"))
    await refresh()
  }

  async function onDelete(skillName: string) {
    const res = await fetch(`/api/skills/${encodeURIComponent(skillName)}`, {
      method: "DELETE",
      credentials: "include",
    })
    if (!res.ok) {
      setMessage(language.t("dataworks.skills.error"))
      return
    }
    await refresh()
  }

  onMount(() => {
    void refresh()
  })

  return (
    <DataWorksShell>
      <div class="flex flex-col gap-4 max-w-3xl" data-page="dataworks-skills">
        <h1 class="text-16-medium text-text-strong">{language.t("dataworks.nav.skills")}</h1>
        <p class="text-12-regular text-text-weak">{language.t("dataworks.skills.hint")}</p>

        <ListStateBanner state={state} onRetry={() => void refresh()} emptyKey="dataworks.skills.empty" />

        <Show when={message()}>
          <p class="text-12-regular" data-message>
            {message()}
          </p>
        </Show>

        <section class="flex flex-col gap-2">
          <h2 class="text-14-medium">{language.t("dataworks.skills.system")}</h2>
          <ul class="flex flex-col gap-2" data-list="skills-system">
            <For each={system()}>
              {(item) => (
                <li class="dwa-card p-3 flex flex-col gap-1">
                  <span class="text-14-medium">{item.name}</span>
                  <span class="text-12-regular text-text-weak">{item.description}</span>
                  <span class="text-12-regular text-text-weak">{language.t("dataworks.skills.readonly")}</span>
                </li>
              )}
            </For>
          </ul>
        </section>

        <section class="flex flex-col gap-2">
          <h2 class="text-14-medium">{language.t("dataworks.skills.user")}</h2>
          <ul class="flex flex-col gap-2" data-list="skills-user">
            <For each={userSkills()}>
              {(item) => (
                <li class="dwa-card p-3 flex flex-wrap items-center gap-3">
                  <div class="flex flex-col min-w-0 flex-1">
                    <span class="text-14-medium">{item.name}</span>
                    <span class="text-12-regular text-text-weak">{item.description}</span>
                  </div>
                  <Button variant="ghost" size="small" onClick={() => void onDelete(item.name)}>
                    {language.t("dataworks.skills.delete")}
                  </Button>
                </li>
              )}
            </For>
          </ul>
        </section>

        <form class="flex flex-col gap-2 dwa-card p-3" onSubmit={(e) => void onCreate(e)}>
          <h2 class="text-14-medium">{language.t("dataworks.skills.create")}</h2>
          <label class="flex flex-col gap-1">
            <span class="text-12-regular text-text-weak">{language.t("dataworks.skills.name")}</span>
            <input
              class="px-2 py-1 border border-[color:var(--dwa-border)] rounded-md"
              value={name()}
              onInput={(e) => setName(e.currentTarget.value)}
              required
            />
          </label>
          <label class="flex flex-col gap-1">
            <span class="text-12-regular text-text-weak">{language.t("dataworks.skills.markdown")}</span>
            <textarea
              class="px-2 py-1 border border-[color:var(--dwa-border)] rounded-md font-mono text-12-regular min-h-40"
              value={markdown()}
              onInput={(e) => setMarkdown(e.currentTarget.value)}
              required
            />
          </label>
          <Button type="submit" size="small" class="self-start">
            {language.t("dataworks.skills.save")}
          </Button>
        </form>
      </div>
    </DataWorksShell>
  )
}

function defaultMarkdown() {
  return `---
name: my-skill
description: Describe this playbook
triggers: []
allowed_tools: [dw_run_sql, dw_list_tables, dw_describe_table]
forbidden_tools: [dw_rerun_job, dw_trigger_supplement]
max_tool_calls_per_session: 20
write_enabled: false
---

# Playbook

Domain guidance for the agent.
`
}
