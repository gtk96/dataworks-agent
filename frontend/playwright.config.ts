// Playwright E2E 测试配置。
//
// 策略:
// - 不依赖真后端(8085),用 webServer 起一个 Node fake BFF server
// - Chromium headless + viewport 1280x800
// - baseURL = http://localhost:3000(vite dev server)
// - 截图 + 视频保留失败用例
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 10000,
    navigationTimeout: 15000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command: 'node e2e/fake-server.mjs',
      port: 8086,  // fake-server 占用；vite proxy /api → 8086 由 VITE_PROXY_TARGET 注入
      timeout: 30000,
      reuseExistingServer: true,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: 'node e2e/start-vite.mjs',
      port: 3000,
      timeout: 60000,
      reuseExistingServer: !process.env.CI,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})
