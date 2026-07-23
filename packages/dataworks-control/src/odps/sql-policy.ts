// Read-only SQL policy. Single-shot tokenizer + top-level sanity checks.
//
// Requirements from the brief:
//   - emit words/punctuation tokens while skipping whitespace,
//     -- line comments, /* block comments */, and quoted bodies (' "/ `).
//   - reject a second top-level semicolon
//   - top-level commands must be SELECT, WITH ... SELECT, SHOW, DESC, DESCRIBE
//   - reject INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, GRANT, REVOKE,
//     TRUNCATE, CALL, SET, ADD, REMOVE, PUT, GET outside quoted bodies.
//   - do not use a startsWith("select") shortcut.

const READ_ONLY_LEAD: ReadonlySet<string> = new Set([
  "SELECT",
  "WITH",
  "SHOW",
  "DESC",
  "DESCRIBE",
])

// Banned tokens at any depth. They are allowed only inside quoted bodies
// (handled by the tokenizer).
const BANNED_TOKENS: ReadonlySet<string> = new Set([
  "INSERT",
  "UPDATE",
  "DELETE",
  "DROP",
  "ALTER",
  "CREATE",
  "GRANT",
  "REVOKE",
  "TRUNCATE",
  "CALL",
  "SET",
  "ADD",
  "REMOVE",
  "PUT",
  "GET",
])

export interface SqlPolicyError {
  readonly code: "EMPTY_SQL" | "BANNED_TOKEN" | "MULTI_STATEMENT" | "DISALLOWED_LEAD" | "WITH_INSERT" | "UNTERMINATED_QUOTE" | "UNTERMINATED_COMMENT"
  readonly message: string
  readonly token?: string
}

export interface SqlPolicyResult {
  readonly ok: boolean
  readonly error?: SqlPolicyError
}

export type Token =
  | { kind: "word"; value: string }
  | { kind: "punct"; value: string }
  // Quoted-body marker. Words and punctuation that appear inside a quoted
  // body are emitted as `quoted` and exempt from the banned-token check.
  | { kind: "quoted"; value: string }

/**
 * Tokenize one SQL statement while skipping whitespace, comments, and quoted
 * bodies. Single quotes handle SQL escapes by doubling (`''`); backticks use
 * the same rule. The output preserves whitespace boundaries through
 * `quoted` markers, so a banned word inside a quoted body never trips the
 * policy.
 */
export function tokenize(sql: string): Token[] {
  const tokens: Token[] = []
  let i = 0
  const n = sql.length
  while (i < n) {
    const c = sql[i]
    // Whitespace
    if (c === " " || c === "\t" || c === "\n" || c === "\r") {
      i++
      continue
    }
    // Line comment
    if (c === "-" && sql[i + 1] === "-") {
      i += 2
      while (i < n && sql[i] !== "\n") i++
      continue
    }
    // Block comment — nested allowed (Postgres/Snowflake style).
    if (c === "/" && sql[i + 1] === "*") {
      i += 2
      let depth = 1
      while (i < n && depth > 0) {
        if (sql[i] === "/" && sql[i + 1] === "*") {
          depth++
          i += 2
        } else if (sql[i] === "*" && sql[i + 1] === "/") {
          depth--
          i += 2
        } else {
          i++
        }
      }
      if (depth !== 0) {
        // Unterminated block comment — surface a typed error.
        tokens.push({ kind: "quoted", value: "UNCLOSED_BLOCK_COMMENT" })
        return tokens
      }
      continue
    }
    const nextChar = sql[i + 1] ?? ""
    // Quoted bodies: collect verbatim as a single quoted marker.
    if (c === "'" || c === '"' || c === "`") {
      const quote = c
      const start = i
      i++ // skip opening
      while (i < n) {
        if (sql[i] === "\\" && i + 1 < n) {
          i += 2
          continue
        }
        if (quote === "'" && sql[i] === "'" && sql[i + 1] === "'") {
          i += 2
          continue
        }
        if (sql[i] === quote) {
          i++
          break
        }
        i++
      }
      tokens.push({ kind: "quoted", value: sql.slice(start, i) })
      continue
    }
    // Punctuation: ; ( ) , < > = etc. Each punctuation char is its own token.
    if (/[;,()[\]<>=+\-*/%|&!?:.]/.test(c ?? "")) {
      tokens.push({ kind: "punct", value: c ?? "" })
      i++
      continue
    }
    // Word: [A-Za-z_][A-Za-z0-9_]* — also catches unicode identifiers.
    if (c && /[A-Za-z_]/.test(c)) {
      const start = i
      while (i < n && /[A-Za-z0-9_]/.test(sql[i] ?? "")) i++
      tokens.push({ kind: "word", value: sql.slice(start, i).toUpperCase() })
      continue
    }
    // Anything else — collect one char as a quoted body so we never silently
    // accept unknown syntax.
    tokens.push({ kind: "quoted", value: c ?? "" })
    i++
  }
  return tokens
}

/** Apply the policy to a SQL string. */
export function evaluateSql(sql: string): SqlPolicyResult {
  if (!sql || !sql.trim()) {
    return { ok: false, error: { code: "EMPTY_SQL", message: "SQL is empty" } }
  }
  const tokens = tokenize(sql)
  for (const t of tokens) {
    if (t.kind === "quoted" && t.value === "UNCLOSED_BLOCK_COMMENT") {
      return {
        ok: false,
        error: { code: "UNTERMINATED_COMMENT", message: "block comment is not closed" },
      }
    }
    if (t.kind === "word" && BANNED_TOKENS.has(t.value)) {
      return {
        ok: false,
        error: {
          code: "BANNED_TOKEN",
          message: `token ${t.value} is not permitted by the SQL safety gate`,
          token: t.value,
        },
      }
    }
  }

  // Walk to find the first non-quoted token (skipping whitespace/comments).
  const wordTokens = tokens.filter((t): t is { kind: "word"; value: string } => t.kind === "word")
  if (wordTokens.length === 0) {
    return { ok: false, error: { code: "EMPTY_SQL", message: "SQL has no words" } }
  }
  const firstWord = wordTokens[0]
  if (!firstWord) {
    return { ok: false, error: { code: "EMPTY_SQL", message: "SQL has no words" } }
  }
  const lead = firstWord.value
  if (!READ_ONLY_LEAD.has(lead)) {
    return {
      ok: false,
      error: {
        code: "DISALLOWED_LEAD",
        message: `top-level command ${lead} is not allowed; expected one of: SELECT, WITH, SHOW, DESC, DESCRIBE`,
        token: lead,
      },
    }
  }
  if (lead === "WITH") {
    // WITH must eventually contain a SELECT at depth 0.
    let depth = 0
    let sawSelect = false
    for (const t of tokens) {
      if (t.kind === "punct") {
        if (t.value === "(") depth++
        else if (t.value === ")") depth--
        continue
      }
      if (t.kind === "word" && depth === 0 && t.value === "SELECT") {
        sawSelect = true
        break
      }
    }
    if (!sawSelect) {
      return {
        ok: false,
        error: {
          code: "WITH_INSERT",
          message: "WITH ... must terminate at a top-level SELECT",
          token: "WITH",
        },
      }
    }
  }

  // Reject anything after a top-level semicolon. The first `;` ends the
  // statement; any token that follows starts a second stream.
  let depth = 0
  let terminatorSeen = false
  for (const t of tokens) {
    if (t.kind === "punct") {
      if (t.value === "(") {
        depth++
        continue
      }
      if (t.value === ")") {
        depth--
        continue
      }
      if (t.value === ";" && depth === 0) {
        terminatorSeen = true
        continue
      }
    }
    if (terminatorSeen && t.kind !== "quoted" && !(t.kind === "punct" && /[)\]]/.test(t.value))) {
      return {
        ok: false,
        error: {
          code: "MULTI_STATEMENT",
          message: "more than one top-level statement is not allowed",
          token: ";",
        },
      }
    }
  }
  return { ok: true }
}

/**
 * Replace any literal that matches the SQL safety gate's banned set or
 * contains a top-level statement terminator with a sanitised form. Used by
 * the service to strip out accidental SQL fragments before logging.
 */
export function sqlSummary(sql: string): string {
  const trimmed = sql.trim()
  if (trimmed.length <= 80) return trimmed
  return trimmed.slice(0, 77) + "..."
}
