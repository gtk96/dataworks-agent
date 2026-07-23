/** DataWorks Skill frontmatter + permission policy (one source: SKILL.md). */

import path from "path"

export const WRITE_TOOLS = [
  "dw_rerun_job",
  "dw_trigger_supplement",
  "dw_pause_schedule",
  "dw_alert_silence",
] as const

export type WriteToolName = (typeof WRITE_TOOLS)[number]

export const MAX_SKILL_FILE_BYTES = 1 * 1024 * 1024

export type PermissionEffect = "allow" | "deny" | "ask"

export interface SkillFrontmatter {
  readonly name: string
  readonly description?: string
  readonly triggers: readonly string[]
  readonly allowed_tools: readonly string[]
  readonly forbidden_tools: readonly string[]
  readonly max_tool_calls_per_session: number
  readonly write_enabled: boolean
}

export interface SkillInfo extends SkillFrontmatter {
  readonly location: string
  readonly content: string
  readonly scope: "system" | "user"
  readonly userId?: string
}

export type SkillParseErrorCode =
  | "missing_frontmatter"
  | "invalid_yaml"
  | "schema"
  | "empty_name"
  | "not_utf8"
  | "too_large"
  | "symlink"

export class SkillParseError extends Error {
  readonly code: SkillParseErrorCode
  constructor(code: SkillParseErrorCode, message?: string) {
    super(message ?? code)
    this.name = "SkillParseError"
    this.code = code
  }
}

export interface SkillToolLimitResult {
  readonly _tag: "SkillToolLimitExceeded"
  readonly skill: string
  readonly tool: string
  readonly limit: number
  readonly used: number
  readonly message: string
}

export interface SkillToolDeniedResult {
  readonly _tag: "SkillToolDenied"
  readonly skill: string
  readonly tool: string
  readonly reason: "forbidden" | "not_allowed" | "write_disabled"
  readonly message: string
}

const NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/

export function isValidSkillName(name: string): boolean {
  return NAME_RE.test(name)
}

export function isWriteTool(tool: string): tool is WriteToolName {
  return (WRITE_TOOLS as readonly string[]).includes(tool)
}

/**
 * Parse OpenCode-compatible SKILL.md: YAML frontmatter between --- fences + body.
 * Uses Bun.YAML (no skill.toml).
 */
export function parseSkillMarkdown(
  raw: string,
  options: { location?: string; maxBytes?: number } = {},
): { meta: SkillFrontmatter; content: string } {
  const maxBytes = options.maxBytes ?? MAX_SKILL_FILE_BYTES
  const bytes = Buffer.byteLength(raw, "utf8")
  if (bytes > maxBytes) throw new SkillParseError("too_large", `skill exceeds ${maxBytes} bytes`)

  try {
    const reencoded = Buffer.from(raw, "utf8").toString("utf8")
    if (reencoded !== raw) throw new SkillParseError("not_utf8")
  } catch (error) {
    if (error instanceof SkillParseError) throw error
  }

  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)([\s\S]*)$/)
  if (!match) throw new SkillParseError("missing_frontmatter", "SKILL.md must start with YAML frontmatter")

  let data: unknown
  try {
    data = Bun.YAML.parse(match[1]!)
  } catch {
    throw new SkillParseError("invalid_yaml", "invalid skill frontmatter YAML")
  }

  const meta = decodeFrontmatter(data)
  const content = (match[2] ?? "").replace(/^\r?\n/, "")
  return { meta, content }
}

export function decodeFrontmatter(data: unknown): SkillFrontmatter {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new SkillParseError("schema", "frontmatter must be a mapping")
  }
  const obj = data as Record<string, unknown>
  const name = typeof obj.name === "string" ? obj.name.trim() : ""
  if (!name) throw new SkillParseError("empty_name", "name is required")
  if (!isValidSkillName(name)) throw new SkillParseError("schema", `invalid skill name: ${name}`)

  const description = typeof obj.description === "string" ? obj.description : undefined
  const triggers = stringArray(obj.triggers, "triggers")
  const allowed_tools = stringArray(obj.allowed_tools, "allowed_tools")
  const forbidden_tools = stringArray(obj.forbidden_tools, "forbidden_tools")

  let max_tool_calls_per_session = 50
  if (obj.max_tool_calls_per_session !== undefined) {
    if (
      typeof obj.max_tool_calls_per_session !== "number" ||
      !Number.isInteger(obj.max_tool_calls_per_session) ||
      obj.max_tool_calls_per_session < 0
    ) {
      throw new SkillParseError("schema", "max_tool_calls_per_session must be a non-negative integer")
    }
    max_tool_calls_per_session = obj.max_tool_calls_per_session
  }

  let write_enabled = false
  if (obj.write_enabled !== undefined) {
    if (typeof obj.write_enabled !== "boolean") {
      throw new SkillParseError("schema", "write_enabled must be a boolean")
    }
    write_enabled = obj.write_enabled
  }

  return {
    name,
    ...(description !== undefined ? { description } : {}),
    triggers,
    allowed_tools,
    forbidden_tools,
    max_tool_calls_per_session,
    write_enabled,
  }
}

/**
 * Map Skill policy to OpenCode PermissionV1-style effect for a DataWorks tool.
 * - forbidden_tools → mandatory deny
 * - allowed_tools (when non-empty) narrows visibility of dw_* tools
 * - write tools stay deny unless both connection and Skill enable write, then ask
 */
export function permissionForTool(
  skill: SkillFrontmatter,
  tool: string,
  connectionWriteEnabled: boolean,
): PermissionEffect {
  if (skill.forbidden_tools.includes(tool)) return "deny"

  if (isWriteTool(tool)) {
    if (!skill.write_enabled || !connectionWriteEnabled) return "deny"
    return "ask"
  }

  if (skill.allowed_tools.length > 0 && tool.startsWith("dw_")) {
    if (!skill.allowed_tools.includes(tool)) return "deny"
  }

  return "allow"
}

export function checkToolAgainstSkill(input: {
  skill: SkillFrontmatter
  tool: string
  connectionWriteEnabled: boolean
  usedCalls: number
}): SkillToolLimitResult | SkillToolDeniedResult | { _tag: "ok" } {
  const effect = permissionForTool(input.skill, input.tool, input.connectionWriteEnabled)
  if (effect === "deny") {
    const reason = input.skill.forbidden_tools.includes(input.tool)
      ? "forbidden"
      : isWriteTool(input.tool)
        ? "write_disabled"
        : "not_allowed"
    return {
      _tag: "SkillToolDenied",
      skill: input.skill.name,
      tool: input.tool,
      reason,
      message: `skill "${input.skill.name}" denies tool "${input.tool}" (${reason})`,
    }
  }

  const limit = input.skill.max_tool_calls_per_session
  if (limit >= 0 && input.usedCalls >= limit) {
    return {
      _tag: "SkillToolLimitExceeded",
      skill: input.skill.name,
      tool: input.tool,
      limit,
      used: input.usedCalls,
      message: `skill "${input.skill.name}" exceeded max_tool_calls_per_session (${limit})`,
    }
  }

  return { _tag: "ok" }
}

export function systemSkillsRoot(appDataRoot: string): string {
  return path.join(appDataRoot, "skills", "system")
}

export function userSkillsRoot(appDataRoot: string, userId: string): string {
  return path.join(appDataRoot, "users", userId, "skills")
}

export function skillDirectory(root: string, name: string): string {
  return path.join(root, name)
}

export function skillMarkdownPath(root: string, name: string): string {
  return path.join(root, name, "SKILL.md")
}

function stringArray(value: unknown, field: string): string[] {
  if (value === undefined || value === null) return []
  if (!Array.isArray(value)) throw new SkillParseError("schema", `${field} must be an array`)
  const out: string[] = []
  for (const item of value) {
    if (typeof item !== "string" || !item.trim()) {
      throw new SkillParseError("schema", `${field} items must be non-empty strings`)
    }
    out.push(item.trim())
  }
  return out
}
