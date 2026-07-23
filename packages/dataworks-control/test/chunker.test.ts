import { describe, expect, test } from "bun:test"
import { chunkText, estimateTokens, MAX_CHUNK_TOKENS, MAX_OVERLAP_TOKENS } from "../src/knowledge/chunker"

describe("bounded chunker", () => {
  test("empty and whitespace create no chunks", () => {
    expect(chunkText("")).toEqual([])
    expect(chunkText("   \n\t  ")).toEqual([])
    expect(chunkText("  ")).toEqual([])
  })

  test("chunks are <= 512 model tokens", () => {
    const paragraph = "段落 alpha 中文 mixed. ".repeat(80)
    const text = Array.from({ length: 12 }, (_, i) => `Section ${i}. ${paragraph}`).join("\n\n")
    const chunks = chunkText(text)
    expect(chunks.length).toBeGreaterThan(1)
    for (const chunk of chunks) {
      expect(estimateTokens(chunk.text)).toBeLessThanOrEqual(MAX_CHUNK_TOKENS)
      expect(chunk.text.trim().length).toBeGreaterThan(0)
    }
  })

  test("overlap is <= 64 tokens and source offsets are monotonic", () => {
    const body = "word ".repeat(2000)
    const chunks = chunkText(body)
    expect(chunks.length).toBeGreaterThan(2)

    for (let i = 0; i < chunks.length; i++) {
      const c = chunks[i]!
      expect(c.start).toBeGreaterThanOrEqual(0)
      expect(c.end).toBeGreaterThan(c.start)
      expect(c.end).toBeLessThanOrEqual(body.length)
      expect(body.slice(c.start, c.end)).toBe(c.text)
      if (i > 0) {
        const prev = chunks[i - 1]!
        expect(c.start).toBeGreaterThanOrEqual(prev.start)
        expect(c.start).toBeLessThan(prev.end)
        const overlapText = body.slice(c.start, prev.end)
        expect(estimateTokens(overlapText)).toBeLessThanOrEqual(MAX_OVERLAP_TOKENS)
      }
    }
  })

  test("handles Unicode paragraphs without dropping content", () => {
    const text = "Hello 世界 🚀\n\nSecond ¶ paragraph with café.\n\n第三段 content."
    const chunks = chunkText(text)
    expect(chunks.length).toBeGreaterThanOrEqual(1)
    const joined = chunks.map((c) => c.text).join("")
    for (const token of ["Hello", "世界", "café", "第三段"]) {
      expect(joined).toContain(token)
    }
    expect(chunks[0]!.start).toBe(0)
    expect(chunks[chunks.length - 1]!.end).toBe(text.length)
  })
})
