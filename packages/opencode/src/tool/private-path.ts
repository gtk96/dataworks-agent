/**
 * OpenCode tool-boundary private-path guard (DataWorks core patch).
 *
 * Control plane injects `DWA_PRIVATE_PATHS` (JSON array of absolute roots) into
 * the worker environment. This module is the single mandatory guard called from
 * external-directory, read, edit, write, apply_patch, and shell path discovery.
 *
 * Policy is intentionally independent of PermissionV1 `always` approvals —
 * a typed deny is returned BEFORE any permission prompt.
 *
 * Implementation mirrors packages/dataworks-core/src/private-path.ts so opencode
 * does not take a hard workspace dependency on @dataworks-agent/core.
 */
import { existsSync, realpathSync } from "fs"
import path from "path"
import { Effect } from "effect"

export type PrivatePathOperation =
  | "read"
  | "write"
  | "edit"
  | "shell"
  | "external_directory"
  | "apply_patch"
  | string

export interface PrivatePathDenied {
  readonly _tag: "PrivatePathDenied"
  readonly path: string
  readonly root: string
  readonly operation: PrivatePathOperation
  readonly message: string
}

export interface PrivatePathAllowed {
  readonly _tag: "PrivatePathAllowed"
  readonly path: string
}

export type PrivatePathResult = PrivatePathDenied | PrivatePathAllowed

export class PrivatePathDeniedError extends Error {
  readonly _tag = "PrivatePathDenied" as const
  readonly path: string
  readonly root: string
  readonly operation: PrivatePathOperation

  constructor(input: { path: string; root: string; operation: PrivatePathOperation; message?: string }) {
    super(input.message ?? `private path denied: ${input.path}`)
    this.name = "PrivatePathDeniedError"
    this.path = input.path
    this.root = input.root
    this.operation = input.operation
  }
}

export class PrivatePathDeny extends Error {
  readonly _tag = "PrivatePathDenied" as const
  readonly path: string
  readonly root: string
  readonly operation: PrivatePathOperation

  constructor(error: PrivatePathDeniedError) {
    super(error.message)
    this.name = "PrivatePathDeny"
    this.path = error.path
    this.root = error.root
    this.operation = error.operation
  }
}

/** Parse control-plane-injected `DWA_PRIVATE_PATHS` (JSON array of absolute roots). */
export function parsePrivatePaths(env: NodeJS.ProcessEnv = process.env): string[] {
  const raw = env.DWA_PRIVATE_PATHS
  if (!raw || !raw.trim()) return []
  try {
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
      .map((item) => normalizeRoot(item))
  } catch {
    return []
  }
}

export function resolveCandidate(candidate: string, cwd = process.cwd()): string {
  const absolute = path.resolve(cwd, candidate)
  const { real, suffix } = nearestRealParent(absolute)
  const joined = suffix ? path.join(real, suffix) : real
  return process.platform === "win32" ? path.normalize(joined) : joined
}

export function isUnderPrivateRoot(resolved: string, root: string): boolean {
  const target = fold(resolved)
  const base = fold(root)
  if (target === base) return true
  const prefix = base.endsWith(path.sep) ? base : base + path.sep
  return target.startsWith(prefix)
}

export const PrivatePathPolicy = {
  check(
    realPath: string,
    operation: PrivatePathOperation,
    userRoot: string | readonly string[],
  ): PrivatePathResult {
    const roots = (Array.isArray(userRoot) ? userRoot : [userRoot])
      .filter((item) => typeof item === "string" && item.trim().length > 0)
      .map((item) => normalizeRoot(item))

    if (roots.length === 0) {
      return { _tag: "PrivatePathAllowed", path: realPath }
    }

    const resolved = resolveCandidate(realPath)
    for (const root of roots) {
      if (isUnderPrivateRoot(resolved, root)) {
        return {
          _tag: "PrivatePathDenied",
          path: resolved,
          root,
          operation,
          message: `Access to private path is denied (${operation}): ${resolved}`,
        }
      }
    }
    return { _tag: "PrivatePathAllowed", path: resolved }
  },

  assert(realPath: string, operation: PrivatePathOperation, userRoot: string | readonly string[]): string {
    const result = PrivatePathPolicy.check(realPath, operation, userRoot)
    if (result._tag === "PrivatePathDenied") {
      throw new PrivatePathDeniedError(result)
    }
    return result.path
  },
}

/** Resolve private roots from the current process environment. */
export function privateRoots(env: NodeJS.ProcessEnv = process.env): string[] {
  return parsePrivatePaths(env)
}

/**
 * Synchronous check used by tools. Throws PrivatePathDeny on denial.
 */
export function assertNotPrivatePath(
  candidate: string,
  operation: PrivatePathOperation,
  env?: NodeJS.ProcessEnv,
): void {
  const roots = privateRoots(env)
  if (roots.length === 0) return
  try {
    PrivatePathPolicy.assert(candidate, operation, roots)
  } catch (error) {
    if (error instanceof PrivatePathDeniedError) throw new PrivatePathDeny(error)
    throw error
  }
}

/** Effect-friendly wrapper — throws as a defect (never in error channel). */
export const assertNotPrivatePathEffect = Effect.fn("Tool.assertNotPrivatePath")(function* (
  candidate: string | undefined,
  operation: PrivatePathOperation,
) {
  if (!candidate) return
  // Synchronous throw keeps the Effect error channel as never so tool execute
  // signatures stay compatible with DefWithoutID.
  yield* Effect.sync(() => {
    assertNotPrivatePath(candidate, operation)
  })
})

function nearestRealParent(absolute: string): { real: string; suffix: string } {
  let current = absolute
  const missing: string[] = []

  while (true) {
    try {
      if (existsSync(current)) {
        const real = realpathSync(current)
        const suffix = missing.length ? missing.reverse().join(path.sep) : ""
        return { real, suffix }
      }
    } catch {
      // continue walking up
    }
    const parent = path.dirname(current)
    if (parent === current) {
      return { real: absolute, suffix: "" }
    }
    missing.push(path.basename(current))
    current = parent
  }
}

function normalizeRoot(root: string): string {
  const absolute = path.resolve(root)
  try {
    if (existsSync(absolute)) return realpathSync(absolute)
  } catch {
    // fall through
  }
  return absolute
}

function fold(value: string): string {
  const normalized = path.normalize(value)
  return process.platform === "win32" ? normalized.toLowerCase() : normalized
}
