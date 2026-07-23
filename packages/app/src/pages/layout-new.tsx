import { createEffect, type ParentProps } from "solid-js"
import { createStore } from "solid-js/store"
import { useNavigate } from "@solidjs/router"
import { DebugBar } from "@/components/debug-bar"
import { TabsInfoPopup } from "@/components/help-button"
import { Titlebar, type TitlebarUpdate } from "@/components/titlebar"
import { usePlatform } from "@/context/platform"
import { DataWorksConsoleLayout } from "@/components/dataworks/console-layout"
import { setNavigate } from "@/utils/notification-click"
import { setV2Toast, ToastRegion } from "@/utils/toast"

export default function NewLayout(props: ParentProps) {
  const platform = usePlatform()
  const navigate = useNavigate()
  setNavigate(navigate)
  const [state, setState] = createStore({ debugTools: false })
  const isDesktop = () => platform.platform === "desktop"

  createEffect(() => setV2Toast(true))

  const update: TitlebarUpdate = {
    version: () => {
      const state = platform.updater?.state()
      if (state?.status !== "ready") return
      return state.version
    },
    installing: () => platform.updater?.state().status === "installing",
    install: () => void platform.updater?.install(),
  }

  return (
    <div class="relative bg-v2-background-bg-deep flex-1 min-h-0 min-w-0 flex flex-col select-none [&_input]:select-text [&_textarea]:select-text [&_[contenteditable]]:select-text">
      {/* Desktop keeps native window chrome; web console uses DataWorks sidebar only. */}
      {isDesktop() && (
        <Titlebar
          update={update}
          debugTools={import.meta.env.DEV ? { visible: state.debugTools, toggle: () => setState("debugTools", (value) => !value) } : undefined}
        />
      )}
      <main class="flex-1 min-h-0 min-w-0 overflow-hidden flex flex-col items-stretch contain-strict">
        <DataWorksConsoleLayout>{props.children}</DataWorksConsoleLayout>
      </main>
      {import.meta.env.DEV && state.debugTools && <DebugBar inline />}
      <TabsInfoPopup />
      <ToastRegion v2 />
    </div>
  )
}
