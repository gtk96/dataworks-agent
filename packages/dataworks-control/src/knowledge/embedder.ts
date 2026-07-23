/**
 * Embedding provider for knowledge RAG.
 * Offline: FastEmbed MLE5Large from packaged assets (never implicit download).
 * Dry-run / explicit hash: deterministic local hash embedding (1024 dims).
 *
 * Fail-closed for product paths: when MLE5 is required (default outside dry-run/hash),
 * a PENDING or missing archiveSha256 refuses to create a silent hash embedder.
 * Hash mode is only used when forceHash, DATAWORKS_AGENT_DRY_RUN=1, or DWA_EMBEDDING_MODE=hash.
 */

import { createHash } from "crypto"
import { existsSync, readFileSync, readdirSync, statSync } from "fs"
import { join, dirname } from "path"
import { EMBEDDING_DIMS, OFFLINE_EMBEDDING_MODEL } from "@dataworks-agent/core"

export type EmbeddingMode = "mle5" | "hash"

export interface EmbeddingProvider {
  readonly modelId: string
  readonly dims: number
  readonly mode: EmbeddingMode
  embedDocuments(texts: string[]): Promise<number[][]>
  embedQuery(text: string): Promise<number[]>
}

export interface EmbedderOptions {
  /** Force hash mode (dry-run / tests). */
  readonly forceHash?: boolean
  /** Directory containing extracted MLE5Large model files. */
  readonly modelDir?: string
  /** Path to assets/embeddings/manifest.json */
  readonly manifestPath?: string
}

const DEFAULT_MANIFEST = join(import.meta.dir, "..", "..", "assets", "embeddings", "manifest.json")

interface Manifest {
  modelId: string
  dims: number
  archiveUrl: string
  archiveSha256: string
  extractedDir: string
  extractedFiles: Array<{ path: string; sha256: string }>
  license?: string
}

/** True when product/staging MLE5 path is required (no silent hash fallback). */
export function requiresMle5Integrity(options: EmbedderOptions = {}): boolean {
  if (options.forceHash) return false
  if (process.env.DATAWORKS_AGENT_DRY_RUN === "1") return false
  if (process.env.DWA_EMBEDDING_MODE === "hash") return false
  // Explicit mle5 or default (unset / other) both require integrity.
  return true
}

export function isManifestHashPending(archiveSha256: string | undefined | null): boolean {
  if (archiveSha256 == null) return true
  const v = archiveSha256.trim()
  return v.length === 0 || v === "PENDING"
}

export class EmbeddingManifestError extends Error {
  readonly code = "EMBEDDING_MANIFEST_PENDING" as const
  constructor(message: string) {
    super(message)
    this.name = "EmbeddingManifestError"
  }
}

export async function createEmbedder(options: EmbedderOptions = {}): Promise<EmbeddingProvider> {
  const allowHash =
    options.forceHash === true ||
    process.env.DATAWORKS_AGENT_DRY_RUN === "1" ||
    process.env.DWA_EMBEDDING_MODE === "hash"

  if (allowHash) {
    return createHashEmbedder()
  }

  // Product / mle5 path: fail closed — never silently fall back to hash.
  const manifestPath = options.manifestPath ?? DEFAULT_MANIFEST
  if (!existsSync(manifestPath)) {
    throw new EmbeddingManifestError(
      `MLE5 embedding manifest missing at ${manifestPath}. Run: bun scripts/fetch-embedding-model.ts (requires network). Or set DWA_EMBEDDING_MODE=hash for dry-run only.`,
    )
  }

  let manifest: Manifest
  try {
    manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Manifest
  } catch (e) {
    throw new EmbeddingManifestError(
      `MLE5 embedding manifest unreadable at ${manifestPath}: ${e instanceof Error ? e.message : String(e)}`,
    )
  }

  if (isManifestHashPending(manifest.archiveSha256)) {
    throw new EmbeddingManifestError(
      `MLE5 embedding archiveSha256 is PENDING/empty in ${manifestPath}. ` +
        `Release and staging require a real SHA-256 from bun scripts/fetch-embedding-model.ts. ` +
        `Hash embedder is only allowed when DWA_EMBEDDING_MODE=hash or DATAWORKS_AGENT_DRY_RUN=1.`,
    )
  }

  const configuredDir =
    options.modelDir ?? join(dirname(manifestPath), manifest.extractedDir || "fast-multilingual-e5-large")
  const modelDir = resolveModelDir(configuredDir)
  if (!modelDir) {
    throw new EmbeddingManifestError(
      `MLE5 model directory missing or incomplete at ${configuredDir} (need model.onnx). Run: bun scripts/fetch-embedding-model.ts`,
    )
  }

  return await createFastEmbedProvider(modelDir, manifest)
}

/** Prefer directory that actually contains model.onnx (handles nested tarball layout). */
export function resolveModelDir(configuredDir: string): string | null {
  if (!existsSync(configuredDir)) return null
  const directOnnx = join(configuredDir, "model.onnx")
  if (existsSync(directOnnx)) return configuredDir
  // Common layout after tar: <extractedDir>/<extractedDir>/model.onnx
  const base = configuredDir.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "fast-multilingual-e5-large"
  const nested = join(configuredDir, base)
  if (existsSync(join(nested, "model.onnx"))) return nested
  // Last resort: single subdirectory that holds model.onnx
  try {
    for (const name of readdirSync(configuredDir)) {
      if (name.startsWith("._")) continue
      const child = join(configuredDir, name)
      try {
        if (statSync(child).isDirectory() && existsSync(join(child, "model.onnx"))) return child
      } catch {
        // ignore
      }
    }
  } catch {
    // ignore
  }
  return existsSync(configuredDir) ? configuredDir : null
}

function createHashEmbedder(): EmbeddingProvider {
  return {
    modelId: "deterministic-hash-v1",
    dims: EMBEDDING_DIMS,
    mode: "hash",
    // Dry-run hash mode intentionally uses the same string for query/passage so
    // exact-marker retrieval works without claiming semantic quality.
    async embedDocuments(texts: string[]) {
      return texts.map((t) => hashEmbed(t))
    },
    async embedQuery(text: string) {
      return hashEmbed(text)
    },
  }
}

/** Deterministic 1024-d unit-ish vector from SHA-256 expanded stream. */
export function hashEmbed(text: string): number[] {
  const out = new Array<number>(EMBEDDING_DIMS)
  let seed = text
  let filled = 0
  while (filled < EMBEDDING_DIMS) {
    const digest = createHash("sha256").update(seed).digest()
    for (let i = 0; i < digest.length && filled < EMBEDDING_DIMS; i += 2) {
      const v = ((digest[i]! << 8) | digest[i + 1]!) / 65535
      out[filled++] = v * 2 - 1
    }
    seed = digest.toString("hex")
  }
  // L2 normalize
  let norm = 0
  for (const x of out) norm += x * x
  norm = Math.sqrt(norm) || 1
  for (let i = 0; i < out.length; i++) out[i] = out[i]! / norm
  return out
}

async function createFastEmbedProvider(modelDir: string, manifest: Manifest): Promise<EmbeddingProvider> {
  // fastembed is optional at typecheck time; runtime may load packaged binary
  const fastembed = (await import("fastembed" as string).catch(() => null)) as {
    EmbeddingModel?: { MLE5Large?: unknown }
    FlagEmbedding?: {
      init: (opts: Record<string, unknown>) => Promise<{
        passageEmbed: (texts: string[], batch?: number) => AsyncGenerator<number[][], void, unknown> | Promise<number[][]>
        queryEmbed: (text: string) => Promise<number[]> | AsyncGenerator<number[], void, unknown>
      }>
    }
  } | null

  if (!fastembed) {
    throw new EmbeddingManifestError(
      "fastembed package failed to load; cannot initialize MLE5 embedder. Install dependencies or set DWA_EMBEDDING_MODE=hash for dry-run.",
    )
  }
  const EmbeddingModel = fastembed.EmbeddingModel
  const FlagEmbedding = fastembed.FlagEmbedding

  if (!FlagEmbedding || !EmbeddingModel?.MLE5Large) {
    throw new EmbeddingManifestError(
      "fastembed MLE5Large unavailable; cannot initialize MLE5 embedder.",
    )
  }

  let embedder: Awaited<ReturnType<typeof FlagEmbedding.init>>
  try {
    embedder = await FlagEmbedding.init({
      model: EmbeddingModel.MLE5Large,
      cacheDir: modelDir,
      maxLength: 512,
    })
  } catch (e) {
    throw new EmbeddingManifestError(
      `Failed to init MLE5 FlagEmbedding: ${e instanceof Error ? e.message : String(e)}`,
    )
  }

  return {
    modelId: manifest.modelId || OFFLINE_EMBEDDING_MODEL,
    dims: manifest.dims || EMBEDDING_DIMS,
    mode: "mle5",
    async embedDocuments(texts: string[]) {
      const result = embedder.passageEmbed(texts, 32)
      if (Symbol.asyncIterator in Object(result)) {
        const rows: number[][] = []
        for await (const batch of result as AsyncGenerator<number[][]>) {
          rows.push(...batch)
        }
        return rows
      }
      return result as Promise<number[][]>
    },
    async embedQuery(text: string) {
      const result = embedder.queryEmbed(text)
      if (Symbol.asyncIterator in Object(result)) {
        for await (const row of result as AsyncGenerator<number[]>) {
          return Array.isArray(row[0]) ? (row as unknown as number[]) : row
        }
        throw new EmbeddingManifestError("MLE5 queryEmbed yielded no vectors")
      }
      const vec = await (result as Promise<number[] | number[][]>)
      return Array.isArray(vec[0]) ? (vec as number[][])[0]! : (vec as number[])
    },
  }
}
