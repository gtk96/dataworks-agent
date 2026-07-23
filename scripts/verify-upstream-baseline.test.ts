import { afterAll, describe, expect, test } from "bun:test"
import { mkdirSync, mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import baseline from "../upstream-baseline.json"

const root = resolve(import.meta.dir, "..")
const verifier = resolve(import.meta.dir, "verify-upstream-baseline.ts")
const temporary = mkdtempSync(join(tmpdir(), "verify-upstream-baseline-"))

afterAll(() => rmSync(temporary, { recursive: true, force: true }))

describe("upstream baseline", () => {
  test("pins the approved active OpenCode commit", () => {
    expect(baseline).toEqual({
      repository: "https://github.com/anomalyco/opencode.git",
      branch: "dev",
      commit: "cd46f22d513d60b7a9bdca1111d25c50d2398355",
      license: "MIT",
    })
  })

  test("rejects an available pinned commit outside HEAD history", () => {
    const repository = initRepository("unmerged")
    git(repository, "commit", "--allow-empty", "-m", "unrelated head")
    git(repository, "fetch", "--depth=1", "--no-tags", root, baseline.commit)
    expect(runGit(repository, "cat-file", "-e", `${baseline.commit}^{commit}`).exitCode).toBe(0)
    expect(runGit(repository, "merge-base", "--is-ancestor", baseline.commit, "HEAD").exitCode).not.toBe(0)

    const result = runVerifier(repository)

    expect(result.exitCode).not.toBe(0)
    expect(result.stderr.toString()).toContain(`Pinned upstream commit ${baseline.commit} is not an ancestor of HEAD`)
  })

  test("accepts the pinned commit when it is an ancestor of HEAD", () => {
    const repository = initRepository("imported")
    git(repository, "fetch", "--depth=1", "--no-tags", root, baseline.commit)
    const descendant = git(
      repository,
      "commit-tree",
      `${baseline.commit}^{tree}`,
      "-p",
      baseline.commit,
      "-m",
      "descendant",
    ).stdout.toString().trim()
    git(repository, "update-ref", "HEAD", descendant)

    const result = runVerifier(repository)

    expect(result.exitCode).toBe(0)
    expect(result.stdout.toString().trim()).toBe(`${baseline.repository}@${baseline.commit}`)
    expect(result.stderr.toString()).toBe("")
  })
})

function initRepository(name: string) {
  const directory = join(temporary, name)
  mkdirSync(directory)
  git(directory, "init", "--quiet")
  git(directory, "config", "user.name", "Baseline Verifier Test")
  git(directory, "config", "user.email", "baseline-verifier@example.invalid")
  return directory
}

function git(cwd: string, ...args: string[]) {
  const result = runGit(cwd, ...args)
  if (result.exitCode === 0) return result
  throw new Error(`git ${args.join(" ")} failed:\n${result.stderr.toString()}`)
}

function runGit(cwd: string, ...args: string[]) {
  return Bun.spawnSync(["git", ...args], { cwd, stdout: "pipe", stderr: "pipe" })
}

function runVerifier(cwd: string) {
  return Bun.spawnSync([process.execPath, verifier], { cwd, stdout: "pipe", stderr: "pipe" })
}
