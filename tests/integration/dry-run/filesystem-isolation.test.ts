import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { mkdirSync, rmSync, writeFileSync, existsSync, readFileSync } from "fs"
import { join, dirname } from "path"
import { tmpdir } from "os"
import {
  PrivatePathPolicy,
  PrivatePathDeniedError,
  parsePrivatePaths,
  resolveCandidate,
} from "../../../packages/dataworks-core/src/private-path"
import {
  assertNotPrivatePath,
  PrivatePathDeny,
  parsePrivatePaths as opencodeParse,
} from "../../../packages/opencode/src/tool/private-path"

const base = join(tmpdir(), `dwa-fs-isolation-${Date.now()}`)
const appData = join(base, "app-data")
const userA = join(appData, "users", "user-a")
const userB = join(appData, "users", "user-b")
const secretsRoot = join(appData, "secrets")
const projectRoot = join(base, "projects", "demo")

beforeAll(() => {
  rmSync(base, { recursive: true, force: true })
  mkdirSync(join(userA, "home"), { recursive: true })
  mkdirSync(join(userB, "home"), { recursive: true })
  mkdirSync(secretsRoot, { recursive: true })
  mkdirSync(projectRoot, { recursive: true })
  writeFileSync(join(userA, "home", "private.txt"), "a-private")
  writeFileSync(join(userB, "home", "private.txt"), "b-private")
  writeFileSync(join(secretsRoot, "secrets.dat"), "cipher")
  writeFileSync(join(projectRoot, "main.ts"), "export const ok = 1\n")

  process.env.DWA_PRIVATE_PATHS = JSON.stringify([userA, userB, secretsRoot, dirname(secretsRoot)])
})

afterAll(() => {
  delete process.env.DWA_PRIVATE_PATHS
  rmSync(base, { recursive: true, force: true })
})

describe("filesystem isolation dry-run", () => {
  test("private path access is denied by core policy", () => {
    const roots = parsePrivatePaths(process.env)
    expect(roots.length).toBeGreaterThan(0)

    const target = join(userA, "home", "private.txt")
    const result = PrivatePathPolicy.check(target, "read", roots)
    expect(result._tag).toBe("PrivatePathDenied")
    expect(() => PrivatePathPolicy.assert(target, "read", roots)).toThrow(PrivatePathDeniedError)
  })

  test("opencode tool guard denies private path before permission prompt", () => {
    const target = join(userB, "home", "private.txt")
    expect(() => assertNotPrivatePath(target, "read")).toThrow(PrivatePathDeny)
    try {
      assertNotPrivatePath(target, "edit")
    } catch (error) {
      expect(error).toBeInstanceOf(PrivatePathDeny)
      expect((error as PrivatePathDeny)._tag).toBe("PrivatePathDenied")
    }
  })

  test("path traversal into secrets is denied", () => {
    const sneaky = join(projectRoot, "..", "..", "app-data", "secrets", "secrets.dat")
    const resolved = resolveCandidate(sneaky)
    expect(existsSync(resolved)).toBe(true)
    const roots = parsePrivatePaths(process.env)
    expect(PrivatePathPolicy.check(sneaky, "read", roots)._tag).toBe("PrivatePathDenied")
    expect(() => assertNotPrivatePath(sneaky, "read")).toThrow()
  })

  test("worker A private root cannot be read as a normal project file", () => {
    const target = join(userA, "home", "private.txt")
    // always-approval simulation: even if roots are present, policy still denies
    const roots = opencodeParse(process.env)
    const result = PrivatePathPolicy.check(target, "write", roots)
    expect(result._tag).toBe("PrivatePathDenied")
  })

  test("normal project file operations still work", () => {
    const target = join(projectRoot, "main.ts")
    const roots = parsePrivatePaths(process.env)
    const result = PrivatePathPolicy.check(target, "read", roots)
    expect(result._tag).toBe("PrivatePathAllowed")

    // No throw from tool guard
    assertNotPrivatePath(target, "read")
    assertNotPrivatePath(target, "edit")
    assertNotPrivatePath(target, "write")

    // Actual filesystem read still succeeds (policy only gates, does not alter FS).
    expect(readFileSync(target, "utf8")).toContain("export const ok")
  })

  test("empty DWA_PRIVATE_PATHS does not block project files", () => {
    const prev = process.env.DWA_PRIVATE_PATHS
    process.env.DWA_PRIVATE_PATHS = ""
    try {
      assertNotPrivatePath(join(projectRoot, "main.ts"), "read")
    } finally {
      process.env.DWA_PRIVATE_PATHS = prev
    }
  })
})
