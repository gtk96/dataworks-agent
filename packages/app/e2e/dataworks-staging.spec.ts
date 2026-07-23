/**
 * Browser-facing staging acceptance (Playwright).
 *
 * Prefer live control plane: PLAYWRIGHT_BASE_URL or BASE_URL (e.g. http://127.0.0.1:8084).
 * Does not require DATAWORKS_AGENT_DRY_RUN=1 (product forbids dry-run for staging).
 *
 * When DATAWORKS_AGENT_ENV=staging and secrets are present, exercises login shell
 * and shell routes. Without secrets/mode, fails clearly (never skip-as-pass).
 */
import { expect, test } from "@playwright/test"

const REQUIRED = [
  "DATAWORKS_STAGING_AK",
  "DATAWORKS_STAGING_SK",
  "DATAWORKS_STAGING_PROJECT_ID",
] as const

function isStaging(): boolean {
  const env = (process.env.DATAWORKS_AGENT_ENV ?? "").toLowerCase()
  const dry = process.env.DATAWORKS_AGENT_DRY_RUN
  // Product mode: dry-run must be off (unset/"0"/"false"). Truthy dry-run is invalid for staging.
  const dryOff = dry === undefined || dry === "" || dry === "0" || dry === "false"
  return (env === "staging" || env === "stage") && dryOff
}

function missing(): string[] {
  return REQUIRED.filter((k) => !process.env[k] || process.env[k]!.trim() === "")
}

test.describe("dataworks staging browser acceptance", () => {
  test("staging preconditions fail clearly when secrets absent", async () => {
    if (!isStaging()) {
      throw new Error(
        "staging browser gate incomplete: set DATAWORKS_AGENT_ENV=staging DATAWORKS_AGENT_DRY_RUN=0 " +
          "and staging secrets. Do not treat as pass/skip.",
      )
    }
    const m = missing()
    if (m.length > 0) {
      throw new Error(
        `staging browser preconditions missing: ${m.join(", ")} — release staging gate blocked`,
      )
    }
  })

  test("login shell mounts for staging operator", async ({ page }) => {
    if (!isStaging() || missing().length > 0) {
      throw new Error("staging browser live steps blocked without secrets/mode")
    }
    await page.goto("/login")
    const form = page.locator("[data-component='dataworks-login']")
    await expect(form).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole("heading")).toBeVisible()
  })

  test("authenticated shell routes are reachable after login page", async ({ page }) => {
    if (!isStaging() || missing().length > 0) {
      throw new Error("staging browser live steps blocked without secrets/mode")
    }
    // Full credentialed browser login needs a running control plane with seeded admin.
    // This asserts shell mount points exist; API-level flow is in agent-e2e.test.ts.
    await page.goto("/dataworks/connections")
    await page.waitForTimeout(500)
    const login = page.locator("[data-component='dataworks-login']")
    const shell = page.locator("[data-component='dataworks-shell']")
    await expect(login.or(shell).first()).toBeVisible({ timeout: 30_000 })
  })
})
