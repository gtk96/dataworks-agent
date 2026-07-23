/**
 * Document parser for knowledge ingestion.
 * Heavy parsers (pdf-parse, mammoth) run in a separate worker process.
 */

import { spawn } from "node:child_process"
import { join } from "node:path"
import { extensionOf } from "@dataworks-agent/core"

export interface ParseResult {
  readonly text: string
  readonly pageCount: number
}

export interface ParseOptions {
  readonly timeoutMs?: number
  readonly maxOutputBytes?: number
  readonly workerScript?: string
}

const DEFAULT_TIMEOUT_MS = 120_000
const DEFAULT_MAX_OUTPUT = 256 * 1024 * 1024

/**
 * Parse a quarantined file path. Spawns parser-worker for pdf/docx.
 * md/txt are read directly (no macros).
 */
export async function parseDocument(
  filePath: string,
  filename: string,
  options: ParseOptions = {},
): Promise<ParseResult> {
  const ext = extensionOf(filename)
  if (ext === ".md" || ext === ".markdown" || ext === ".txt") {
    const file = Bun.file(filePath)
    const text = await file.text()
    return { text, pageCount: 1 }
  }

  const workerScript = options.workerScript ?? join(import.meta.dir, "parser-worker.ts")
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const maxOutput = options.maxOutputBytes ?? DEFAULT_MAX_OUTPUT

  return runParserWorker(workerScript, filePath, filename, timeoutMs, maxOutput)
}

function runParserWorker(
  script: string,
  filePath: string,
  filename: string,
  timeoutMs: number,
  maxOutput: number,
): Promise<ParseResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script, filePath, filename], {
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...process.env,
        // no extra network hints
      },
      windowsHide: true,
    })

    const chunks: Buffer[] = []
    let total = 0
    let settled = false

    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      child.kill("SIGKILL")
      reject(new Error("parser worker timeout"))
    }, timeoutMs)

    child.stdout?.on("data", (buf: Buffer) => {
      total += buf.length
      if (total > maxOutput) {
        if (!settled) {
          settled = true
          clearTimeout(timer)
          child.kill("SIGKILL")
          reject(new Error("parser worker output exceeded cap"))
        }
        return
      }
      chunks.push(buf)
    })

    let errBuf = ""
    child.stderr?.on("data", (buf: Buffer) => {
      errBuf += buf.toString("utf8").slice(0, 4000)
    })

    child.on("error", (err) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      reject(err)
    })

    child.on("close", (code) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      if (code !== 0) {
        reject(new Error(`parser worker exited ${code}: ${errBuf || "unknown"}`))
        return
      }
      try {
        const raw = Buffer.concat(chunks).toString("utf8")
        const parsed = JSON.parse(raw) as { text?: string; pageCount?: number; error?: string }
        if (parsed.error) {
          reject(new Error(parsed.error))
          return
        }
        resolve({
          text: typeof parsed.text === "string" ? parsed.text : "",
          pageCount: typeof parsed.pageCount === "number" ? parsed.pageCount : 1,
        })
      } catch (e) {
        reject(e instanceof Error ? e : new Error(String(e)))
      }
    })
  })
}

/**
 * In-process fallback used when worker spawn is unavailable (dry-run / tests).
 * Still never executes macros; only extracts plain text heuristics.
 */
export async function parseDocumentInProcess(filePath: string, filename: string): Promise<ParseResult> {
  const ext = extensionOf(filename)
  const bytes = new Uint8Array(await Bun.file(filePath).arrayBuffer())

  if (ext === ".md" || ext === ".markdown" || ext === ".txt") {
    return { text: new TextDecoder().decode(bytes), pageCount: 1 }
  }

  if (ext === ".pdf") {
    try {
      // Optional dependency; dry-run falls back if missing
      const mod = await import("pdf-parse" as string).catch(() => null) as
        | { default: (b: Buffer) => Promise<{ text: string; numpages?: number }> }
        | null
      if (mod?.default) {
        const result = await mod.default(Buffer.from(bytes))
        return { text: result.text ?? "", pageCount: result.numpages ?? 1 }
      }
      const raw = new TextDecoder("utf-8", { fatal: false }).decode(bytes)
      return { text: raw, pageCount: 1 }
    } catch {
      const raw = new TextDecoder("utf-8", { fatal: false }).decode(bytes)
      return { text: raw, pageCount: 1 }
    }
  }

  if (ext === ".docx") {
    try {
      const mammoth = (await import("mammoth" as string).catch(() => null)) as
        | { extractRawText: (input: { buffer: Buffer }) => Promise<{ value: string }> }
        | null
      if (mammoth?.extractRawText) {
        const result = await mammoth.extractRawText({ buffer: Buffer.from(bytes) })
        return { text: result.value ?? "", pageCount: 1 }
      }
      const raw = new TextDecoder("utf-8", { fatal: false }).decode(bytes)
      const texts = [...raw.matchAll(/<w:t[^>]*>([^<]*)<\/w:t>/g)].map((m) => m[1] ?? "")
      if (texts.length) return { text: texts.join(" "), pageCount: 1 }
      return { text: raw, pageCount: 1 }
    } catch {
      const raw = new TextDecoder("utf-8", { fatal: false }).decode(bytes)
      const texts = [...raw.matchAll(/<w:t[^>]*>([^<]*)<\/w:t>/g)].map((m) => m[1] ?? "")
      if (texts.length) return { text: texts.join(" "), pageCount: 1 }
      return { text: raw, pageCount: 1 }
    }
  }

  throw new Error(`unsupported extension: ${ext}`)
}
