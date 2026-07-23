import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
  lstatSync,
} from "fs"
import { join, resolve, dirname } from "path"
import {
  MAX_SKILL_FILE_BYTES,
  SkillParseError,
  isValidSkillName,
  parseSkillMarkdown,
  skillMarkdownPath,
  systemSkillsRoot,
  userSkillsRoot,
  type SkillFrontmatter,
  type SkillInfo,
} from "@dataworks-agent/core"

export interface SkillRepoOptions {
  readonly appDataRoot: string
}

export interface SkillWriteInput {
  readonly name: string
  readonly markdown: string
}

export class SkillRepo {
  readonly appDataRoot: string

  constructor(opts: SkillRepoOptions) {
    this.appDataRoot = resolve(opts.appDataRoot)
  }

  systemRoot(): string {
    return systemSkillsRoot(this.appDataRoot)
  }

  userRoot(userId: string): string {
    assertSafeUserId(userId)
    return userSkillsRoot(this.appDataRoot, userId)
  }

  ensureRoots(userId?: string): void {
    mkdirSync(this.systemRoot(), { recursive: true })
    if (userId) mkdirSync(this.userRoot(userId), { recursive: true })
  }

  discoveryRoots(userId: string): string[] {
    this.ensureRoots(userId)
    return [this.systemRoot(), this.userRoot(userId)]
  }

  list(userId: string): SkillInfo[] {
    this.ensureRoots(userId)
    const system = loadSkillsFromRoot(this.systemRoot(), "system")
    const user = loadSkillsFromRoot(this.userRoot(userId), "user", userId)
    const byName = new Map<string, SkillInfo>()
    for (const skill of system) byName.set(skill.name, skill)
    for (const skill of user) byName.set(skill.name, skill)
    return Array.from(byName.values()).sort((a, b) => a.name.localeCompare(b.name))
  }

  listAll(userId: string): { system: SkillInfo[]; user: SkillInfo[] } {
    this.ensureRoots(userId)
    return {
      system: loadSkillsFromRoot(this.systemRoot(), "system"),
      user: loadSkillsFromRoot(this.userRoot(userId), "user", userId),
    }
  }

  get(userId: string, name: string): SkillInfo | null {
    if (!isValidSkillName(name)) return null
    const userPath = skillMarkdownPath(this.userRoot(userId), name)
    const loadedUser = loadOne(userPath, "user", userId)
    if (loadedUser) return loadedUser
    const systemPath = skillMarkdownPath(this.systemRoot(), name)
    return loadOne(systemPath, "system")
  }

  readMarkdown(userId: string, name: string): string | null {
    const info = this.get(userId, name)
    if (!info) return null
    return readFileSync(info.location, "utf8")
  }

  writeUser(userId: string, input: SkillWriteInput): SkillInfo {
    assertSafeUserId(userId)
    if (!isValidSkillName(input.name)) {
      throw new SkillParseError("schema", `invalid skill name: ${input.name}`)
    }
    validateMarkdownPayload(input.markdown)
    const { meta } = parseSkillMarkdown(input.markdown)
    if (meta.name !== input.name) {
      throw new SkillParseError("schema", `frontmatter name "${meta.name}" must match path name "${input.name}"`)
    }
    this.ensureRoots(userId)
    const dir = join(this.userRoot(userId), input.name)
    mkdirSync(dir, { recursive: true })
    const file = skillMarkdownPath(this.userRoot(userId), input.name)
    assertNotSymlink(file, dir)
    writeFileSync(file, input.markdown, "utf8")
    const loaded = loadOne(file, "user", userId)
    if (!loaded) throw new SkillParseError("schema", "failed to load written skill")
    return loaded
  }

  writeSystem(input: SkillWriteInput): SkillInfo {
    if (!isValidSkillName(input.name)) {
      throw new SkillParseError("schema", `invalid skill name: ${input.name}`)
    }
    validateMarkdownPayload(input.markdown)
    const { meta } = parseSkillMarkdown(input.markdown)
    if (meta.name !== input.name) {
      throw new SkillParseError("schema", `frontmatter name "${meta.name}" must match path name "${input.name}"`)
    }
    this.ensureRoots()
    const dir = join(this.systemRoot(), input.name)
    mkdirSync(dir, { recursive: true })
    const file = skillMarkdownPath(this.systemRoot(), input.name)
    assertNotSymlink(file, dir)
    writeFileSync(file, input.markdown, "utf8")
    const loaded = loadOne(file, "system")
    if (!loaded) throw new SkillParseError("schema", "failed to load written skill")
    return loaded
  }

  removeUser(userId: string, name: string): boolean {
    if (!isValidSkillName(name)) return false
    const dir = join(this.userRoot(userId), name)
    if (!existsSync(dir)) return false
    assertNotSymlink(dir, this.userRoot(userId))
    rmSync(dir, { recursive: true, force: true })
    return true
  }

  removeSystem(name: string): boolean {
    if (!isValidSkillName(name)) return false
    const dir = join(this.systemRoot(), name)
    if (!existsSync(dir)) return false
    assertNotSymlink(dir, this.systemRoot())
    rmSync(dir, { recursive: true, force: true })
    return true
  }
}

function loadSkillsFromRoot(root: string, scope: "system" | "user", userId?: string): SkillInfo[] {
  if (!existsSync(root)) return []
  const entries = readdirSync(root, { withFileTypes: true })
  const skills: SkillInfo[] = []
  for (const entry of entries) {
    if (!entry.isDirectory()) continue
    if (!isValidSkillName(entry.name)) continue
    const file = skillMarkdownPath(root, entry.name)
    const skill = loadOne(file, scope, userId)
    if (skill) skills.push(skill)
  }
  return skills.sort((a, b) => a.name.localeCompare(b.name))
}

function loadOne(file: string, scope: "system" | "user", userId?: string): SkillInfo | null {
  if (!existsSync(file)) return null
  try {
    assertNotSymlink(file, dirname(file))
    const raw = readFileSync(file, "utf8")
    const { meta, content } = parseSkillMarkdown(raw, { location: file })
    return {
      ...meta,
      location: file,
      content,
      scope,
      ...(userId ? { userId } : {}),
    }
  } catch {
    return null
  }
}

function validateMarkdownPayload(markdown: string): void {
  if (typeof markdown !== "string") throw new SkillParseError("schema", "markdown required")
  const bytes = Buffer.byteLength(markdown, "utf8")
  if (bytes > MAX_SKILL_FILE_BYTES) throw new SkillParseError("too_large")
  if (Buffer.from(markdown, "utf8").toString("utf8") !== markdown) {
    throw new SkillParseError("not_utf8")
  }
  parseSkillMarkdown(markdown)
}

function assertNotSymlink(target: string, allowedParent: string): void {
  const parent = resolve(allowedParent)
  if (existsSync(target)) {
    const st = lstatSync(target)
    if (st.isSymbolicLink()) throw new SkillParseError("symlink", "symlink/junction not allowed")
    try {
      const real = realpathSync(target)
      const realParent = realpathSync(parent)
      const folded = process.platform === "win32" ? real.toLowerCase() : real
      const foldedParent = process.platform === "win32" ? realParent.toLowerCase() : realParent
      const sep = process.platform === "win32" ? "\\" : "/"
      if (folded !== foldedParent && !folded.startsWith(foldedParent + sep)) {
        throw new SkillParseError("symlink", "path escapes skill root")
      }
    } catch (error) {
      if (error instanceof SkillParseError) throw error
    }
  }
  if (existsSync(parent)) {
    const pst = lstatSync(parent)
    if (pst.isSymbolicLink()) throw new SkillParseError("symlink", "symlink/junction not allowed")
  }
}

function assertSafeUserId(userId: string): void {
  if (!/^[a-zA-Z0-9_-]{1,64}$/.test(userId)) {
    throw new Error("invalid_user_id")
  }
}

export type { SkillFrontmatter, SkillInfo }
