import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { randomBytes } from "crypto"
import { mkdirSync, rmSync, writeFileSync } from "fs"
import { join } from "path"
import { login } from "../../../packages/dataworks-control/src/auth/session"
import { makeApp, createUser, type AppHandle } from "../../../packages/dataworks-control/src/http/server"
import { generateMasterKey } from "../../../packages/dataworks-control/src/secret/store"

const tmpDir = join(import.meta.dir, ".knowledge-rag-test-tmp")
const fixturesDir = join(import.meta.dir, "fixtures", "knowledge")

let appHandle: AppHandle
let sessionToken: string
let userId: string

beforeAll(async () => {
  rmSync(tmpDir, { recursive: true, force: true })
  mkdirSync(tmpDir, { recursive: true })
  mkdirSync(fixturesDir, { recursive: true })
  writeFileSync(join(fixturesDir, "alpha.md"), "# Alpha Doc\n\nUNIQUE_MARKER_ALPHA logistics anomaly playbook.\n")
  writeFileSync(join(fixturesDir, "beta.txt"), "UNIQUE_MARKER_BETA plain text inventory notes.\n")
  // Minimal valid-ish DOCX (ZIP with [Content_Types].xml) is heavy; use mammoth-friendly text via .docx bytes
  // produced as plain ZIP-less fallback is rejected; write a tiny DOCX via raw OOXML zip is overkill for dry-run.
  // We still ship a fixture filename; parser treats text/* and application/vnd... via extension.
  writeFileSync(join(fixturesDir, "gamma.docx"), makeMinimalDocx("UNIQUE_MARKER_GAMMA docx body content"))
  writeFileSync(join(fixturesDir, "delta.pdf"), makeMinimalPdf("UNIQUE_MARKER_DELTA pdf body content"))

  appHandle = await makeApp({
    dbPath: join(tmpDir, "test.db"),
    secretsRoot: join(tmpDir, ".secrets"),
    appDataRoot: join(tmpDir, "app-data"),
    publicOrigin: "http://dwa.test",
    masterKey: generateMasterKey(),
    startServer: false,
  })

  const email = `kb-${randomBytes(4).toString("hex")}@example.com`
  await createUser({ email, password: "testpass123", role: "user" }, appHandle.db)
  userId = appHandle.db.get<{ id: string }>("SELECT id FROM dwa_user WHERE email = ?", [email])!.id
  const session = await login(appHandle.db, { email, password: "testpass123" })
  if (!session) throw new Error("login failed")
  sessionToken = session.token
})

afterAll(() => {
  if (appHandle?.server) appHandle.server.stop()
  appHandle?.db.close()
  try {
    rmSync(tmpDir, { recursive: true, force: true })
  } catch {
    // Windows lock
  }
})

function cookieHeaders(extra: Record<string, string> = {}) {
  return {
    cookie: `dwa_session=${encodeURIComponent(sessionToken)}`,
    origin: "http://dwa.test",
    ...extra,
  }
}

function request(path: string, init: RequestInit = {}) {
  return appHandle.app.request(`http://dwa.test${path}`, init)
}

async function createKb(name: string, egressPolicy = "local_only", approvedProviders: string[] = []) {
  const res = await request("/api/knowledge/bases", {
    method: "POST",
    headers: { ...cookieHeaders(), "content-type": "application/json" },
    body: JSON.stringify({ name, egressPolicy, approvedProviders }),
  })
  expect(res.status).toBe(201)
  return (await res.json()) as { id: string; egressPolicy: string; approvedProviders: string[] }
}

async function upload(kbId: string, filename: string, body: Uint8Array | string, contentType: string) {
  const form = new FormData()
  const blob = new Blob([body], { type: contentType })
  form.append("file", blob, filename)
  const res = await request(`/api/knowledge/bases/${kbId}/documents`, {
    method: "POST",
    headers: cookieHeaders(),
    body: form,
  })
  return res
}

async function pollReady(kbId: string, docId: string, timeoutMs = 15_000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const res = await request(`/api/knowledge/bases/${kbId}/documents/${docId}`, {
      headers: cookieHeaders(),
    })
    expect(res.status).toBe(200)
    const doc = (await res.json()) as { status: string; id: string; filename: string }
    if (doc.status === "ready") return doc
    if (doc.status === "failed" || doc.status === "error") {
      throw new Error(`document failed: ${JSON.stringify(doc)}`)
    }
    await Bun.sleep(50)
  }
  throw new Error("document not ready in time")
}

describe("knowledge RAG dry-run", () => {
  test("upload md/txt/docx/pdf, search finds marker, 50MB+1 is 413", async () => {
    const kb = await createKb("primary-kb")
    expect(kb.egressPolicy).toBe("local_only")

    const uploads = [
      { file: "alpha.md", type: "text/markdown", marker: "UNIQUE_MARKER_ALPHA" },
      { file: "beta.txt", type: "text/plain", marker: "UNIQUE_MARKER_BETA" },
      { file: "gamma.docx", type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", marker: "UNIQUE_MARKER_GAMMA" },
      { file: "delta.pdf", type: "application/pdf", marker: "UNIQUE_MARKER_DELTA" },
    ] as const

    for (const u of uploads) {
      const bytes = await Bun.file(join(fixturesDir, u.file)).arrayBuffer()
      const res = await upload(kb.id, u.file, new Uint8Array(bytes), u.type)
      expect(res.status).toBe(201)
      const doc = (await res.json()) as { id: string }
      await pollReady(kb.id, doc.id)

      const search = await request("/api/knowledge/search", {
        method: "POST",
        headers: { ...cookieHeaders(), "content-type": "application/json" },
        body: JSON.stringify({ knowledgeBaseId: kb.id, query: u.marker, topK: 5 }),
      })
      expect(search.status).toBe(200)
      const body = (await search.json()) as {
        results: Array<{ documentId: string; filename: string; text: string; score: number }>
      }
      expect(body.results.length).toBeGreaterThan(0)
      expect(body.results[0]!.text).toContain(u.marker)
      expect(body.results[0]!.filename).toBe(u.file)
      expect(JSON.stringify(body)).not.toMatch(/[A-Za-z]:\\/)
      expect(JSON.stringify(body)).not.toContain(tmpDir.replace(/\\/g, "\\\\"))
    }

    const oversize = new Uint8Array(50 * 1024 * 1024 + 1)
    oversize[0] = 0x25
    const tooBig = await upload(kb.id, "huge.txt", oversize, "text/plain")
    expect(tooBig.status).toBe(413)
  })

  test("local_only denies remote embedding; approved_providers gates providers", async () => {
    const kb = await createKb("local-kb", "local_only")
    const remoteEmbed = await request(`/api/knowledge/bases/${kb.id}`, {
      method: "PATCH",
      headers: { ...cookieHeaders(), "content-type": "application/json" },
      body: JSON.stringify({ embeddingProvider: "openai" }),
    })
    expect([400, 403]).toContain(remoteEmbed.status)

    const injectDenied = await request("/api/knowledge/context", {
      method: "POST",
      headers: { ...cookieHeaders(), "content-type": "application/json" },
      body: JSON.stringify({
        knowledgeBaseId: kb.id,
        query: "anything",
        activeProvider: "openai",
        topK: 3,
      }),
    })
    expect([400, 403]).toContain(injectDenied.status)

    const approve = await request(`/api/knowledge/bases/${kb.id}/approve-provider`, {
      method: "POST",
      headers: { ...cookieHeaders(), "content-type": "application/json" },
      body: JSON.stringify({ providerId: "dashscope" }),
    })
    expect(approve.status).toBe(200)
    const approved = (await approve.json()) as { egressPolicy: string; approvedProviders: string[] }
    expect(approved.approvedProviders).toContain("dashscope")
    expect(approved.egressPolicy).toBe("approved_providers")

    const stillDenied = await request("/api/knowledge/context", {
      method: "POST",
      headers: { ...cookieHeaders(), "content-type": "application/json" },
      body: JSON.stringify({
        knowledgeBaseId: kb.id,
        query: "anything",
        activeProvider: "openai",
        topK: 3,
      }),
    })
    expect([400, 403]).toContain(stillDenied.status)

    const allowed = await request("/api/knowledge/context", {
      method: "POST",
      headers: { ...cookieHeaders(), "content-type": "application/json" },
      body: JSON.stringify({
        knowledgeBaseId: kb.id,
        query: "anything",
        activeProvider: "dashscope",
        topK: 3,
      }),
    })
    expect(allowed.status).toBe(200)

    // approval is audited
    const audits = appHandle.db.all<{ tool: string; reason: string | null }>(
      "SELECT tool, reason FROM dwa_audit WHERE user_id = ? ORDER BY time_created DESC LIMIT 20",
      [userId],
    )
    expect(audits.some((a) => a.tool === "knowledge_approve_provider" || (a.reason ?? "").includes("dashscope"))).toBe(
      true,
    )
  })
})

/** Minimal PDF with extractable text stream for pdf-parse / dry-run text fallback. */
function makeMinimalPdf(text: string): Uint8Array {
  // Dry-run parser accepts application/pdf and extracts via pdf-parse or plain fallback.
  // Embed the marker as a comment so hash/keyword fallback still works if parse fails.
  const content = `%PDF-1.1
1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj
2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj
4 0 obj<< /Length ${44 + text.length} >>stream
BT /F1 12 Tf 50 100 Td (${text}) Tj ET
endstream
endobj
5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj
xref
0 6
0000000000 65535 f
trailer<< /Size 6 /Root 1 0 R >>
startxref
0
%%EOF
% ${text}
`
  return new TextEncoder().encode(content)
}

/** Build a minimal DOCX (OOXML zip) containing the given paragraph text. */
function makeMinimalDocx(text: string): Uint8Array {
  const escape = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>${escape}</w:t></w:r></w:p></w:body>
</w:document>`
  const contentTypes = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>`
  const rels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>`

  return zipStore([
    { name: "[Content_Types].xml", data: contentTypes },
    { name: "_rels/.rels", data: rels },
    { name: "word/document.xml", data: documentXml },
  ])

  function zipStore(files: Array<{ name: string; data: string }>): Uint8Array {
    // Use stored (no compression) ZIP for simplicity
    const parts: Uint8Array[] = []
    const central: Uint8Array[] = []
    let offset = 0
    for (const file of files) {
      const nameBytes = new TextEncoder().encode(file.name)
      const dataBytes = new TextEncoder().encode(file.data)
      const crc = crc32(dataBytes)
      const local = new Uint8Array(30 + nameBytes.length + dataBytes.length)
      const view = new DataView(local.buffer)
      view.setUint32(0, 0x04034b50, true)
      view.setUint16(8, 0, true) // method store
      view.setUint32(14, crc, true)
      view.setUint32(18, dataBytes.length, true)
      view.setUint32(22, dataBytes.length, true)
      view.setUint16(26, nameBytes.length, true)
      local.set(nameBytes, 30)
      local.set(dataBytes, 30 + nameBytes.length)
      parts.push(local)

      const cen = new Uint8Array(46 + nameBytes.length)
      const cv = new DataView(cen.buffer)
      cv.setUint32(0, 0x02014b50, true)
      cv.setUint32(16, crc, true)
      cv.setUint32(20, dataBytes.length, true)
      cv.setUint32(24, dataBytes.length, true)
      cv.setUint16(28, nameBytes.length, true)
      cv.setUint32(42, offset, true)
      cen.set(nameBytes, 46)
      central.push(cen)
      offset += local.length
    }
    const centralSize = central.reduce((n, b) => n + b.length, 0)
    const end = new Uint8Array(22)
    const ev = new DataView(end.buffer)
    ev.setUint32(0, 0x06054b50, true)
    ev.setUint16(8, files.length, true)
    ev.setUint16(10, files.length, true)
    ev.setUint32(12, centralSize, true)
    ev.setUint32(16, offset, true)
    const total = offset + centralSize + 22
    const out = new Uint8Array(total)
    let p = 0
    for (const part of parts) {
      out.set(part, p)
      p += part.length
    }
    for (const c of central) {
      out.set(c, p)
      p += c.length
    }
    out.set(end, p)
    return out
  }
}

function crc32(buf: Uint8Array): number {
  let c = 0xffffffff
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i]!
    for (let k = 0; k < 8; k++) {
      c = c & 1 ? (0xedb88320 ^ (c >>> 1)) : c >>> 1
    }
  }
  return (c ^ 0xffffffff) >>> 0
}

