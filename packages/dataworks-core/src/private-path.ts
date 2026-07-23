import { existsSync, realpathSync, lstatSync } from "fs"
import path from "path"

export type PrivatePathOperation = "read" | "write" | "edit" | "shell" | "external_directory" | "apply_patch" | string

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

/** Parse control-plane-injected `DWA_PRIVATE_PATHS` (JSON array of absolute roots). */
export function parsePrivatePaths(env: Record<string, string | undefined> = process.env as Record<string, string | undefined>): string[] {
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

/**
 * Resolve a candidate path the way the tool boundary must:
 * path.resolve → nearest existing parent via fs.realpath → reattach missing suffix.
 * Windows paths are case-folded for comparisons only after resolution.
 */
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

/**
 * Mandatory private-path policy.
 * `userRoot` may be a single absolute root or an array of absolute roots
 * (control-plane injects JSON array via DWA_PRIVATE_PATHS).
 */
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

  assert(
    realPath: string,
    operation: PrivatePathOperation,
    userRoot: string | readonly string[],
  ): string {
    const result = PrivatePathPolicy.check(realPath, operation, userRoot)
    if (result._tag === "PrivatePathDenied") {
      throw new PrivatePathDeniedError(result)
    }
    return result.path
  },
}

function nearestRealParent(absolute: string): { real: string; suffix: string } {
  let current = absolute
  const missing: string[] = []

  while (true) {
    try {
      if (existsSync(current)) {
        // Prefer realpath so symlink/junction targets are evaluated.
        const real = realpathSync(current)
        // If the path itself is a symlink and the candidate is exactly that path,
        // realpath already points at the target — still treat as the resolved location.
        void lstatSync
        const suffix = missing.length ? missing.reverse().join(path.sep) : ""
        return { real, suffix }
      }
    } catch {
      // continue walking up
    }
    const parent = path.dirname(current)
    if (parent === current) {
      // filesystem root; best effort
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
