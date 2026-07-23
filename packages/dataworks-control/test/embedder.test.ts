import { describe, expect, test, beforeEach, afterEach } from "bun:test"
import { mkdirSync, writeFileSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import {
  createEmbedder,
  hashEmbed,
  isManifestHashPending,
  requiresMle5Integrity,
  resolveModelDir,
  EmbeddingManifestError,
} from "../src/knowledge/embedder"
import { EMBEDDING_DIMS } from "@dataworks-agent/core"

const saved: Record<string, string | undefined> = {}

function stashEnv(...keys: string[]) {
  for (const k of keys) {
    saved[k] = process.env[k]
  }
}

function restoreEnv() {
  for (const [k, v] of Object.entries(saved)) {
    if (v === undefined) delete process.env[k]
    else process.env[k] = v
  }
  for (const k of Object.keys(saved)) delete saved[k]
}

describe("hash embedder (forceHash / dry-run)", () => {
  beforeEach(() => {
    stashEnv("DATAWORKS_AGENT_DRY_RUN", "DWA_EMBEDDING_MODE")
    delete process.env.DATAWORKS_AGENT_DRY_RUN
    delete process.env.DWA_EMBEDDING_MODE
  })
  afterEach(restoreEnv)

  test("forceHash produces hash mode with expected dims", async () => {
    const embedder = await createEmbedder({ forceHash: true })
    expect(embedder.mode).toBe("hash")
    expect(embedder.dims).toBe(EMBEDDING_DIMS)
    expect(embedder.modelId).toBe("deterministic-hash-v1")
    const vec = await embedder.embedQuery("hello")
    expect(vec.length).toBe(EMBEDDING_DIMS)
    // L2 ~ 1
    const norm = Math.sqrt(vec.reduce((s, x) => s + x * x, 0))
    expect(norm).toBeCloseTo(1, 5)
  })

  test("DWA_EMBEDDING_MODE=hash allows hash without forceHash", async () => {
    process.env.DWA_EMBEDDING_MODE = "hash"
    const embedder = await createEmbedder()
    expect(embedder.mode).toBe("hash")
  })

  test("DATAWORKS_AGENT_DRY_RUN=1 allows hash", async () => {
    process.env.DATAWORKS_AGENT_DRY_RUN = "1"
    const embedder = await createEmbedder()
    expect(embedder.mode).toBe("hash")
  })

  test("hashEmbed is deterministic", () => {
    expect(hashEmbed("same")).toEqual(hashEmbed("same"))
    expect(hashEmbed("a")).not.toEqual(hashEmbed("b"))
  })
})

describe("MLE5 fail-closed on PENDING manifest", () => {
  let dir: string
  let manifestPath: string

  beforeEach(() => {
    stashEnv("DATAWORKS_AGENT_DRY_RUN", "DWA_EMBEDDING_MODE")
    delete process.env.DATAWORKS_AGENT_DRY_RUN
    delete process.env.DWA_EMBEDDING_MODE
    dir = join(tmpdir(), `dwa-embed-test-${Date.now()}-${Math.random().toString(36).slice(2)}`)
    mkdirSync(dir, { recursive: true })
    manifestPath = join(dir, "manifest.json")
  })

  afterEach(() => {
    restoreEnv()
    try {
      rmSync(dir, { recursive: true, force: true })
    } catch {
      // ignore
    }
  })

  test("requiresMle5Integrity is true by default", () => {
    expect(requiresMle5Integrity()).toBe(true)
    expect(requiresMle5Integrity({ forceHash: true })).toBe(false)
  })

  test("isManifestHashPending detects PENDING and empty", () => {
    expect(isManifestHashPending("PENDING")).toBe(true)
    expect(isManifestHashPending("")).toBe(true)
    expect(isManifestHashPending("   ")).toBe(true)
    expect(isManifestHashPending(null)).toBe(true)
    expect(isManifestHashPending("abc".repeat(21).slice(0, 64))).toBe(false)
  })

  test("createEmbedder refuses PENDING when mode is mle5/default", async () => {
    writeFileSync(
      manifestPath,
      JSON.stringify({
        modelId: "fast-multilingual-e5-large",
        dims: 1024,
        archiveUrl: "https://example.invalid/x.tar.gz",
        archiveSha256: "PENDING",
        extractedDir: "fast-multilingual-e5-large",
        extractedFiles: [],
      }),
    )
    await expect(createEmbedder({ manifestPath })).rejects.toBeInstanceOf(EmbeddingManifestError)
    await expect(createEmbedder({ manifestPath })).rejects.toThrow(/PENDING/)
  })

  test("createEmbedder refuses empty archiveSha256 on product path", async () => {
    writeFileSync(
      manifestPath,
      JSON.stringify({
        modelId: "x",
        dims: 1024,
        archiveUrl: "https://example.invalid/x.tar.gz",
        archiveSha256: "",
        extractedDir: "d",
        extractedFiles: [],
      }),
    )
    await expect(createEmbedder({ manifestPath })).rejects.toBeInstanceOf(EmbeddingManifestError)
  })

  test("createEmbedder with DWA_EMBEDDING_MODE=hash ignores PENDING", async () => {
    process.env.DWA_EMBEDDING_MODE = "hash"
    writeFileSync(
      manifestPath,
      JSON.stringify({
        modelId: "x",
        dims: 1024,
        archiveUrl: "u",
        archiveSha256: "PENDING",
        extractedDir: "d",
        extractedFiles: [],
      }),
    )
    const embedder = await createEmbedder({ manifestPath })
    expect(embedder.mode).toBe("hash")
  })

  test("packaged manifest PENDING fails closed without forceHash", async () => {
    // Uses real packaged asset path (may be PENDING until fetch script is run).
    const realManifest = join(import.meta.dir, "../assets/embeddings/manifest.json")
    const raw = await Bun.file(realManifest).text()
    const m = JSON.parse(raw) as { archiveSha256: string }
    if (isManifestHashPending(m.archiveSha256)) {
      await expect(createEmbedder({ manifestPath: realManifest })).rejects.toBeInstanceOf(
        EmbeddingManifestError,
      )
    } else {
      // Real hash present: do not load fastembed here (slow / optional native).
      // Integrity helpers already cover PENDING; product path refuses hash mode.
      expect(isManifestHashPending(m.archiveSha256)).toBe(false)
      expect(requiresMle5Integrity()).toBe(true)
    }
  }, 15_000)})

describe("resolveModelDir nested tarball layout", () => {
  test("prefers subdirectory that contains model.onnx", () => {
    const root = join(tmpdir(), `dwa-modeldir-${Date.now()}-${Math.random().toString(36).slice(2)}`)
    const nested = join(root, "fast-multilingual-e5-large")
    mkdirSync(nested, { recursive: true })
    writeFileSync(join(nested, "model.onnx"), "stub")
    try {
      expect(resolveModelDir(root)).toBe(nested)
      // Direct layout
      expect(resolveModelDir(nested)).toBe(nested)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })
})
