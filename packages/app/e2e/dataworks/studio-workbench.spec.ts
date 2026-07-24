import { expect, test, type Page, type Route, type TestInfo } from "@playwright/test"
import { mkdir } from "node:fs/promises"
import path from "node:path"
import { setupTimeline, assistantMessage, textPart, userMessage } from "../performance/timeline-stability/fixture"

const connection = {
  id: "conn-acceptance",
  userId: "user-acceptance",
  name: "Read-only analytics",
  region: "cn-hangzhou",
  accessKeyDisplay: "AK...7890",
  writeEnabled: false,
  timeCreated: 1,
  timeUpdated: 1,
}

const projects = [
  { projectId: "project-one", id: "project-one", projectName: "analytics", name: "analytics", region: "cn-hangzhou" },
  { projectId: "project-two", id: "project-two", projectName: "reporting", name: "reporting", region: "cn-hangzhou" },
]

const sqlResult = {
  columns: Array.from({ length: 60 }, (_, index) => ({ name: `column_${index + 1}`, type: "string" })),
  rows: Array.from({ length: 30 }, (_, row) => Array.from({ length: 60 }, (_, column) => `row-${row}-column-${column}`)),
  truncated: true,
  durationMs: 3,
}

test("opens Agent SQL without execution, preserves safe preview context, and adapts across workbench widths", async ({ page }, testInfo: TestInfo) => {
  const evidence = path.resolve(process.cwd(), "../../.superpowers/evidence")
  const errors: string[] = []
  const submitted: unknown[] = []
  let todoBody = ""
  let todoCalls = 0
  let sqlCalls = 0
  let sqlMode: "success" | "invalid-json" | "hold" = "success"
  let heldSql: Promise<void> | undefined
  let releaseHeldSql = () => {}
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.endsWith("/todo")) todoCalls += 1
  })
  page.on("response", async (response) => {
    if (new URL(response.url()).pathname.endsWith("/todo")) todoBody = await response.text()
  })
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text())
  })
  page.on("pageerror", (error) => errors.push(error.message))

  await page.addInitScript(() => {
    document.addEventListener("DOMContentLoaded", () => document.body.setAttribute("data-new-layout", ""))
  })
  await installDataWorksFixtures(page, async () => {
    sqlCalls += 1
    if (sqlMode !== "hold" || !heldSql) return sqlMode
    await heldSql
    return "success"
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await setupTimeline(page, {
    settings: { newLayoutDesigns: true },
    dataworks: {
      user: { id: "user-acceptance", email: "acceptance@example.test", role: "admin" },
      connections: [connection],
    },
    todos: [{ id: "todo-workbench", content: "Inspect the generated SQL", status: "in_progress", priority: "high" }],
    messages: [
      userMessage(),
      assistantMessage([textPart("prt_agent_sql", "Run this read-only query:\n\n```sql\nSELECT * FROM orders LIMIT 100\n```")]),
    ],
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.route("**/session/*/prompt_async", async (route) => {
    submitted.push(route.request().postDataJSON())
    await route.fulfill({ contentType: "application/json", body: "{}" })
  })

  const workbench = page.locator('[data-component="studio-workbench"]')
  await expect(workbench).toBeVisible()
  await expect(page.locator("body")).toHaveAttribute("data-new-layout", "")
  await expect(workbench.locator('[data-slot="resource-panel"]')).toBeVisible()
  const agentPanel = workbench.locator('[data-slot="agent-panel"]')
  await expect(agentPanel).toBeVisible()
  await expect
    .poll(() =>
      agentPanel.evaluate((element) => {
        const style = getComputedStyle(element)
        return {
          background: style.getPropertyValue("--v2-background-bg-base").trim(),
          text: style.getPropertyValue("--v2-text-text-base").trim(),
        }
      }),
    )
    .toEqual({ background: "#101720", text: "#edf6fb" })
  await expect
    .poll(() =>
      agentPanel
        .locator('[data-component="session-dataworks-scope"]')
        .evaluate((element) => getComputedStyle(element).backgroundColor),
    )
    .toBe("rgb(16, 23, 32)")
  await expect
    .poll(() =>
      agentPanel.locator('[data-component="prompt-input-v2"]').evaluate((element) => getComputedStyle(element).backgroundColor),
    )
    .toBe("rgb(16, 23, 32)")
  await expect(workbench.locator('[data-component="artifact-workspace"]')).toBeVisible()
  await expect.poll(() => todoCalls).toBeGreaterThan(0)
  await expect.poll(() => todoBody).toContain("Inspect the generated SQL")
  await page.getByRole("tab", { name: "plan" }).click()
  await expect(page.getByText("Inspect the generated SQL", { exact: true })).toBeVisible()
  await page.getByRole("tab", { name: "sql" }).click()
  await page.screenshot({ path: testInfo.outputPath("workbench-1440.png") })

  await page.getByRole("button", { name: "Open in SQL" }).click()
  await expect(page.getByRole("tab", { name: "sql" })).toHaveAttribute("aria-selected", "true")
  expect(sqlCalls).toBe(0)

  const editor = page.getByRole("textbox", { name: "SQL editor" })
  await editor.fill("SELECT 2")
  page.once("dialog", (dialog) => dialog.dismiss())
  await page.getByRole("button", { name: "Open in SQL" }).click()
  await expect(editor).toHaveValue("SELECT 2")
  page.once("dialog", (dialog) => dialog.accept())
  await page.getByRole("button", { name: "Open in SQL" }).click()
  await expect(editor).toHaveValue("SELECT * FROM orders LIMIT 100")

  await page.getByRole("button", { name: "Run" }).click()
  await expect.poll(() => sqlCalls).toBe(1)
  await expect(page.getByRole("tab", { name: "results" })).toHaveAttribute("aria-selected", "true")
  await expect(page.getByRole("columnheader", { name: "column_1", exact: true })).toBeVisible()
  await expect(page.getByRole("cell", { name: "row-0-column-0" })).toBeVisible()
  await expect(page.getByText("Preview truncated.", { exact: true })).toBeVisible()

  await page.getByRole("button", { name: "Attach preview to Agent" }).click()
  const preview = workbench.locator('[data-component="agent-context-chip"]')
  await expect(preview).toHaveAttribute("data-rows", "20")
  await expect(preview).toHaveAttribute("data-columns", "50")
  await mkdir(evidence, { recursive: true })
  await page.screenshot({ path: path.join(evidence, "studio-workbench-1440.png"), fullPage: true })

  const prompt = page.locator('[data-component="prompt-input"]').last()
  await prompt.fill("Explain the attached result")
  await page.getByRole("button", { name: /send/i }).last().click()
  await expect.poll(() => submitted.length).toBe(1)
  await expect(preview).toHaveCount(0)
  expect(JSON.stringify(submitted[0])).toContain("row-0-column-0")
  expect(JSON.stringify(submitted[0])).not.toContain("row-20-column-0")
  expect(JSON.stringify(submitted[0])).not.toContain("column_51")

  await page.getByRole("button", { name: "orders" }).click()
  await expect(page.getByRole("tab", { name: "schema" })).toHaveAttribute("aria-selected", "true")
  await workbench.locator('[data-slot="resource-panel"] [data-component="dataworks-project-selector"]').selectOption("project-two")
  await expect(page.getByText("Select a table to inspect its Schema.")).toBeVisible()
  await page.getByRole("tab", { name: "results" }).click()
  await expect(page.getByText("Run a read-only query to see results.")).toBeVisible()
  await page.getByRole("tab", { name: "sql" }).click()
  await expect(page.getByRole("textbox", { name: "SQL editor" })).toHaveValue("SELECT * FROM orders LIMIT 100")
  sqlMode = "invalid-json"
  await page.getByRole("button", { name: "Run" }).click()
  await expect.poll(() => sqlCalls).toBe(2)
  await expect(workbench.locator('[data-slot="workbench-status"]')).toHaveAttribute("data-state", "error")
  await expect(page.getByRole("button", { name: "Run" })).toBeEnabled()
  sqlMode = "hold"
  heldSql = new Promise<void>((resolve) => {
    releaseHeldSql = resolve
  })
  await page.getByRole("button", { name: "Run" }).click()
  await expect.poll(() => sqlCalls).toBe(3)
  await workbench.locator('[data-slot="resource-panel"] [data-component="dataworks-project-selector"]').selectOption("project-one")
  await expect(workbench.locator('[data-slot="workbench-status"]')).toHaveAttribute("data-state", "idle")
  await expect(page.getByRole("button", { name: "Run" })).toBeEnabled()
  sqlMode = "success"
  await page.getByRole("button", { name: "Run" }).click()
  await expect.poll(() => sqlCalls).toBe(4)
  await expect(page.getByRole("tab", { name: "results" })).toHaveAttribute("aria-selected", "true")
  releaseHeldSql()
  await expect(workbench.locator('[data-slot="workbench-status"]')).toHaveAttribute("data-state", "ready")
  await page.getByRole("separator", { name: "Resize Agent" }).focus()
  await expect(page.getByRole("separator", { name: "Resize Agent" })).toBeFocused()

  await page.setViewportSize({ width: 1024, height: 900 })
  await expect(workbench).toHaveAttribute("data-resource-overlay", "false")
  await expect(workbench).toHaveAttribute("data-agent-overlay", "true")
  await page.getByRole("button", { name: "Resources" }).click()
  await expect(workbench).toHaveAttribute("data-resource-expanded", "false")
  await expect.poll(() => scopeActionsFollowProject(agentPanel)).toBe(true)
  await page.screenshot({ path: path.join(evidence, "studio-workbench-1024.png"), fullPage: true })
  await page.getByRole("button", { name: "Resources" }).click()
  await expect(workbench).toHaveAttribute("data-resource-expanded", "true")
  await page.screenshot({ path: testInfo.outputPath("workbench-1024.png") })

  await page.getByRole("tab", { name: "sql" }).focus()
  await expect(page.getByRole("tab", { name: "sql" })).toBeFocused()
  await page.getByRole("tab", { name: "sql" }).press("ArrowRight")
  await expect(page.getByRole("tab", { name: "results" })).toBeFocused()
  await expect(page.getByRole("tab", { name: "results" })).toHaveAttribute("aria-selected", "true")
  await page.getByRole("tab", { name: "results" }).press("Home")
  await expect(page.getByRole("tab", { name: "plan" })).toBeFocused()
  await page.getByRole("tab", { name: "plan" }).press("End")
  await expect(page.getByRole("tab", { name: "schema" })).toBeFocused()
  await page.getByRole("tab", { name: "sql" }).click()
  await page.getByRole("button", { name: "Run" }).focus()
  await expect(page.getByRole("button", { name: "Run" })).toBeFocused()
  await page.getByRole("button", { name: "Resources" }).focus()
  await expect(page.getByRole("button", { name: "Resources" })).toBeFocused()
  await page.getByRole("separator", { name: "Resize resources" }).focus()
  await expect(page.getByRole("separator", { name: "Resize resources" })).toBeFocused()

  await page.setViewportSize({ width: 768, height: 900 })
  await expect(workbench).toHaveAttribute("data-agent-overlay", "true")
  await expect(workbench).toHaveAttribute("data-agent-expanded", "false")
  await page.getByRole("button", { name: "Agent" }).click()
  await expect(workbench).toHaveAttribute("data-agent-expanded", "true")
  await expect(workbench.locator('[data-slot="agent-panel"]')).toBeVisible()
  await expect.poll(() => scopeActionsFollowProject(agentPanel)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath("workbench-768.png") })
  await page.screenshot({ path: path.join(evidence, "studio-workbench-768.png"), fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole("button", { name: "Navigation" }).click()
  await expect(page.locator('[data-component="dataworks-console"]')).toHaveAttribute("data-mobile-open", "true")
  await expect(page.locator('[data-slot="console-nav"]')).toBeVisible()
  await expect.poll(() => workbench.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)

  const storage = await page.evaluate(() =>
    JSON.stringify({
      local: Object.fromEntries(Object.entries(localStorage)),
      session: Object.fromEntries(Object.entries(sessionStorage)),
    }),
  )
  expect(storage).not.toContain("row-0-column-0")
  expect(storage).not.toContain("AK...7890")
  expect(errors).toEqual([])
})

async function installDataWorksFixtures(
  page: Page,
  onSql: () => Promise<"success" | "invalid-json">,
) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === "/api/auth/me") return json(route, { id: "user-acceptance", email: "acceptance@example.test", role: "admin" })
    if (url.pathname === "/api/data-connections") return json(route, [connection])
    if (url.pathname === "/api/dataworks/projects") return json(route, projects)
    if (url.pathname === "/api/dataworks/tables") {
      const projectID = url.searchParams.get("projectID")
      return json(route, projectID === "project-two" ? [{ name: "reports", type: "table", projectId: projectID }] : [{ name: "orders", type: "table", projectId: projectID }])
    }
    if (url.pathname === "/api/dataworks/tables/orders") {
      return json(route, { name: "orders", projectName: "analytics", columns: [{ name: "id", type: "bigint" }] })
    }
    if (url.pathname === "/api/dataworks/sql") {
      if ((await onSql()) === "invalid-json") return route.fulfill({ contentType: "application/json", body: "{" })
      return json(route, sqlResult)
    }
    return json(route, {})
  })
}

function json(route: Route, body: unknown) {
  return route.fulfill({ contentType: "application/json", body: JSON.stringify(body) })
}

function scopeActionsFollowProject(agentPanel: ReturnType<Page["locator"]>) {
  return agentPanel.locator('[data-component="dataworks-scope-bar"]').evaluate((scope) => {
    const project = scope.querySelector('[data-component="dataworks-project-selector"]')?.getBoundingClientRect()
    const actions = scope.querySelector('[data-slot="write-badge"]')?.parentElement?.getBoundingClientRect()
    if (!project || !actions) return false
    return actions.top >= project.bottom
  })
}
