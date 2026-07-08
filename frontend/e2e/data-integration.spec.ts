/** DataIntegration e2e — 验证 ODS 集成页面渲染 + Tab 交互（不依赖真机）。 */
import { test, expect } from '@playwright/test'

test('DataIntegration 加载 — ODS DI tab 展示数据源列表', async ({ page }) => {
  await page.goto('/di')

  // Element Plus el-radio-button：用文本定位，避免 inner span 拦截 pointer events
  await page.locator('.el-radio-button').filter({ hasText: 'ODS DI' }).click()

  // fake-server 的 /api/workspace/datasources 返回 dataworks / dataworks_holo 数据源
  await expect(page.getByText('dataworks', { exact: false }).first()).toBeVisible({ timeout: 10000 })
})

test('DataIntegration 批量部署 tab — 渲染表单 + 提交按钮', async ({ page }) => {
  await page.goto('/di')

  await page.locator('.el-radio-button').filter({ hasText: '批量部署' }).click()

  const card = page.locator('.el-card').filter({ hasText: '批量部署 ODS/DWD 表' })
  await expect(card).toBeVisible()
  // 避免与 tab 上的「批量部署」radio 冲突，只断言表单内 primary 按钮
  await expect(card.locator('.el-form .el-button--primary')).toHaveText('批量部署')
})
