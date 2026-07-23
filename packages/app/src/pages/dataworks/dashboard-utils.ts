/**
 * Dashboard pure utilities.
 *
 * Only quick-action metadata + project payload normalization live here.
 * Visible text (hint prompts, labels, descriptions) belongs in i18n, where it
 * can be themed per language. See `dataworks.chat.hint.*` in zh.ts / en.ts.
 */

export type ChatReadiness = {
  ready: boolean
  reason?: "prompt"
}

export type ChatInput = {
  prompt: string
}

export function queryChatReadiness(input: ChatInput): ChatReadiness {
  if (!input.prompt.trim()) return { ready: false, reason: "prompt" }
  return { ready: true }
}

export type QuickActionKey = "tables" | "jobs" | "orders" | "ping"

export const QUICK_ACTION_KEYS: readonly QuickActionKey[] = ["tables", "jobs", "orders", "ping"]

/** Map a hint key to its i18n key. Caller passes the resulting text into language.t(). */
export function quickActionI18nKey(key: QuickActionKey, slot: "prompt" | "label" | "hint" | "category"): string {
  return `dataworks.chat.${slot}.${key}`
}

/** Normalize control-plane project payloads (id/name vs projectId/projectName). */
export function normalizeDataWorksProject(raw: Record<string, unknown>): {
  projectId: string
  projectName: string
  region?: string
  envType?: string
} | null {
  const idRaw = raw.projectId ?? raw.projectID ?? raw.id
  if (idRaw === undefined || idRaw === null || idRaw === "") return null
  const projectId = String(idRaw)
  const nameRaw = raw.projectName ?? raw.name ?? raw.projectIdentifier
  const projectName = typeof nameRaw === "string" && nameRaw.trim() ? nameRaw : projectId
  const region = typeof raw.region === "string" ? raw.region : undefined
  const envType = typeof raw.envType === "string" ? raw.envType : undefined
  return { projectId, projectName, region, envType }
}