import { For, Show, createMemo, createSignal, onMount, type JSX } from "solid-js"
import { useLanguage } from "@/context/language"
import { QUICK_ACTION_KEYS, quickActionI18nKey, type QuickActionKey } from "./dashboard-utils"

type IconName = "database" | "activity" | "receipt" | "terminal" | "sparkle" | "paperclip" | "send" | "chevron"

function Icon(props: { name: IconName; size?: number; class?: string }): JSX.Element {
  const s = props.size ?? 16
  const common = {
    width: s,
    height: s,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "2",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "aria-hidden": "true",
    class: props.class,
  } as const
  switch (props.name) {
    case "database":
      return (
        <svg {...common}>
          <ellipse cx="12" cy="5" rx="9" ry="3" />
          <path d="M3 5v6c0 1.66 4.03 3 9 3s9-1.34 9-3V5" />
          <path d="M3 11v6c0 1.66 4.03 3 9 3s9-1.34 9-3v-6" />
        </svg>
      )
    case "activity":
      return (
        <svg {...common}>
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
        </svg>
      )
    case "receipt":
      return (
        <svg {...common}>
          <path d="M5 2h14v20l-3-2-3 2-3-2-3 2-2-2V2z" />
          <path d="M9 7h6M9 11h6M9 15h4" />
        </svg>
      )
    case "terminal":
      return (
        <svg {...common}>
          <polyline points="4 17 10 11 4 5" />
          <line x1="12" y1="19" x2="20" y2="19" />
        </svg>
      )
    case "sparkle":
      return (
        <svg {...common}>
          <path d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6L12 3z" />
          <path d="M18 14l.8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8L18 14z" />
        </svg>
      )
    case "paperclip":
      return (
        <svg {...common}>
          <path d="M21 12.5l-9 9a5.5 5.5 0 0 1-7.78-7.78l9-9a3.7 3.7 0 0 1 5.22 5.22L9.22 18.94a1.85 1.85 0 0 1-2.61-2.62L14.4 8.5" />
        </svg>
      )
    case "send":
      return (
        <svg {...common}>
          <path d="M12 19V5M5 12l7-7 7 7" />
        </svg>
      )
    case "chevron":
      return (
        <svg {...common}>
          <polyline points="6 9 12 15 18 9" />
        </svg>
      )
  }
}

const HINT_ICONS: Record<QuickActionKey, IconName> = {
  tables: "database",
  jobs: "activity",
  orders: "receipt",
  ping: "terminal",
}

export type EnvTone = "prod" | "staging" | "dev" | "unknown"

export function ChatHero(props: {
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

  function focusEnd() {
    const el = textareaRef
    if (!el) return
    const len = el.value.length
    el.setSelectionRange(len, len)
    el.focus()
  }

  function submit() {
    const text = value().trim()
    if (!text || props.disabled) return
    props.onSubmit(text)
  }

  function pickHint(key: QuickActionKey) {
    setValue(language.t(quickActionI18nKey(key, "prompt")))
    queueMicrotask(() => focusEnd())
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

  onMount(() => {
    queueMicrotask(() => textareaRef?.focus())
  })

  const envTag = createMemo<{ label: string; tone: EnvTone; fullLabel: string } | undefined>(() => {
    const env = props.scopeEnv
    if (env === "prod") {
      return { label: language.t("dataworks.chat.env.prod"), tone: "prod", fullLabel: language.t("dataworks.chat.env.prod.full") }
    }
    if (env === "staging") {
      return { label: language.t("dataworks.chat.env.staging"), tone: "staging", fullLabel: language.t("dataworks.chat.env.staging.full") }
    }
    if (env === "dev") {
      return { label: language.t("dataworks.chat.env.dev"), tone: "dev", fullLabel: language.t("dataworks.chat.env.dev.full") }
    }
    return undefined
  })

  return (
    <section class="dwa-chat-hero" data-component="dataworks-chat-hero">
      <header class="dwa-chat-brand">
        <span class="dwa-chat-brand-mark" aria-hidden="true">
          <Icon name="sparkle" size={18} />
        </span>
        <span class="dwa-chat-brand-label">{language.t("dataworks.shell.product")}</span>
      </header>

      <h1 class="dwa-chat-greeting">{language.t("dataworks.chat.hero")}</h1>
      <p class="dwa-chat-subtitle">{language.t("dataworks.chat.subtitle")}</p>

      <div class="dwa-chat-composer" data-component="dataworks-chat-composer">
        <textarea
          ref={(el) => (textareaRef = el)}
          class="dwa-chat-textarea"
          rows={2}
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
              class="dwa-chat-tool"
              data-tool="attach"
              aria-label={language.t("dataworks.chat.attach")}
            >
              <Icon name="paperclip" size={16} />
            </button>
            <span class="dwa-chat-tool-divider" aria-hidden="true" />
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
              <Icon name="database" size={14} class="dwa-chat-scope-icon" />
              <span class="dwa-chat-scope-text">{props.scopeLabel}</span>
              <Show when={envTag()}>
                {(tag) => (
                  <span
                    class="dwa-chat-env-tag"
                    data-tone={tag().tone}
                    aria-label={tag().fullLabel}
                    title={tag().fullLabel}
                  >
                    {tag().label}
                  </span>
                )}
              </Show>
              <Icon name="chevron" size={12} class="dwa-chat-chevron" />
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
              <Icon name="chevron" size={12} class="dwa-chat-chevron" />
            </button>
            <button
              type="button"
              class="dwa-chat-send"
              data-component="dataworks-send"
              aria-label={language.t("dataworks.chat.send")}
              disabled={!value().trim() || props.disabled}
              onClick={submit}
            >
              <Icon name="send" size={16} />
            </button>
          </div>
        </div>
      </div>

      <div class="dwa-chat-hints" role="list">
        <span class="dwa-chat-hints-label">{language.t("dataworks.chat.hints.try")}</span>
        <For each={QUICK_ACTION_KEYS}>
          {(key) => {
            const promptText = () => language.t(quickActionI18nKey(key, "prompt"))
            const metaText = () => language.t(quickActionI18nKey(key, "hint"))
            const categoryText = () => language.t(quickActionI18nKey(key, "category"))
            return (
              <button
                type="button"
                class="dwa-chat-hint"
                role="listitem"
                data-hint={key}
                aria-label={promptText()}
                onClick={() => pickHint(key)}
              >
                <span class="dwa-chat-hint-icon" aria-hidden="true">
                  <Icon name={HINT_ICONS[key]} size={16} />
                </span>
                <span class="dwa-chat-hint-body">
                  <span class="dwa-chat-hint-text">{promptText()}</span>
                  <span class="dwa-chat-hint-meta" aria-hidden="true">{metaText()}</span>
                </span>
                <span class="dwa-chat-hint-category" aria-hidden="true">{categoryText()}</span>
              </button>
            )
          }}
        </For>
      </div>

      <footer class="dwa-chat-footer" data-component="dataworks-chat-footer">
        <div class="dwa-chat-footer-row dwa-chat-footer-row-primary">
          <span class="dwa-chat-footer-text">{language.t("dataworks.chat.footer.scope")}</span>
          <span class="dwa-chat-footer-sep" aria-hidden="true">·</span>
          <kbd class="dwa-chat-footer-kbd">⌘/Ctrl</kbd>
          <span class="dwa-chat-footer-plus" aria-hidden="true">+</span>
          <kbd class="dwa-chat-footer-kbd">Enter</kbd>
          <span class="dwa-chat-footer-text">{language.t("dataworks.chat.footer.shortcut")}</span>
        </div>
        <div class="dwa-chat-footer-row dwa-chat-footer-row-secondary">
          <span class="dwa-chat-footer-text">{language.t("dataworks.chat.footer.compliance")}</span>
        </div>
      </footer>
    </section>
  )
}