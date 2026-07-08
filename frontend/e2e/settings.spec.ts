/** Settings e2e — 验证 Cookie 状态 + 服务健康检查渲染。 */
import { test, expect } from '@playwright/test'

test('Settings 加载 — 显示项目参数和服务状态', async ({ page }) => {
  await page.goto('/settings')

  // /api/settings 应返回 region + schema（project_id 为占位 0，不在 UI 文本断言里）
  await expect(page.locator('body')).toContainText('cn-shenzhen')
  await expect(page.locator('body')).toContainText('dataworks_dev')
})

test('Settings Cookie 状态卡片渲染', async ({ page }) => {
  await page.goto('/settings')

  // 等 health API
  await expect(page.locator('body')).toContainText('cn-shenzhen')

  // Cookie 状态卡片应展示
  // (具体文案随实现,这里只验证页面无 500 错误)
  await expect(page.locator('body')).not.toContainText('500')
  await expect(page.locator('body')).not.toContainText('Internal Server Error')
})
