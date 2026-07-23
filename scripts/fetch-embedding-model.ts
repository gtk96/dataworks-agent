#!/usr/bin/env bun
/**
 * Controlled asset-update job: download only the allowlisted FastEmbed MLE5Large archive,
 * verify archive SHA-256, extract, hash each file, and update manifest.json.
 * Refuses empty/uncommitted archive hash after download (must write real digest).
 */

import { createHash } from "crypto"
import { createWriteStream, existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "fs"
import { join, relative } from "path"
import { pipeline } from "stream/promises"
import { createGunzip } from "zlib"
import { extract } from "tar-fs"

const ALLOWED_URL = "https://storage.googleapis.com/qdrant-fastembed/fast-multilingual-e5-large.tar.gz"
const ROOT = join(import.meta.dir, "..")
const MANIFEST_PATH = join(ROOT, "packages/dataworks-control/assets/embeddings/manifest.json")
const OUT_DIR = join(ROOT, "packages/dataworks-control/assets/embeddings")

async function main() {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, "utf8")) as {
    archiveUrl: string
    archiveSha256: string
    extractedDir: string
    extractedFiles: Array<{ path: string; sha256: string }>
  }

  if (manifest.archiveUrl !== ALLOWED_URL) {
    throw new Error(`refusing non-allowlisted URL: ${manifest.archiveUrl}`)
  }

  const archivePath = join(OUT_DIR, "fast-multilingual-e5-large.tar.gz")
  mkdirSync(OUT_DIR, { recursive: true })

  console.log("Downloading", ALLOWED_URL)
  const res = await fetch(ALLOWED_URL)
  if (!res.ok || !res.body) throw new Error(`download failed: ${res.status}`)

  const hash = createHash("sha256")
  const file = createWriteStream(archivePath)
  const reader = res.body.getReader()
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    hash.update(value)
    file.write(value)
  }
  await new Promise<void>((resolve, reject) => file.end(() => resolve()))
  const digest = hash.digest("hex")
  if (!digest || digest.length !== 64) throw new Error("empty archive hash refused")

  if (manifest.archiveSha256 && manifest.archiveSha256 !== "PENDING" && manifest.archiveSha256 !== digest) {
    throw new Error(`archive hash mismatch: expected ${manifest.archiveSha256}, got ${digest}`)
  }

  const extractDir = join(OUT_DIR, manifest.extractedDir || "fast-multilingual-e5-large")
  mkdirSync(extractDir, { recursive: true })

  // Extract tar.gz
  const { createReadStream } = await import("fs")
  await pipeline(createReadStream(archivePath), createGunzip(), extract(extractDir))

  const files: Array<{ path: string; sha256: string }> = []
  walk(extractDir, (abs) => {
    const rel = relative(extractDir, abs).replace(/\\/g, "/")
    const sha = createHash("sha256").update(readFileSync(abs)).digest("hex")
    files.push({ path: rel, sha256: sha })
  })

  const next = {
    ...manifest,
    archiveSha256: digest,
    extractedFiles: files,
  }
  writeFileSync(MANIFEST_PATH, JSON.stringify(next, null, 2) + "\n")
  console.log("Updated manifest with archiveSha256=", digest, "files=", files.length)
}

function walk(dir: string, visit: (abs: string) => void) {
  for (const name of readdirSync(dir)) {
    const abs = join(dir, name)
    if (statSync(abs).isDirectory()) walk(abs, visit)
    else visit(abs)
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
