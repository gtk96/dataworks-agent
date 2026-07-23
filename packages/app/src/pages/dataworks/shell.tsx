import { A, useLocation, useNavigate, useSearchParams } from "@solidjs/router"
import { Match, Show, Switch, createEffect, createMemo, createSignal, type JSX, type ParentProps } from "solid-js"
import { useDataWorks } from "@/context/dataworks"
import { useLanguage } from "@/context/language"
import {
  isLoginPath,
  loginRedirectTarget,
  resolveAuthGate,
} from "@/pages/dataworks/route"
import { WriteConfirmationHost } from "@/pages/dataworks/write-host"
import "@/styles/dataworks-theme.css"

export function DataWorksShell(props: ParentProps): JSX.Element {
  const dataworks = useDataWorks()
  const language = useLanguage()
  const location = useLocation()
  const navigate = useNavigate()
  const [search] = useSearchParams<{ scope?: string; allUsers?: string }>()

  const gate = createMemo(() =>
    resolveAuthGate({
      user: dataworks.user() ?? null,
      pathname: location.pathname,
      searchParams: search,
    }),
  )

  createEffect(() => {
    const user = dataworks.user()
    if (user === undefined) return
    const result = gate()
    if (result.status === "anonymous" && !isLoginPath(location.pathname)) {
      const returnTo = encodeURIComponent(location.pathname + location.search)
      navigate(`/login?returnTo=${returnTo}`, { replace: true })
    }
  })

  return (
    <div data-component="dataworks-shell" class="flex flex-col flex-1 min-h-0 w-full">
      <Show
        when={dataworks.user() !== undefined}
        fallback={
          <div class="p-6 text-14-regular text-text-weak" data-state="loading">
            {language.t("dataworks.state.loading")}
          </div>
        }
      >
        <Show
          when={dataworks.user()}
          fallback={
            <div class="p-6 text-14-regular" data-state="anonymous">
              {language.t("dataworks.auth.redirecting")}
            </div>
          }
        >
          {(user) => (
            <Show
              when={gate().status !== "forbidden"}
              fallback={
                <div class="p-6 flex flex-col gap-2" data-state="forbidden" role="alert">
                  <h1 class="text-16-medium text-text-strong">{language.t("dataworks.audit.forbidden.title")}</h1>
                  <p class="text-14-regular text-text-weak">{language.t("dataworks.audit.forbidden.body")}</p>
                  <A href="/dataworks/audit" class="text-14-regular text-[color:var(--dwa-primary)]">
                    {language.t("dataworks.audit.forbidden.back")}
                  </A>
                </div>
              }
            >
              <div data-component="dataworks-page" class="w-full min-h-full">
                {props.children}
                <WriteConfirmationHost />
              </div>
            </Show>
          )}
        </Show>
      </Show>
    </div>
  )
}

export function LoginPage(): JSX.Element {
  const dataworks = useDataWorks()
  const language = useLanguage()
  const navigate = useNavigate()
  const [search] = useSearchParams<{ returnTo?: string }>()
  const [email, setEmail] = createSignal("")
  const [password, setPassword] = createSignal("")
  const [error, setError] = createSignal("")
  const [submitting, setSubmitting] = createSignal(false)

  createEffect(() => {
    if (dataworks.user()) {
      navigate(loginRedirectTarget(search.returnTo), { replace: true })
    }
  })

  async function onSubmit(event: Event) {
    event.preventDefault()
    if (submitting()) return
    setSubmitting(true)
    setError("")
    const result = await dataworks.login(email(), password())
    setSubmitting(false)
    if (!result.ok) {
      setError(
        result.status === 429
          ? language.t("dataworks.auth.rateLimited")
          : language.t("dataworks.auth.failed"),
      )
      return
    }
    navigate(loginRedirectTarget(search.returnTo), { replace: true })
  }

  return (
    <div
      data-component="dataworks-shell"
      class="flex flex-1 items-center justify-center p-6 min-h-0 w-full"
      style={{
        background:
          "radial-gradient(900px 420px at 15% 10%, rgb(59 130 246 / 16%), transparent 55%), radial-gradient(700px 360px at 85% 90%, rgb(99 102 241 / 14%), transparent 50%), #f0f2f5",
      }}
    >
      <form
        data-component="dataworks-login"
        class="w-full max-w-sm flex flex-col gap-4 p-7"
        style={{
          background: "#fff",
          "border-radius": "16px",
          border: "1px solid #e8eaed",
          "box-shadow": "0 1px 2px rgb(15 23 42 / 4%), 0 20px 48px rgb(15 23 42 / 10%)",
        }}
        onSubmit={(event) => void onSubmit(event)}
      >
        <div class="flex items-center gap-3 mb-1">
          <span
            aria-hidden="true"
            style={{
              display: "inline-flex",
              width: "36px",
              height: "36px",
              "border-radius": "10px",
              "align-items": "center",
              "justify-content": "center",
              background: "linear-gradient(135deg, #60a5fa, #3b82f6 50%, #6366f1)",
              color: "#fff",
              "font-size": "12px",
              "font-weight": "800",
              "box-shadow": "0 4px 14px rgb(59 130 246 / 40%)",
            }}
          >
            DW
          </span>
          <div>
            <h1 class="text-16-medium text-text-strong" style={{ margin: 0, "font-weight": 700 }}>
              {language.t("dataworks.auth.login.title")}
            </h1>
            <p class="text-12-regular text-text-weak" style={{ margin: "2px 0 0" }}>
              DataWorks Agent
            </p>
          </div>
        </div>
        <p class="text-12-regular text-text-weak" style={{ margin: 0 }}>
          {language.t("dataworks.auth.login.subtitle")}
        </p>
        <label class="flex flex-col gap-1.5">
          <span class="text-12-regular text-text-weak" style={{ "font-weight": 600 }}>
            {language.t("dataworks.auth.username")}
          </span>
          <input
            type="text"
            name="username"
            required
            autocomplete="username"
            placeholder="admin"
            value={email()}
            onInput={(e) => setEmail(e.currentTarget.value)}
            class="text-14-regular px-3 py-2.5 rounded-lg border border-[color:var(--dwa-border)] bg-[#f8fafc]"
          />
        </label>
        <label class="flex flex-col gap-1.5">
          <span class="text-12-regular text-text-weak" style={{ "font-weight": 600 }}>
            {language.t("dataworks.auth.password")}
          </span>
          <input
            type="password"
            name="password"
            required
            autocomplete="current-password"
            value={password()}
            onInput={(e) => setPassword(e.currentTarget.value)}
            class="text-14-regular px-3 py-2.5 rounded-lg border border-[color:var(--dwa-border)] bg-[#f8fafc]"
          />
        </label>
        <Show when={error()}>
          <p data-login-error class="text-12-regular dwa-status-danger" role="alert">
            {error()}
          </p>
        </Show>
        <button
          type="submit"
          class="dwa-btn-primary text-14-medium px-3 py-2.5"
          style={{ "min-height": "40px", "border-radius": "10px" }}
          disabled={submitting()}
        >
          {language.t("dataworks.auth.login.submit")}
        </button>
      </form>
    </div>
  )
}

export function ListStateBanner(props: {
  state: () => string
  onRetry?: () => void
  emptyKey?: "dataworks.state.empty" | "dataworks.knowledge.empty" | "dataworks.skills.empty"
}): JSX.Element {
  const language = useLanguage()
  return (
    <Switch>
      <Match when={props.state() === "loading"}>
        <p data-state="loading" class="text-14-regular text-text-weak">
          {language.t("dataworks.state.loading")}
        </p>
      </Match>
      <Match when={props.state() === "empty"}>
        <p data-state="empty" class="text-14-regular text-text-weak">
          {language.t(props.emptyKey ?? "dataworks.state.empty")}
        </p>
      </Match>
      <Match when={props.state() === "partial"}>
        <div data-state="partial" class="flex items-center gap-2 text-14-regular dwa-status-warning">
          <span>{language.t("dataworks.state.partial")}</span>
          <Show when={props.onRetry}>
            <button type="button" class="underline" onClick={props.onRetry}>
              {language.t("dataworks.state.retry")}
            </button>
          </Show>
        </div>
      </Match>
      <Match when={props.state() === "rate_limit"}>
        <div data-state="rate_limit" class="flex items-center gap-2 text-14-regular dwa-status-warning">
          <span>{language.t("dataworks.state.rateLimit")}</span>
          <Show when={props.onRetry}>
            <button type="button" class="underline" onClick={props.onRetry}>
              {language.t("dataworks.state.retry")}
            </button>
          </Show>
        </div>
      </Match>
      <Match when={props.state() === "error"}>
        <div data-state="error" class="flex items-center gap-2 text-14-regular dwa-status-danger">
          <span>{language.t("dataworks.state.error")}</span>
          <Show when={props.onRetry}>
            <button type="button" class="underline" onClick={props.onRetry}>
              {language.t("dataworks.state.retry")}
            </button>
          </Show>
        </div>
      </Match>
    </Switch>
  )
}
