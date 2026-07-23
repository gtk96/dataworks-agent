import { For, Show, createSignal } from "solid-js"
import { Button } from "@opencode-ai/ui/button"
import { useDataWorks } from "@/context/dataworks"
import { useLanguage } from "@/context/language"
import { DataWorksShell, ListStateBanner } from "@/pages/dataworks/shell"

export default function ConnectionsPage() {
  const dataworks = useDataWorks()
  const language = useLanguage()
  const [name, setName] = createSignal("")
  const [region, setRegion] = createSignal("cn-hangzhou")
  const [accessKeyId, setAccessKeyId] = createSignal("")
  const [accessKeySecret, setAccessKeySecret] = createSignal("")
  const [writeEnabled, setWriteEnabled] = createSignal(false)
  const [message, setMessage] = createSignal<string | undefined>()
  const [testing, setTesting] = createSignal(false)

  async function onCreate(event: Event) {
    event.preventDefault()
    setMessage(undefined)
    const result = await dataworks.createConnection({
      name: name().trim(),
      region: region().trim(),
      accessKeyId: accessKeyId(),
      accessKeySecret: accessKeySecret(),
      writeEnabled: writeEnabled(),
    })
    if (!result.ok) {
      setMessage(result.error)
      return
    }
    setName("")
    setAccessKeyId("")
    setAccessKeySecret("")
    setWriteEnabled(false)
    setMessage(language.t("dataworks.connection.created"))
  }

  async function onTest(id: string) {
    setTesting(true)
    setMessage(undefined)
    const conn = dataworks.connections().find((item) => item.id === id)
    const result = await dataworks.listProjects(id, conn?.region)
    setTesting(false)
    if (!result.ok) {
      setMessage(result.error)
      return
    }
    setMessage(language.t("dataworks.connection.test.ok", { count: String(result.data.length) }))
  }

  return (
    <DataWorksShell>
      <div class="flex flex-col gap-4 max-w-3xl" data-page="dataworks-connections">
        <h1 class="text-16-medium text-text-strong">{language.t("dataworks.nav.connections")}</h1>

        <ListStateBanner state={dataworks.connectionState} onRetry={() => void dataworks.refreshConnections()} />

        <Show when={dataworks.connectionState() === "ready" || dataworks.connectionState() === "empty"}>
          <ul class="flex flex-col gap-2" data-list="connections">
            <For each={dataworks.connections()}>
              {(item) => (
                <li class="dwa-card p-3 flex flex-wrap items-center gap-3">
                  <div class="flex flex-col min-w-0 flex-1">
                    <span class="text-14-medium text-text-strong">{item.name}</span>
                    <span class="text-12-regular text-text-weak font-mono">
                      {item.accessKeyDisplay} · {item.region}
                    </span>
                    <span class="text-12-regular">
                      {item.writeEnabled
                        ? language.t("dataworks.connection.write.on")
                        : language.t("dataworks.connection.write.off")}
                    </span>
                  </div>
                  <Button variant="secondary" size="small" disabled={testing()} onClick={() => void onTest(item.id)}>
                    {language.t("dataworks.connection.test")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="small"
                    onClick={() => void dataworks.removeConnection(item.id)}
                  >
                    {language.t("dataworks.connection.delete")}
                  </Button>
                </li>
              )}
            </For>
          </ul>
        </Show>

        <form class="dwa-card p-4 flex flex-col gap-3" onSubmit={(event) => void onCreate(event)}>
          <h2 class="text-14-medium">{language.t("dataworks.connection.create")}</h2>
          <label class="flex flex-col gap-1">
            <span class="text-12-regular text-text-weak">{language.t("dataworks.connection.name")}</span>
            <input
              class="text-14-regular px-3 py-2 rounded-md border border-[color:var(--dwa-border)] bg-transparent"
              value={name()}
              required
              onInput={(e) => setName(e.currentTarget.value)}
            />
          </label>
          <label class="flex flex-col gap-1">
            <span class="text-12-regular text-text-weak">{language.t("dataworks.connection.region")}</span>
            <input
              class="text-14-regular px-3 py-2 rounded-md border border-[color:var(--dwa-border)] bg-transparent"
              value={region()}
              required
              onInput={(e) => setRegion(e.currentTarget.value)}
            />
          </label>
          <label class="flex flex-col gap-1">
            <span class="text-12-regular text-text-weak">{language.t("dataworks.connection.ak")}</span>
            <input
              class="text-14-regular px-3 py-2 rounded-md border border-[color:var(--dwa-border)] bg-transparent font-mono"
              value={accessKeyId()}
              required
              autocomplete="off"
              onInput={(e) => setAccessKeyId(e.currentTarget.value)}
            />
          </label>
          <label class="flex flex-col gap-1">
            <span class="text-12-regular text-text-weak">{language.t("dataworks.connection.sk")}</span>
            <input
              type="password"
              class="text-14-regular px-3 py-2 rounded-md border border-[color:var(--dwa-border)] bg-transparent font-mono"
              value={accessKeySecret()}
              required
              autocomplete="off"
              onInput={(e) => setAccessKeySecret(e.currentTarget.value)}
            />
          </label>
          <label class="flex items-center gap-2 text-14-regular">
            <input type="checkbox" checked={writeEnabled()} onChange={(e) => setWriteEnabled(e.currentTarget.checked)} />
            {language.t("dataworks.connection.write.toggle")}
          </label>
          <Button type="submit" variant="primary" class="dwa-btn-primary self-start">
            {language.t("dataworks.connection.save")}
          </Button>
        </form>

        <Show when={message()}>
          <p class="text-12-regular" role="status">
            {message()}
          </p>
        </Show>
      </div>
    </DataWorksShell>
  )
}
