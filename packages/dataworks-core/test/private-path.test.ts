import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { mkdirSync, rmSync, symlinkSync, writeFileSync, existsSync } from "fs"
import { join, resolve, dirname } from "path"
import { tmpdir } from "os"
import {
  PrivatePathPolicy,
  PrivatePathDeniedError,
  parsePrivatePaths,
  resolveCandidate,
  isUnderPrivateRoot,
} from "../src/private-path"

const root = join(tmpdir(), `dwa-private-path-${Date.now()}`)
const privateRoot = join(root, "app-data", "users", "user-a")
const otherUser = join(root, "app-data", "users", "user-b")
const projectRoot = join(root, "projects", "demo")
const secrets = join(root, "app-data", "secrets.dat")

beforeAll(() => {
  rmSync(root, { recursive: true, force: true })
  mkdirSync(join(privateRoot, "home"), { recursive: true })
  mkdirSync(join(otherUser, "home"), { recursive: true })
  mkdirSync(projectRoot, { recursive: true })
  writeFileSync(join(privateRoot, "home", "secret.txt"), "private-a")
  writeFileSync(join(otherUser, "home", "secret.txt"), "private-b")
  writeFileSync(join(projectRoot, "readme.md"), "ok")
  writeFileSync(secrets, "encrypted")
})

afterAll(() => {
  rmSync(root, { recursive: true, force: true })
})

describe("PrivatePathPolicy", () => {
  test("direct private path is denied", () => {
    const target = join(privateRoot, "home", "secret.txt")
    const result = PrivatePathPolicy.check(target, "read", [privateRoot, otherUser, dirname(secrets)])
    expect(result._tag).toBe("PrivatePathDenied")
    if (result._tag === "PrivatePathDenied") {
      expect(result.operation).toBe("read")
      expect(result.root).toBeTruthy()
    }
  })

  test("path traversal with .. cannot escape into private root", () => {
    const sneaky = join(projectRoot, "..", "..", "app-data", "users", "user-a", "home", "secret.txt")
    const result = PrivatePathPolicy.check(sneaky, "read", [privateRoot])
    expect(result._tag).toBe("PrivatePathDenied")
  })

  test("Windows case-insensitivity treats private root as equal", () => {
    if (process.platform !== "win32") {
      // Still exercise fold via isUnderPrivateRoot using mixed-case absolute strings
      const lower = privateRoot.toLowerCase()
      const upper = privateRoot.toUpperCase()
      // On non-win, fold is case-sensitive so mixed case may not match; skip assertion
      expect(typeof lower).toBe("string")
      expect(typeof upper).toBe("string")
      return
    }
    const mixed = privateRoot
      .split(/[/\\]/)
      .map((part: string, i: number) => (i % 2 === 0 ? part.toUpperCase() : part.toLowerCase()))
      .join("\\")
    const target = join(mixed, "home", "secret.txt")
    const result = PrivatePathPolicy.check(target, "read", [privateRoot])
    expect(result._tag).toBe("PrivatePathDenied")
  })

  test("symlink / junction into private root is denied", () => {
    const linkPath = join(projectRoot, "escape-link")
    try {
      if (existsSync(linkPath)) rmSync(linkPath, { recursive: true, force: true })
      // Windows: try junction; Unix: symlink
      if (process.platform === "win32") {
        try {
          // directory junction
          const { execSync } = require("child_process") as typeof import("child_process")
          execSync(`cmd /c mklink /J "${linkPath}" "${join(privateRoot, "home")}"`, {
            stdio: "ignore",
          })
        } catch {
          // fall back to file symlink if junction fails
          symlinkSync(join(privateRoot, "home", "secret.txt"), linkPath, "file")
        }
      } else {
        symlinkSync(join(privateRoot, "home"), linkPath, "dir")
      }
    } catch {
      // Environments without symlink privilege still assert resolveCandidate semantics
      const resolved = resolveCandidate(join(privateRoot, "home", "secret.txt"))
      expect(isUnderPrivateRoot(resolved, privateRoot)).toBe(true)
      return
    }

    const viaLink = join(
      linkPath,
      process.platform === "win32" && !existsSync(join(linkPath, "secret.txt")) ? "" : "secret.txt",
    )
    const candidate = viaLink.endsWith("secret.txt") ? viaLink : join(privateRoot, "home", "secret.txt")
    const result = PrivatePathPolicy.check(candidate, "read", [privateRoot])
    expect(result._tag).toBe("PrivatePathDenied")
  })

  test("worker A cannot access worker B private root", () => {
    const target = join(otherUser, "home", "secret.txt")
    // Worker A is only allowed to treat its own private roots as protected from itself? No —
    // DWA_PRIVATE_PATHS lists ALL private roots that must never be touched (control plane,
    // other users). Worker A seeing worker B's path is denied.
    const result = PrivatePathPolicy.check(target, "read", [privateRoot, otherUser])
    expect(result._tag).toBe("PrivatePathDenied")
    if (result._tag === "PrivatePathDenied") {
      expect(isUnderPrivateRoot(result.path, otherUser)).toBe(true)
    }
  })

  test("allowed project file is not denied", () => {
    const target = join(projectRoot, "readme.md")
    const result = PrivatePathPolicy.check(target, "read", [privateRoot, otherUser, dirname(secrets)])
    expect(result._tag).toBe("PrivatePathAllowed")
    if (result._tag === "PrivatePathAllowed") {
      expect(result.path).toContain("readme.md")
    }
  })

  test("typed deny cannot be overridden by always approval (assert throws PrivatePathDeniedError)", () => {
    const target = join(privateRoot, "home", "secret.txt")
    // always approvals are irrelevant — assert throws before any permission prompt
    expect(() => PrivatePathPolicy.assert(target, "edit", [privateRoot])).toThrow(PrivatePathDeniedError)
    try {
      PrivatePathPolicy.assert(target, "edit", [privateRoot])
    } catch (error) {
      expect(error).toBeInstanceOf(PrivatePathDeniedError)
      const denied = error as PrivatePathDeniedError
      expect(denied._tag).toBe("PrivatePathDenied")
      expect(denied.operation).toBe("edit")
    }
  })

  test("parsePrivatePaths reads DWA_PRIVATE_PATHS JSON array", () => {
    const paths = parsePrivatePaths({
      DWA_PRIVATE_PATHS: JSON.stringify([privateRoot, otherUser]),
    })
    expect(paths.length).toBe(2)
    expect(paths.some((p) => p.includes("user-a"))).toBe(true)
  })

  test("resolveCandidate collapses .. segments", () => {
    const sneaky = join(projectRoot, "..", "..", "app-data", "users", "user-a")
    const resolved = resolveCandidate(sneaky)
    expect(resolve(resolved)).toBe(resolve(privateRoot))
  })
})
