import { Show, type JSX } from "solid-js"

export type ChatError =
  | { kind: "connection" }
  | { kind: "project" }
  | { kind: "runtime" }
  | { kind: "send"; message?: string }

export function ChatError(props: {
  error: ChatError | undefined
  onAddConnection?: () => void
  onRefreshProjects?: () => void
  onRetry?: () => void
  t: (key: string, fallback?: string) => string
}): JSX.Element {
  const visible = () => Boolean(props.error)
  return (
    <div
      class="dwa-chat-error"
      data-component="dataworks-chat-error"
      data-state={visible() ? "shown" : "hidden"}
      role="status"
      aria-live="polite"
    >
      <Show when={props.error?.kind === "connection"}>
        <span class="dwa-chat-error-text">{props.t("dataworks.dashboard.needConnectionBody")}</span>
        <Show when={props.onAddConnection}>
          <button type="button" class="dwa-chat-error-action" onClick={() => props.onAddConnection?.()}>
            {props.t("dataworks.connection.create")}
          </button>
        </Show>
      </Show>

      <Show when={props.error?.kind === "project"}>
        <span class="dwa-chat-error-text">{props.t("dataworks.dashboard.projectEmpty")}</span>
        <Show when={props.onRefreshProjects}>
          <button type="button" class="dwa-chat-error-action" onClick={() => props.onRefreshProjects?.()}>
            {props.t("dataworks.dashboard.refresh")}
          </button>
        </Show>
      </Show>

      <Show when={props.error?.kind === "runtime"}>
        <span class="dwa-chat-error-text">{props.t("dataworks.dashboard.runtimeMissingBody")}</span>
        <Show when={props.onRetry}>
          <button type="button" class="dwa-chat-error-action" onClick={() => props.onRetry?.()}>
            {props.t("dataworks.state.retry")}
          </button>
        </Show>
      </Show>

      <Show when={props.error?.kind === "send"}>
        <span class="dwa-chat-error-text">
          {props.error && props.error.kind === "send" && props.error.message
            ? props.error.message
            : props.t("dataworks.dashboard.sendFailedBody")}
        </span>
        <Show when={props.onRetry}>
          <button type="button" class="dwa-chat-error-action" onClick={() => props.onRetry?.()}>
            {props.t("dataworks.state.retry")}
          </button>
        </Show>
      </Show>
    </div>
  )
}