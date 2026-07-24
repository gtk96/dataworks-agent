/**
 * Dashboard pure utilities.
 *
 * Keep display labels and project payload normalization out of the component.
 */
import { ServerConnection, serverName } from "@/context/server"

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

export function serverModelLabel(server: ServerConnection.Any | undefined, fallback: string) {
  return serverName(server) || fallback
}
