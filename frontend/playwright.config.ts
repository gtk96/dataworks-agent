import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || '../reports/continuous-dialogue/playwright-artifacts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  reporter: [
    ['list'],
    ['junit', { outputFile: process.env.PLAYWRIGHT_JUNIT_OUTPUT || '../reports/continuous-dialogue/playwright-junit.xml' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:15173',
    trace: 'on',
    screenshot: 'only-on-failure',
    video: 'on',
    ...devices['Desktop Chrome'],
  },
  webServer: [
    {
      command: 'uv run --project .. python ../tests/e2e/dialogue_server.py',
      url: 'http://127.0.0.1:18085/api/health',
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 15173',
      url: 'http://127.0.0.1:15173',
      timeout: 120_000,
      reuseExistingServer: false,
      env: { VITE_PROXY_TARGET: 'http://127.0.0.1:18085' },
    },
  ],
})
