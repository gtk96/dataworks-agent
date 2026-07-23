import { Show, createMemo, createSignal, onMount, type JSX } from "solid-js"
import { useLanguage } from "@/context/language"

type IconName = "database" | "send" | "chevron"

function Icon(props: { name: IconName; size?: number; class?: string }): JSX.Element {
  const size = props.size ?? 16
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "2",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "aria-hidden": "true",
    class: props.class,
  } as const
  if (props.name === "database") {
    return (
      <svg {...common}>
        <ellipse cx="12" cy="5" rx="9" ry="3" />
        <path d="M3 5v6c0 1.66 4.03 3 9 3s9-1.34 9-3V5" />
        <path d="M3 11v6c0 1.66 4.03 3 9 3s9-1.34 9-3v-6" />
      </svg>
    )
  }
  if (props.name === "send") {
    return (
      <svg {...common}>
        <path d="M12 19V5M5 12l7-7 7 7" />
      </svg>
    )
  }
  return (
    <svg {...common}>
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

export type EnvTone = "prod" | "staging" | "dev" | "unknown"

export function ChatHero(props: {
  mode?: "panel"
  onSubmit: (text: string) => void
  disabled?: boolean
  scopeLabel: string
  scopeEnv: EnvTone
  modelLabel: string
  onPickScope?: () => void
  onPickModel?: () => void
}): JSX.Element {
  const language = useLanguage()
  const [value, setValue] = createSignal("")
  let textareaRef: HTMLTextAreaElement | undefined

  function submit() {
    const text = value().trim()
    if (!text || props.disabled) return
    props.onSubmit(text)
  }

  function onKeyDown(event: KeyboardEvent & { currentTarget: HTMLTextAreaElement }) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault()
      submit()
      return
    }
    if (event.key === "Escape" && document.activeElement === event.currentTarget) {
      event.currentTarget.blur()
    }
  }

  onMount(() => queueMicrotask(() => textareaRef?.focus()))

  const envTag = createMemo<{ label: string; fullLabel: string } | undefined>(() => {
    if (props.scopeEnv === "prod") {
      return { label: language.t("dataworks.chat.env.prod"), fullLabel: language.t("dataworks.chat.env.prod.full") }
    }
    if (props.scopeEnv === "staging") {
      return {
        label: language.t("dataworks.chat.env.staging"),
        fullLabel: language.t("dataworks.chat.env.staging.full"),
      }
    }
    if (props.scopeEnv === "dev") {
      return { label: language.t("dataworks.chat.env.dev"), fullLabel: language.t("dataworks.chat.env.dev.full") }
    }
  })

  return (
    <section class="dwa-chat-hero" data-component="dataworks-chat-hero" data-mode={props.mode ?? "panel"}>
      <header class="dwa-agent-heading">
        <strong>Agent</strong>
        <span>{language.t("dataworks.chat.subtitle")}</span>
      </header>

      <div class="dwa-chat-composer" data-component="dataworks-chat-composer">
        <textarea
          ref={(element) => (textareaRef = element)}
          class="dwa-chat-textarea"
          rows={4}
          placeholder={language.t("dataworks.dashboard.placeholder")}
          value={value()}
          disabled={props.disabled}
          onInput={(event) => setValue(event.currentTarget.value)}
          onKeyDown={onKeyDown}
          aria-label={language.t("dataworks.chat.placeholder.aria")}
        />

        <div class="dwa-chat-toolbar">
          <div class="dwa-chat-toolbar-left">
            <button
              type="button"
              class="dwa-chat-scope"
              data-slot="composer-scope"
              data-env={props.scopeEnv}
              aria-haspopup="listbox"
              aria-label={`${language.t("dataworks.chat.scope.change")}: ${props.scopeLabel}`}
              title={props.scopeLabel}
              onClick={() => props.onPickScope?.()}
            >
              <Icon name="database" size={14} />
              <span class="dwa-chat-scope-text">{props.scopeLabel}</span>
              <Show when={envTag()}>
                {(tag) => (
                  <span class="dwa-chat-env-tag" data-tone={props.scopeEnv} title={tag().fullLabel}>
                    {tag().label}
                  </span>
                )}
              </Show>
              <Icon name="chevron" size={12} />
            </button>
          </div>
          <div class="dwa-chat-toolbar-right">
            <button
              type="button"
              class="dwa-chat-model"
              data-slot="composer-model"
              aria-haspopup="listbox"
              aria-label={`${language.t("dataworks.chat.model.change")}: ${props.modelLabel}`}
              title={props.modelLabel}
              onClick={() => props.onPickModel?.()}
            >
              <span class="dwa-chat-model-dot" aria-hidden="true" />
              <span class="dwa-chat-model-text">{props.modelLabel}</span>
              <Icon name="chevron" size={12} />
            </button>
            <button
              type="button"
              class="dwa-chat-send"
              data-component="dataworks-send"
              aria-label={language.t("dataworks.chat.send")}
              disabled={!value().trim() || props.disabled}
              onClick={submit}
            >
              <Icon name="send" />
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}
