/** SyncManager e2e — 验证双环境同步页面渲染 + 差异对比交互。 */
import { test, expect } from '@playwright/test'

test('SyncManager 加载 — 表格 + 同步历史卡片', async ({ page }) => {
  await page.goto('/sync')

  // /api/sync/tables 响应包含 dwd_test
  await expect(page.getByText('dwd_test').first()).toBeVisible({ timeout: 10000 })
  // 同步历史卡片
  await expect(page.getByText('同步历史')).toBeVisible()
})

test('SyncManager 差异对比 — 点击对比触发 /api/sync/diff', async ({ page }) => {
  await page.goto('/sync')

  // 点首行的「对比」按钮，触发 POST /api/sync/diff
  await page.getByRole('button', { name: '对比' }).first().click()

  // fake-server 对 /api/sync/diff 返回 has_changes:false → 应展示“已一致”
  await expect(page.getByText('dev 和 prod 已一致')).toBeVisible({ timeout: 10000 })
})
