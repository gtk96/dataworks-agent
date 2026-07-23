import { A, useLocation, useNavigate } from "@solidjs/router"
import { createEffect, createMemo, createSignal, For, Show, type JSX, type ParentProps } from "solid-js"
import { Icon } from "@opencode-ai/ui/v2/icon"
import { useDataWorks } from "@/context/dataworks"
import { useLanguage } from "@/context/language"
import { useSettingsDialog } from "@/components/settings-dialog"
import {
  DATAWORKS_CONSOLE_ITEMS,
  activeDataWorksNavItem,
  isDataWorksProtectedPath,
  type DataWorksConsoleIcon,
} from "@/pages/dataworks/route"
import { StudioWorkbench } from "@/pages/dataworks/studio-workbench"
import "./console-layout.css"

export type Translator = ReturnType<typeof useLanguage>["t"]

export function shouldUseConsoleShell(pathname: string): boolean {
  return isDataWorksProtectedPath(pathname)
}

export function consolePageKey(pathname: string) {
  return activeDataWorksNavItem(pathname).key
}

export function consoleSurface(pathname: string) {
  if (!shouldUseConsoleShell(pathname)) return "none" as const
  if (activeDataWorksNavItem(pathname).key === "chat") return "workbench" as const
  return "management" as const
}

const ICON_MAP: Record<DataWorksConsoleIcon, "status" | "folder" | "grid-plus" | "monitor" | "branch" | "edit" | "check" | "settings-gear" | "help"> = {
  chat: "status",
  connection: "folder",
  table: "grid-plus",
  job: "monitor",
  mcp: "branch",
  skill: "edit",
  knowledge: "help",
  audit: "check",
  settings: "settings-gear",
}

export function consolePageTitle(pathname: string, t: Translator): string {
  const key = consolePageKey(pathname)
  return t(`dataworks.nav.${key}` as "dataworks.nav.connections")
}

export function DataWorksConsoleLayout(props: ParentProps): JSX.Element {
  const dataworks = useDataWorks()
  const language = useLanguage()
  const location = useLocation()
  const navigate = useNavigate()
  const showSettings = useSettingsDialog()
  const [mobileOpen, setMobileOpen] = createSignal(false)

  const pathname = createMemo(() => location.pathname)
  const useShell = createMemo(() => shouldUseConsoleShell(pathname()))
  const active = createMemo(() => activeDataWorksNavItem(pathname()))
  const surface = createMemo(() => consoleSurface(pathname()))
  const pageTitle = createMemo(() => consolePageTitle(pathname(), language.t))

  createEffect(() => {
    if (!useShell()) return
    const user = dataworks.user()
    if (user === undefined) return
    if (!user) {
      const returnTo = encodeURIComponent(pathname() + location.search)
      navigate(`/login?returnTo=${returnTo}`, { replace: true })
    }
  })

  createEffect(() => {
    // Close the drawer after route changes.
    pathname()
    setMobileOpen(false)
  })

  return (
    <Show when={useShell()} fallback={<>{props.children}</>}>
      <Show
        when={dataworks.user() !== undefined}
        fallback={
          <div data-state="loading" class="p-6 text-text-weak">
            {language.t("dataworks.state.loading")}
          </div>
        }
      >
        <Show
          when={dataworks.user()}
          fallback={
            <div data-state="anonymous" class="p-6">
              {language.t("dataworks.auth.redirecting")}
            </div>
          }
        >
          {(user) => (
            <div
              data-component="dataworks-console"
              data-surface={surface()}
              data-mobile-open={mobileOpen() ? "true" : "false"}
            >
              <Show when={mobileOpen()}>
                <button
                  type="button"
                  data-slot="console-backdrop"
                  aria-label={language.t("dataworks.shell.nav")}
                  onClick={() => setMobileOpen(false)}
                />
              </Show>
              <aside data-slot="console-sidebar">
                <A href="/" data-slot="console-brand" onClick={() => setMobileOpen(false)}>
                  <span class="dwa-brand-mark" aria-hidden="true">
                    DW
                  </span>
                  <span>{language.t("dataworks.shell.product")}</span>
                </A>
                <nav aria-label={language.t("dataworks.shell.nav")} data-slot="console-nav">
                  <For each={[...DATAWORKS_CONSOLE_ITEMS]}>
                    {(item) =>
                      item.key === "settings" ? (
                        <button
                          type="button"
                          data-slot="console-nav-item"
                          data-active={active().key === item.key ? "true" : "false"}
                          onClick={() => {
                            showSettings()
                            setMobileOpen(false)
                          }}
                        >
                          <Icon name={ICON_MAP[item.icon]} size="small" />
                          <span>{language.t(`dataworks.nav.${item.key}` as "dataworks.nav.connections")}</span>
                        </button>
                      ) : (
                        <A
                          href={item.href}
                          data-slot="console-nav-item"
                          data-active={active().key === item.key ? "true" : "false"}
                          onClick={() => setMobileOpen(false)}
                        >
                          <Icon name={ICON_MAP[item.icon]} size="small" />
                          <span>{language.t(`dataworks.nav.${item.key}` as "dataworks.nav.connections")}</span>
                        </A>
                      )
                    }
                  </For>
                </nav>
                <div data-slot="console-account">
                  <span class="text-12-regular text-text-weak truncate">{user().email}</span>
                  <button
                    type="button"
                    data-slot="console-logout"
                    onClick={() => void dataworks.logout().then(() => navigate("/login", { replace: true }))}
                  >
                    {language.t("dataworks.auth.logout")}
                  </button>
                </div>
              </aside>
              <Show
                when={surface() === "workbench"}
                fallback={
                  <section data-slot="console-main">
                    <header data-slot="console-topbar">
                      <button
                        type="button"
                        data-slot="console-menu"
                        aria-label={language.t("dataworks.shell.nav")}
                        onClick={() => setMobileOpen((value) => !value)}
                      >
                        <Icon name="menu" size="small" />
                      </button>
                      <div data-slot="console-crumb">
                        <span class="text-12-regular text-text-weak">{language.t("dataworks.shell.console")}</span>
                        <span class="text-12-regular text-text-weak">/</span>
                        <h1>{pageTitle()}</h1>
                      </div>
                    </header>
                    <main data-slot="console-content">{props.children}</main>
                  </section>
                }
              >
                <StudioWorkbench agent={props.children} />
              </Show>
            </div>
          )}
        </Show>
      </Show>
    </Show>
  )
}
