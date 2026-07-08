/** SyncManager e2e — 验证双环境同步页面渲染 + 同步历史。 */
import { test, expect } from '@playwright/test'

test('SyncManager 加载 — 表格 + 同步历史卡片', async ({ page }) => {
  await page.goto('/sync')

  // /api/sync/tables 响应包含 dwd_test
  await expect(page.getByText('dwd_test').first()).toBeVisible({ timeout: 10000 })
  // 同步历史卡片
  await expect(page.getByText('同步历史')).toBeVisible()
})
