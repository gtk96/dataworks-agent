#!/usr/bin/env bun
/**
 * Isolated parser worker process.
 * Invoked as: bun parser-worker.ts <filePath> <filename>
 * Constraints (enforced by caller): no network mount, read-only input, 1GiB mem, 1 CPU, 120s, 256MB stdout.
 * Never executes embedded content/macros.
 */

import { basename } from "node:path"

const filePathArg = process.argv[2]
const filenameArg = process.argv[3]
const filename = filenameArg ?? (filePathArg ? basename(filePathArg) : "document")

if (!filePathArg) {
  process.stdout.write(JSON.stringify({ error: "missing file path" }))
  process.exit(1)
}

const filePath: string = filePathArg

async function main() {
  const ext = filename.includes(".") ? filename.slice(filename.lastIndexOf(".")).toLowerCase() : ""
  const bytes = new Uint8Array(await Bun.file(filePath).arrayBuffer())

  if (ext === ".md" || ext === ".markdown" || ext === ".txt") {
    const text = new TextDecoder().decode(bytes)
    process.stdout.write(JSON.stringify({ text, pageCount: 1 }))
    return
  }

  if (ext === ".pdf") {
    try {
      const mod = (await import("pdf-parse" as string).catch(() => null)) as
        | { default: (b: Buffer) => Promise<{ text: string; numpages?: number }> }
        | null
      if (mod?.default) {
        const result = await mod.default(Buffer.from(bytes))
        process.stdout.write(JSON.stringify({ text: result.text ?? "", pageCount: result.numpages ?? 1 }))
        return
      }
      const raw = new TextDecoder("utf-8", { fatal: false }).decode(bytes)
      process.stdout.write(JSON.stringify({ text: raw, pageCount: 1 }))
      return
    } catch (e) {
      const raw = new TextDecoder("utf-8", { fatal: false }).decode(bytes)
      process.stdout.write(JSON.stringify({ text: raw, pageCount: 1, warning: String(e) }))
      return
    }
  }

  if (ext === ".docx") {
    try {
      const mammoth = (await import("mammoth" as string).catch(() => null)) as
        | { extractRawText: (input: { buffer: Buffer }) => Promise<{ value: string }> }
        | null
      if (mammoth?.extractRawText) {
        const result = await mammoth.extractRawText({ buffer: Buffer.from(bytes) })
        process.stdout.write(JSON.stringify({ text: result.value ?? "", pageCount: 1 }))
        return
      }
      const raw = new TextDecoder("utf-8", { fatal: false }).decode(bytes)
      const texts = [...raw.matchAll(/<w:t[^>]*>([^<]*)<\/w:t>/g)].map((m) => m[1] ?? "")
      process.stdout.write(JSON.stringify({ text: texts.length ? texts.join(" ") : raw, pageCount: 1 }))
      return
    } catch (e) {
      const raw = new TextDecoder("utf-8", { fatal: false }).decode(bytes)
      const texts = [...raw.matchAll(/<w:t[^>]*>([^<]*)<\/w:t>/g)].map((m) => m[1] ?? "")
      process.stdout.write(
        JSON.stringify({ text: texts.length ? texts.join(" ") : raw, pageCount: 1, warning: String(e) }),
      )
      return
    }
  }

  process.stdout.write(JSON.stringify({ error: `unsupported extension: ${ext}` }))
  process.exit(2)
}

main().catch((err) => {
  process.stdout.write(JSON.stringify({ error: err instanceof Error ? err.message : String(err) }))
  process.exit(1)
})
