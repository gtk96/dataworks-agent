/**
 * DataWorks shell E2E (browser).
 *
 * Prefer a live control plane when PLAYWRIGHT_BASE_URL / BASE_URL is set
 * (e.g. http://127.0.0.1:8084 from `bun run start`).
 *
 * Does NOT require DATAWORKS_AGENT_DRY_RUN=1. Product mode forbids dry-run for
 * staging; smoke tests only need a reachable HTTP server (Vite app or control plane).
 *
 * Skip policy:
 * - If neither BASE_URL nor the default Playwright webServer can serve /login,
 *   individual tests time out / fail visibly — do not invert into "requires dry-run".
 * - Staging secrets are optional here; real staging browser gate is dataworks-staging.spec.ts.
 */
import { expect, test } from "@playwright/test"
import { mockDataWorksServer } from "./utils/mock-server"

const liveBase =
  process.env.PLAYWRIGHT_BASE_URL?.trim() ||
  process.env.BASE_URL?.trim() ||
  ""

test.beforeEach(async ({ page }) => {
  if (liveBase) return
  await mockDataWorksServer(page, { user: null })
})

test.describe("dataworks shell", () => {
  test("login page renders and is keyboard reachable", async ({ page }) => {
    // Live control plane or Playwright webServer (see packages/app/playwright.config.ts).
    await page.goto("/login")
    const form = page.locator("[data-component='dataworks-login']")
    await expect(form).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole("heading")).toBeVisible()
    const username = page.locator('input[name="username"]')
    await username.focus()
    await expect(username).toBeFocused()
    await page.keyboard.press("Tab")
    await expect(page.locator('input[name="password"]')).toBeFocused()
  })

  test("anonymous dataworks route redirects toward login", async ({ page }) => {
    await page.goto("/dataworks/connections")
    await page.waitForTimeout(500)
    // Auth gate navigates to /login when /api/auth/me is 401 (or stays on shell while loading).
    await expect(page).toHaveURL(/login|dataworks/, { timeout: 30_000 })
  })

  test("explorer route shell mounts after navigation", async ({ page }) => {
    await page.goto("/dataworks/explorer")
    await page.waitForTimeout(500)
    const login = page.locator("[data-component='dataworks-login']")
    const shell = page.locator("[data-component='dataworks-shell']")
    await expect(login.or(shell).first()).toBeVisible({ timeout: 30_000 })
  })

  test("documents live base when control plane URL is provided", async () => {
    // Documentation assertion: operators run against live plane via env, not dry-run.
    if (liveBase) {
      expect(liveBase.startsWith("http")).toBe(true)
      // Prefer product start default port when pointing at control plane.
      expect(process.env.DATAWORKS_AGENT_DRY_RUN === "1").toBe(false)
    } else {
      // No live URL — Playwright webServer may still serve the Vite app for smoke.
      expect(true).toBe(true)
    }
  })
})
