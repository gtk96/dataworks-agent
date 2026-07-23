import { readdirSync, readFileSync, existsSync, lstatSync } from "fs"
import { join } from "path"
import {
  checkToolAgainstSkill,
  parseSkillMarkdown,
  skillMarkdownPath,
  systemSkillsRoot,
  userSkillsRoot,
  type SkillFrontmatter,
  type SkillInfo,
  type SkillToolDeniedResult,
  type SkillToolLimitResult,
} from "@dataworks-agent/core"

export type SkillGateResult =
  | { _tag: "ok" }
  | SkillToolLimitResult
  | SkillToolDeniedResult
  | { _tag: "no_active_skill" }

export interface SkillContextOptions {
  readonly appDataRoot?: string
  readonly userId?: string
  readonly roots?: readonly string[]
  readonly env?: Record<string, string | undefined>
}

/**
 * Per-worker skill discovery + session tool-call accounting.
 * Roots default to system + users/<id>/skills from env.
 */
export class SkillContext {
  private cache: SkillInfo[] | null = null
  private readonly roots: string[]
  private readonly sessionCalls = new Map<string, number>()
  private activeSkillBySession = new Map<string, string>()

  constructor(private readonly options: SkillContextOptions = {}) {
    this.roots = resolveRoots(options)
  }

  list(): SkillInfo[] {
    if (this.cache) return this.cache
    const byName = new Map<string, SkillInfo>()
    for (const root of this.roots) {
      for (const skill of scanRoot(root)) {
        byName.set(skill.name, skill)
      }
    }
    this.cache = Array.from(byName.values()).sort((a, b) => a.name.localeCompare(b.name))
    return this.cache
  }

  get(name: string): SkillInfo | undefined {
    return this.list().find((s) => s.name === name)
  }

  /** Force re-read of SKILL.md roots (hot reload after edit). */
  reload(): void {
    this.cache = null
  }

  setActiveSkill(sessionID: string, skillName: string): void {
    this.activeSkillBySession.set(sessionID, skillName)
  }

  clearActiveSkill(sessionID: string): void {
    this.activeSkillBySession.delete(sessionID)
  }

  activeSkill(sessionID: string): SkillInfo | undefined {
    const name = this.activeSkillBySession.get(sessionID)
    if (!name) return undefined
    return this.get(name)
  }

  usedCalls(sessionID: string): number {
    return this.sessionCalls.get(sessionID) ?? 0
  }

  /**
   * Enforce Skill policy before a DataWorks tool runs.
   * Returns typed limit/deny results for the model.
   */
  gateTool(input: {
    sessionID: string
    tool: string
    connectionWriteEnabled?: boolean
    skillName?: string
  }): SkillGateResult {
    if (!input.tool.startsWith("dw_")) return { _tag: "ok" }

    const skillName = input.skillName ?? this.activeSkillBySession.get(input.sessionID)
    if (!skillName) return { _tag: "ok" }

    const skill = this.get(skillName)
    if (!skill) return { _tag: "ok" }

    const used = this.sessionCalls.get(input.sessionID) ?? 0
    const result = checkToolAgainstSkill({
      skill,
      tool: input.tool,
      connectionWriteEnabled: input.connectionWriteEnabled ?? false,
      usedCalls: used,
    })
    if (result._tag !== "ok") return result
    this.sessionCalls.set(input.sessionID, used + 1)
    return { _tag: "ok" }
  }

  /** Simulate OpenCode skill tool load: return content + meta for a named skill. */
  loadSkillTool(name: string): { title: string; output: string; metadata: Record<string, unknown> } | null {
    this.reload()
    const skill = this.get(name)
    if (!skill) return null
    return {
      title: `Loaded skill: ${skill.name}`,
      output: skill.content,
      metadata: {
        name: skill.name,
        location: skill.location,
        description: skill.description,
        allowed_tools: skill.allowed_tools,
        forbidden_tools: skill.forbidden_tools,
        write_enabled: skill.write_enabled,
        max_tool_calls_per_session: skill.max_tool_calls_per_session,
        scope: skill.scope,
      },
    }
  }
}

/** Parse DWA_SKILL_ROOTS JSON array or build from app data + user. */
export function resolveRoots(options: SkillContextOptions): string[] {
  if (options.roots && options.roots.length > 0) return [...options.roots]
  const env = options.env ?? (process.env as Record<string, string | undefined>)
  const raw = env.DWA_SKILL_ROOTS
  if (raw && raw.trim()) {
    try {
      const parsed = JSON.parse(raw) as unknown
      if (Array.isArray(parsed)) {
        return parsed.filter((p): p is string => typeof p === "string" && p.length > 0)
      }
    } catch {
      // fall through
    }
  }
  const appData = options.appDataRoot ?? env.DWA_APP_DATA_ROOT
  const userId = options.userId ?? env.DWA_USER_ID
  if (appData && userId) {
    return [systemSkillsRoot(appData), userSkillsRoot(appData, userId)]
  }
  if (appData) return [systemSkillsRoot(appData)]
  return []
}

function scanRoot(root: string): SkillInfo[] {
  if (!existsSync(root)) return []
  const out: SkillInfo[] = []
  let entries: string[]
  try {
    entries = readdirSync(root)
  } catch {
    return []
  }
  for (const name of entries) {
    const dir = join(root, name)
    try {
      if (lstatSync(dir).isSymbolicLink()) continue
      if (!lstatSync(dir).isDirectory()) continue
    } catch {
      continue
    }
    const file = skillMarkdownPath(root, name)
    if (!existsSync(file)) continue
    try {
      if (lstatSync(file).isSymbolicLink()) continue
      const raw = readFileSync(file, "utf8")
      const { meta, content } = parseSkillMarkdown(raw)
      const normalized = root.replace(/\\/g, "/")
      const isSystem = normalized.includes("/skills/system")
      out.push({
        ...meta,
        location: file,
        content,
        scope: isSystem ? "system" : "user",
      })
    } catch {
      // skip invalid
    }
  }
  return out
}

let shared: SkillContext | null = null

export function getSkillContext(options?: SkillContextOptions): SkillContext {
  if (options) {
    shared = new SkillContext(options)
    return shared
  }
  if (!shared) shared = new SkillContext()
  return shared
}

export function resetSkillContext(): void {
  shared = null
}

export function formatSkillGateOutput(result: SkillToolLimitResult | SkillToolDeniedResult): string {
  return JSON.stringify(result)
}

export type { SkillFrontmatter, SkillInfo }
