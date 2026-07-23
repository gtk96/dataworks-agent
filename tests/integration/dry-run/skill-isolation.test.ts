import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { mkdirSync, rmSync, writeFileSync } from "fs"
import { join } from "path"
import {
  checkToolAgainstSkill,
  parseSkillMarkdown,
  permissionForTool,
  systemSkillsRoot,
  userSkillsRoot,
} from "../../../packages/dataworks-core/src/skill"
import { SkillRepo } from "../../../packages/dataworks-control/src/skill/repo"
import {
  SkillContext,
  resetSkillContext,
} from "../../../packages/dataworks-plugin/src/skill-context"

const base = join(import.meta.dir, ".skill-isolation-test-tmp")
const appData = join(base, "app-data")
const userA = "user-a"
const userB = "user-b"

function skillMd(name: string, body: string, extra: Record<string, unknown> = {}) {
  const fm: Record<string, unknown> = {
    name,
    description: `Skill ${name}`,
    triggers: ["t1"],
    allowed_tools: ["dw_run_sql", "dw_list_tables", "dw_describe_table"],
    forbidden_tools: ["dw_rerun_job", "dw_trigger_supplement"],
    max_tool_calls_per_session: 20,
    write_enabled: false,
    ...extra,
  }
  const yaml = Object.entries(fm)
    .map(([k, v]) => {
      if (Array.isArray(v)) return `${k}: [${v.map((x) => JSON.stringify(x)).join(", ")}]`
      if (typeof v === "boolean" || typeof v === "number") return `${k}: ${v}`
      return `${k}: ${JSON.stringify(v)}`
    })
    .join("\n")
  return `---\n${yaml}\n---\n\n${body}\n`
}

beforeAll(() => {
  rmSync(base, { recursive: true, force: true })
  mkdirSync(appData, { recursive: true })
})

afterAll(() => {
  resetSkillContext()
  try {
    rmSync(base, { recursive: true, force: true })
  } catch {
    // Windows may keep the sqlite handle briefly locked
  }
})

describe("skill isolation dry-run", () => {
  test("system + per-user skills: each worker sees only system + own skill", () => {
    const repo = new SkillRepo({ appDataRoot: appData })
    repo.ensureRoots(userA)
    repo.ensureRoots(userB)

    repo.writeSystem({
      name: "system-playbook",
      markdown: skillMd("system-playbook", "SYSTEM shared playbook content"),
    })

    repo.writeUser(userA, {
      name: "logistics-anomaly",
      markdown: skillMd("logistics-anomaly", "USER_A logistics body"),
    })
    repo.writeUser(userB, {
      name: "logistics-anomaly",
      markdown: skillMd("logistics-anomaly", "USER_B logistics body"),
    })

    const rootsA = repo.discoveryRoots(userA)
    const rootsB = repo.discoveryRoots(userB)
    expect(rootsA).toContain(systemSkillsRoot(appData))
    expect(rootsA).toContain(userSkillsRoot(appData, userA))
    expect(rootsB).toContain(userSkillsRoot(appData, userB))
    expect(rootsA).not.toContain(userSkillsRoot(appData, userB))

    const workerA = new SkillContext({ roots: rootsA, userId: userA, appDataRoot: appData })
    const workerB = new SkillContext({ roots: rootsB, userId: userB, appDataRoot: appData })

    const listA = workerA.list().map((s) => s.name).sort()
    const listB = workerB.list().map((s) => s.name).sort()

    expect(listA).toEqual(["logistics-anomaly", "system-playbook"])
    expect(listB).toEqual(["logistics-anomaly", "system-playbook"])

    const loadA = workerA.loadSkillTool("logistics-anomaly")
    const loadB = workerB.loadSkillTool("logistics-anomaly")
    expect(loadA).toBeTruthy()
    expect(loadB).toBeTruthy()
    expect(loadA!.output).toContain("USER_A logistics body")
    expect(loadB!.output).toContain("USER_B logistics body")
    expect(loadA!.output).not.toContain("USER_B")
    expect(loadB!.output).not.toContain("USER_A")

    expect(workerA.loadSkillTool("system-playbook")!.output).toContain("SYSTEM shared")
    expect(workerB.loadSkillTool("system-playbook")!.output).toContain("SYSTEM shared")

    repo.writeUser(userB, {
      name: "b-only-skill",
      markdown: skillMd("b-only-skill", "secret-to-b"),
    })
    workerA.reload()
    workerB.reload()
    expect(workerA.get("b-only-skill")).toBeUndefined()
    expect(workerB.get("b-only-skill")?.content).toContain("secret-to-b")
  })

  test("hot-reload: modify user A SKILL.md; reload only affects A", () => {
    const repo = new SkillRepo({ appDataRoot: appData })
    if (!repo.get(userA, "logistics-anomaly")) {
      repo.writeUser(userA, {
        name: "logistics-anomaly",
        markdown: skillMd("logistics-anomaly", "USER_A logistics body"),
      })
    }
    if (!repo.get(userB, "logistics-anomaly")) {
      repo.writeUser(userB, {
        name: "logistics-anomaly",
        markdown: skillMd("logistics-anomaly", "USER_B logistics body"),
      })
    }

    const workerA = new SkillContext({ roots: repo.discoveryRoots(userA) })
    const workerB = new SkillContext({ roots: repo.discoveryRoots(userB) })

    expect(workerA.loadSkillTool("logistics-anomaly")!.output).toContain("USER_A")
    expect(workerB.loadSkillTool("logistics-anomaly")!.output).toContain("USER_B")

    repo.writeUser(userA, {
      name: "logistics-anomaly",
      markdown: skillMd("logistics-anomaly", "USER_A reloaded content v2"),
    })

    workerA.reload()
    const reloadedA = workerA.loadSkillTool("logistics-anomaly")
    expect(reloadedA!.output).toContain("USER_A reloaded content v2")
    expect(reloadedA!.output).not.toContain("USER_A logistics body")

    const stillB = workerB.loadSkillTool("logistics-anomaly")
    expect(stillB!.output).toContain("USER_B logistics body")
    expect(stillB!.output).not.toContain("reloaded content v2")

    workerB.reload()
    expect(workerB.loadSkillTool("logistics-anomaly")!.output).toContain("USER_B logistics body")
  })

  test("frontmatter policy: forbidden deny, allowed narrow, write gate, max calls", () => {
    const { meta } = parseSkillMarkdown(
      skillMd("logistics-anomaly", "body", {
        max_tool_calls_per_session: 2,
        write_enabled: false,
      }),
    )
    expect(meta.name).toBe("logistics-anomaly")
    expect(permissionForTool(meta, "dw_rerun_job", true)).toBe("deny")
    expect(permissionForTool(meta, "dw_run_sql", false)).toBe("allow")
    expect(permissionForTool(meta, "dw_list_jobs", false)).toBe("deny")
    expect(permissionForTool(meta, "dw_rerun_job", false)).toBe("deny")

    const writeOn = parseSkillMarkdown(
      skillMd("w", "body", {
        name: "w",
        write_enabled: true,
        allowed_tools: ["dw_rerun_job"],
        forbidden_tools: [],
      }),
    ).meta
    expect(permissionForTool(writeOn, "dw_rerun_job", true)).toBe("ask")
    expect(permissionForTool(writeOn, "dw_rerun_job", false)).toBe("deny")

    expect(
      checkToolAgainstSkill({
        skill: meta,
        tool: "dw_rerun_job",
        connectionWriteEnabled: true,
        usedCalls: 0,
      })._tag,
    ).toBe("SkillToolDenied")

    const ctx = new SkillContext({ roots: [userSkillsRoot(appData, userA)] })
    ctx.setActiveSkill("ses1", "logistics-anomaly")
    ctx.reload()
    ctx.setActiveSkill("ses1", "logistics-anomaly")

    expect(ctx.gateTool({ sessionID: "ses1", tool: "dw_run_sql" })._tag).toBe("ok")
    expect(ctx.gateTool({ sessionID: "ses1", tool: "dw_run_sql" })._tag).toBe("ok")

    const denied = ctx.gateTool({ sessionID: "ses1", tool: "dw_rerun_job" })
    expect(denied._tag).toBe("SkillToolDenied")

    const tightPath = join(userSkillsRoot(appData, userA), "tight-limit")
    mkdirSync(tightPath, { recursive: true })
    writeFileSync(
      join(tightPath, "SKILL.md"),
      skillMd("tight-limit", "t", { name: "tight-limit", max_tool_calls_per_session: 1, forbidden_tools: [] }),
    )
    const tight = new SkillContext({ roots: [userSkillsRoot(appData, userA)] })
    tight.setActiveSkill("ses-limit", "tight-limit")
    expect(tight.gateTool({ sessionID: "ses-limit", tool: "dw_run_sql" })._tag).toBe("ok")
    const limited = tight.gateTool({ sessionID: "ses-limit", tool: "dw_run_sql" })
    expect(limited._tag).toBe("SkillToolLimitExceeded")
  })

  test("API: normal user cannot write system skills", async () => {
    const { makeApp, createUser } = await import("../../../packages/dataworks-control/src/http/server")
    const { generateMasterKey } = await import("../../../packages/dataworks-control/src/secret/store")
    const { randomBytes } = await import("crypto")

    const tmp = join(base, "api-tmp")
    mkdirSync(tmp, { recursive: true })
    const appHandle = await makeApp({
      dbPath: join(tmp, "test.db"),
      secretsRoot: join(tmp, ".secrets"),
      appDataRoot: appData,
      publicOrigin: "http://dwa.test",
      masterKey: generateMasterKey(),
      startServer: false,
    })

    const email = `skill-${randomBytes(4).toString("hex")}@example.com`
    await createUser({ email, password: "testpass123", role: "user" }, appHandle.db)
    const loginRes = await appHandle.app.request("http://dwa.test/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json", origin: "http://dwa.test" },
      body: JSON.stringify({ email, password: "testpass123" }),
    })
    expect(loginRes.status).toBe(204)
    const cookie = (loginRes.headers.get("set-cookie") ?? "").split(";")[0]!

    const putSystem = await appHandle.app.request("http://dwa.test/api/skills/system/evil", {
      method: "PUT",
      headers: {
        cookie,
        origin: "http://dwa.test",
        "content-type": "application/json",
      },
      body: JSON.stringify({ markdown: skillMd("evil", "nope", { name: "evil" }) }),
    })
    expect(putSystem.status).toBe(403)

    const postUser = await appHandle.app.request("http://dwa.test/api/skills", {
      method: "POST",
      headers: {
        cookie,
        origin: "http://dwa.test",
        "content-type": "application/json",
      },
      body: JSON.stringify({ name: "my-skill", markdown: skillMd("my-skill", "ok", { name: "my-skill" }) }),
    })
    expect(postUser.status).toBe(201)

    const list = await appHandle.app.request("http://dwa.test/api/skills", {
      method: "GET",
      headers: { cookie, origin: "http://dwa.test" },
    })
    expect(list.status).toBe(200)
    const body = (await list.json()) as { system: { name: string }[]; user: { name: string }[] }
    expect(body.system.some((s) => s.name === "system-playbook")).toBe(true)
    expect(body.user.some((s) => s.name === "my-skill")).toBe(true)

    appHandle.db.close()
  })
})
