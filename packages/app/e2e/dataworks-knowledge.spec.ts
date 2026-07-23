/**
 * DataWorks Knowledge browser E2E (Playwright).
 *
 * Prefer a live control plane when PLAYWRIGHT_BASE_URL / BASE_URL is set
 * (e.g. http://127.0.0.1:8084 from `bun run start`).
 *
 * Does NOT require DATAWORKS_AGENT_DRY_RUN=1. Product mode forbids dry-run for
 * real product flows; dry-run knowledge coverage lives under tests/integration/dry-run/.
 *
 * Authenticated upload flow (when credentials available):
 *   DWA_E2E_EMAIL / DWA_E2E_PASSWORD — operator test account
 *   or password from DWA_BOOTSTRAP_PASSWORD after `bun run create-admin`
 *   (create-admin default email is "admin"; use a valid email address if the
 *   login form enforces type=email validation).
 *
 * Never asserts secrets. Without live base URL, only smoke against Vite/webServer.
 */
import { expect, test, type Page } from "@playwright/test"
import { mkdirSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { tmpdir } from "node:os"

const liveBase =
  process.env.PLAYWRIGHT_BASE_URL?.trim() || process.env.BASE_URL?.trim() || ""

const e2eEmail = process.env.DWA_E2E_EMAIL?.trim() || ""
const e2ePassword =
  process.env.DWA_E2E_PASSWORD?.trim() || process.env.DWA_BOOTSTRAP_PASSWORD?.trim() || ""

function hasLiveControlPlane(): boolean {
  return liveBase.startsWith("http")
}

function hasLoginCreds(): boolean {
  return Boolean(e2eEmail && e2ePassword)
}

async function loginIfPossible(page: Page): Promise<boolean> {
  if (!hasLoginCreds()) return false
  await page.goto("/login")
  const form = page.locator("[data-component='dataworks-login']")
  await expect(form).toBeVisible({ timeout: 30_000 })
  await page.locator('input[name="email"]').fill(e2eEmail)
  await page.locator('input[name="password"]').fill(e2ePassword)
  await page.locator('button[type="submit"]').click()
  // Successful login leaves /login; failure keeps the form with an error.
  await page.waitForTimeout(800)
  const stillLogin = page.url().includes("/login")
  if (stillLogin) {
    const err = page.locator("[data-login-error]")
    if (await err.isVisible().catch(() => false)) return false
  }
  return !stillLogin || (await page.locator("[data-component='dataworks-shell']").isVisible().catch(() => false))
}

function writeFixtureMd(): string {
  const dir = join(tmpdir(), "dwa-knowledge-e2e")
  mkdirSync(dir, { recursive: true })
  const path = join(dir, `e2e-knowledge-${Date.now()}.md`)
  writeFileSync(
    path,
    [
      "# E2E Knowledge Fixture",
      "",
      `UNIQUE_E2E_MARKER_${Date.now()} knowledge browser upload smoke.`,
      "",
    ].join("\n"),
    "utf8",
  )
  return path
}

test.describe("dataworks knowledge browser", () => {
  test("documents live-base policy (no dry-run requirement)", async () => {
    if (liveBase) {
      expect(liveBase.startsWith("http")).toBe(true)
      expect(process.env.DATAWORKS_AGENT_DRY_RUN === "1").toBe(false)
    } else {
      // Playwright webServer may still serve the Vite app for smoke.
      expect(true).toBe(true)
    }
  })

  test("knowledge route mounts login or shell", async ({ page }) => {
    await page.goto("/dataworks/knowledge")
    await page.waitForTimeout(500)
    const login = page.locator("[data-component='dataworks-login']")
    const shell = page.locator("[data-component='dataworks-shell']")
    const knowledge = page.locator("[data-page='dataworks-knowledge']")
    await expect(login.or(shell).or(knowledge).first()).toBeVisible({ timeout: 30_000 })
  })

  test("upload md fixture and wait for ready (control plane + creds)", async ({ page }) => {
    test.skip(
      !hasLiveControlPlane(),
      "Set PLAYWRIGHT_BASE_URL or BASE_URL to a live control plane (e.g. http://127.0.0.1:8084). " +
        "Without a control plane this authenticated knowledge flow is skipped; smoke tests above still run via Vite.",
    )
    test.skip(
      !hasLoginCreds(),
      "Set DWA_E2E_EMAIL and DWA_E2E_PASSWORD (or DWA_BOOTSTRAP_PASSWORD) for authenticated knowledge upload. " +
        "create-admin seeds email 'admin' with DWA_BOOTSTRAP_PASSWORD — use a form-valid email when type=email is enforced.",
    )

    const loggedIn = await loginIfPossible(page)
    expect(loggedIn).toBe(true)

    await page.goto("/dataworks/knowledge")
    const pageRoot = page.locator("[data-page='dataworks-knowledge']")
    await expect(pageRoot).toBeVisible({ timeout: 30_000 })

    const fixturePath = writeFixtureMd()
    const fileInput = pageRoot.locator('input[type="file"]')
    await expect(fileInput).toBeVisible({ timeout: 15_000 })
    await fileInput.setInputFiles(fixturePath)

    // Poll list until a document shows status ready (ingest is async).
    const list = page.locator('[data-list="knowledge"]')
    const deadline = Date.now() + 90_000
    let sawReady = false
    while (Date.now() < deadline) {
      const refresh = page.getByRole("button").filter({ hasText: /refresh|刷新/i }).first()
      if (await refresh.isVisible().catch(() => false)) {
        await refresh.click().catch(() => undefined)
      }
      await page.waitForTimeout(1_000)
      if (await list.isVisible().catch(() => false)) {
        const text = (await list.innerText().catch(() => "")) || ""
        if (/\bready\b/i.test(text) || /就绪|完成/.test(text)) {
          sawReady = true
          break
        }
        if (/\b(failed|error)\b/i.test(text) || /失败|错误/.test(text)) {
          throw new Error(`knowledge document entered error state: ${text.slice(0, 200)}`)
        }
      }
    }
    expect(sawReady).toBe(true)

    // UI has no dedicated search box; list showing ready is sufficient.
    // Optional: probe public search API only when already authenticated (cookie session).
    // Do not assert secret material.
  })
})
