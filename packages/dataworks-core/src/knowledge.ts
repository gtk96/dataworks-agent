/** Knowledge domain types for document ingestion and tenant-isolated RAG. */

import type { UserID } from "./identity"

export const MAX_KNOWLEDGE_FILE_BYTES = 50 * 1024 * 1024
export const MAX_KNOWLEDGE_PAGES = 1000
export const MAX_PARSE_MS = 10 * 60 * 1000
export const EMBEDDING_DIMS = 1024
export const OFFLINE_EMBEDDING_MODEL = "fast-multilingual-e5-large" as const

export type KnowledgeEgressPolicy = "local_only" | "approved_providers"

export type DocumentStatus =
  | "pending"
  | "uploading"
  | "quarantined"
  | "parsing"
  | "indexing"
  | "ready"
  | "failed"
  | "error"

export type IndexStatus = "ready" | "degraded" | "rebuilding" | "missing"

export type AllowedKnowledgeMime =
  | "application/pdf"
  | "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
  | "text/markdown"
  | "text/plain"
  | "text/x-markdown"

export const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".md", ".txt", ".markdown"] as const
export const ALLOWED_MIME_TYPES: readonly string[] = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/markdown",
  "text/x-markdown",
  "text/plain",
]

export interface KnowledgeBase {
  readonly id: string
  readonly userId: UserID
  readonly name: string
  readonly egressPolicy: KnowledgeEgressPolicy
  readonly approvedProviders: readonly string[]
  readonly embeddingProvider: "local" | "remote"
  readonly indexStatus: IndexStatus
  readonly timeCreated: number
  readonly timeUpdated: number
}

export interface KnowledgeDocument {
  readonly id: string
  readonly knowledgeBaseId: string
  readonly userId: UserID
  readonly filename: string
  readonly mimeType: string
  readonly byteSize: number
  readonly sha256: string
  readonly status: DocumentStatus
  readonly pageCount: number | null
  readonly error: string | null
  readonly connectionId: string | null
  readonly timeCreated: number
  readonly timeUpdated: number
}

export interface KnowledgeChunkRow {
  readonly id: string
  readonly userId: UserID
  readonly knowledgeBaseId: string
  readonly documentId: string
  readonly connectionId: string | null
  readonly filename: string
  readonly startOffset: number
  readonly endOffset: number
  readonly text: string
  readonly vector: number[]
}

export interface KnowledgeSearchHit {
  readonly documentId: string
  readonly knowledgeBaseId: string
  readonly filename: string
  readonly text: string
  readonly startOffset: number
  readonly endOffset: number
  readonly score: number
  readonly citation: string
}

export interface KnowledgeSearchResult {
  readonly results: KnowledgeSearchHit[]
  readonly degraded: boolean
  readonly mode: "vector" | "keyword"
}

export interface ProviderApprovalEvent {
  readonly knowledgeBaseId: string
  readonly userId: UserID
  readonly providerId: string
  readonly timeCreated: number
}

export function sanitizeFilename(name: string): string {
  const base = name.replace(/\\/g, "/").split("/").pop() ?? "document"
  const cleaned = base.replace(/[^\w.\- ()[\]]+/g, "_").replace(/^\.+/, "")
  return cleaned.slice(0, 200) || "document"
}

export function extensionOf(filename: string): string {
  const i = filename.lastIndexOf(".")
  if (i < 0) return ""
  return filename.slice(i).toLowerCase()
}

export function isAllowedUpload(filename: string, mimeType: string | null | undefined): boolean {
  const ext = extensionOf(filename)
  if (!(ALLOWED_EXTENSIONS as readonly string[]).includes(ext)) return false
  if (!mimeType) return true
  const mt = mimeType.toLowerCase().split(";")[0]!.trim()
  if (mt === "application/octet-stream") return true
  if (ALLOWED_MIME_TYPES.includes(mt)) return true
  // browsers sometimes send empty or generic types
  if (mt === "" || mt === "application/x-msdownload") return false
  // allow text/* for md/txt
  if ((ext === ".md" || ext === ".markdown" || ext === ".txt") && mt.startsWith("text/")) return true
  return false
}

export function defaultMimeForExtension(ext: string): string {
  switch (ext) {
    case ".pdf":
      return "application/pdf"
    case ".docx":
      return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    case ".md":
    case ".markdown":
      return "text/markdown"
    case ".txt":
      return "text/plain"
    default:
      return "application/octet-stream"
  }
}

/**
 * Whether RAG chunks from a knowledge base may be injected into the active OpenCode Provider.
 * - local_only: only configured local provider ids
 * - approved_providers: exact provider id match against approvedProviders
 */
export function canInjectIntoProvider(
  kb: Pick<KnowledgeBase, "egressPolicy" | "approvedProviders">,
  activeProvider: string,
  localProviderIds: readonly string[] = ["local", "ollama", "lmstudio", "openai-compatible-local"],
): boolean {
  if (!activeProvider) return false
  if (kb.egressPolicy === "local_only") {
    return localProviderIds.includes(activeProvider)
  }
  return kb.approvedProviders.includes(activeProvider)
}

export function citationFor(doc: { id: string; filename: string }, start: number, end: number): string {
  // Never absolute paths — only document id + filename + offsets
  return `kbdoc://${doc.id}/${encodeURIComponent(doc.filename)}#${start}-${end}`
}
