/** Bounded text chunker for knowledge ingestion. */

export const MAX_CHUNK_TOKENS = 512
export const MAX_OVERLAP_TOKENS = 64

/** Approximate model tokens: ~4 chars / token for mixed CJK+Latin, floor 1 for non-empty. */
export function estimateTokens(text: string): number {
  if (!text) return 0
  // Count CJK/emoji-ish as ~1 token each, latin groups as ~4 chars.
  let tokens = 0
  let latinRun = 0
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 0
    const isCjk =
      (code >= 0x4e00 && code <= 0x9fff) ||
      (code >= 0x3400 && code <= 0x4dbf) ||
      (code >= 0x3040 && code <= 0x30ff) ||
      (code >= 0xac00 && code <= 0xd7af) ||
      code > 0xffff
    if (isCjk) {
      if (latinRun > 0) {
        tokens += Math.ceil(latinRun / 4)
        latinRun = 0
      }
      tokens += 1
    } else if (/\s/.test(ch)) {
      if (latinRun > 0) {
        tokens += Math.ceil(latinRun / 4)
        latinRun = 0
      }
      // whitespace is cheap; ignore for budgeting
    } else {
      latinRun += 1
    }
  }
  if (latinRun > 0) tokens += Math.ceil(latinRun / 4)
  return Math.max(tokens, text.trim().length === 0 ? 0 : 1)
}

export interface TextChunk {
  readonly text: string
  readonly start: number
  readonly end: number
  readonly tokenCount: number
}

export interface ChunkOptions {
  readonly maxTokens?: number
  readonly overlapTokens?: number
}

/**
 * Split text into chunks of at most maxTokens with bounded overlap.
 * Offsets are absolute into the original string and monotonic.
 */
export function chunkText(text: string, options: ChunkOptions = {}): TextChunk[] {
  const maxTokens = options.maxTokens ?? MAX_CHUNK_TOKENS
  const overlapTokens = Math.min(options.overlapTokens ?? MAX_OVERLAP_TOKENS, maxTokens - 1)
  if (!text || !text.trim()) return []

  const units = splitUnits(text)
  if (units.length === 0) return []

  const chunks: TextChunk[] = []
  let i = 0
  while (i < units.length) {
    // Oversized single unit → hard character slice
    if (units[i]!.tokens > maxTokens) {
      const unit = units[i]!
      chunks.push(...hardSlice(unit.text, unit.start, maxTokens))
      i += 1
      continue
    }

    let tokenSum = 0
    let end = i
    while (end < units.length) {
      const next = units[end]!
      if (next.tokens > maxTokens) break
      const add = next.tokens
      if (tokenSum > 0 && tokenSum + add > maxTokens) break
      tokenSum += add
      end += 1
      if (tokenSum >= maxTokens) break
    }
    if (end === i) {
      const unit = units[i]!
      chunks.push(...hardSlice(unit.text, unit.start, maxTokens))
      i += 1
      continue
    }

    const startOffset = units[i]!.start
    const endOffset = units[end - 1]!.end
    const slice = text.slice(startOffset, endOffset)
    chunks.push({
      text: slice,
      start: startOffset,
      end: endOffset,
      tokenCount: estimateTokens(slice),
    })

    if (end >= units.length) break

    // Step back for overlap: include up to overlapTokens of prior units
    let backTokens = 0
    let nextStart = end
    for (let j = end - 1; j >= i; j--) {
      backTokens += units[j]!.tokens
      if (backTokens >= overlapTokens) {
        nextStart = j
        break
      }
      nextStart = j
    }
    // Ensure forward progress
    if (nextStart <= i) nextStart = i + 1
    i = nextStart
  }

  return chunks.filter((c) => c.text.trim().length > 0)
}

interface Unit {
  text: string
  start: number
  end: number
  tokens: number
}

function splitUnits(text: string): Unit[] {
  const units: Unit[] = []
  // Prefer paragraph breaks, then sentences, then words
  const paragraphRe = /\n{2,}/g
  let last = 0
  const paragraphs: Array<{ start: number; end: number; text: string }> = []
  let m: RegExpExecArray | null
  while ((m = paragraphRe.exec(text)) !== null) {
    if (m.index > last) {
      paragraphs.push({ start: last, end: m.index, text: text.slice(last, m.index) })
    }
    last = m.index + m[0].length
  }
  if (last < text.length) paragraphs.push({ start: last, end: text.length, text: text.slice(last) })

  for (const p of paragraphs) {
    if (!p.text.trim()) continue
    const tokens = estimateTokens(p.text)
    if (tokens <= MAX_CHUNK_TOKENS) {
      units.push({ text: p.text, start: p.start, end: p.end, tokens })
      continue
    }
    // Split by sentence-ish boundaries
    const sentRe = /(?<=[.!?。！？\n])\s+/g
    let sLast = 0
    let sm: RegExpExecArray | null
    const local = p.text
    const sentenceStarts: number[] = [0]
    while ((sm = sentRe.exec(local)) !== null) {
      sentenceStarts.push(sm.index + sm[0].length)
    }
    sentenceStarts.push(local.length)
    for (let i = 0; i < sentenceStarts.length - 1; i++) {
      const a = sentenceStarts[i]!
      const b = sentenceStarts[i + 1]!
      if (a >= b) continue
      const piece = local.slice(a, b)
      if (!piece.trim()) continue
      units.push({
        text: piece,
        start: p.start + a,
        end: p.start + b,
        tokens: estimateTokens(piece),
      })
      void sLast
    }
  }
  return units
}

function hardSlice(text: string, baseStart: number, maxTokens: number): TextChunk[] {
  const out: TextChunk[] = []
  let offset = 0
  while (offset < text.length) {
    let lo = offset + 1
    let hi = text.length
    let best = offset + 1
    while (lo <= hi) {
      const mid = Math.floor((lo + hi) / 2)
      const slice = text.slice(offset, mid)
      if (estimateTokens(slice) <= maxTokens) {
        best = mid
        lo = mid + 1
      } else {
        hi = mid - 1
      }
    }
    if (best <= offset) best = Math.min(offset + 1, text.length)
    const slice = text.slice(offset, best)
    if (slice.trim()) {
      out.push({
        text: slice,
        start: baseStart + offset,
        end: baseStart + best,
        tokenCount: estimateTokens(slice),
      })
    }
    if (best >= text.length) break

    // Advance so next chunk overlaps by at most MAX_OVERLAP_TOKENS
    const overlapBudget = Math.min(MAX_OVERLAP_TOKENS, maxTokens - 1)
    let keepFrom = best
    let ot = 0
    // walk backwards from best for overlapBudget tokens
    for (let pos = best; pos > offset; ) {
      const prev = pos - 1
      const ch = text[prev]!
      // approximate one step
      pos = prev
      ot = estimateTokens(text.slice(pos, best))
      if (ot >= overlapBudget) {
        keepFrom = pos
        break
      }
      keepFrom = pos
    }
    const nextOffset = keepFrom
    if (nextOffset <= offset) {
      offset = best
    } else {
      offset = nextOffset
    }
  }
  return out
}
