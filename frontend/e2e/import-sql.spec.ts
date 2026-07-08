/** ImportSql e2e — 验证 SQL 目录解析。本页仅建表，不配置调度/节点/依赖（878464a）。 */
import { test, expect } from '@playwright/test'

test('ImportSql 预览真实 SQL 目录 — 展示 3 张 DIM 表', async ({ page }) => {
  await page.goto('/import')

  // 路径默认填了 E:/dw-modeling-template/sql/order-fulfillment
  // 但 mock 服务器返回 mock 数据,直接验证前端渲染

  // 点"预览"按钮
  const previewBtn = page.getByRole('button', { name: '预览' })
  await previewBtn.click()

  // 等预览结果
  await expect(page.getByText('dim_ord_ofc_cancel_reason_all').first()).toBeVisible({ timeout: 10000 })
  await expect(page.getByText('dim_ord_oms_platform_all').first()).toBeVisible()
  await expect(page.getByText('dim_ord_oms_payment_all').first()).toBeVisible()
})

test('ImportSql 不再展示调度 UI — 878464a 后本页仅建表', async ({ page }) => {
  await page.goto('/import')

  await page.getByRole('button', { name: '预览' }).click()
  await expect(page.getByText('dim_ord_ofc_cancel_reason_all').first()).toBeVisible({ timeout: 10000 })

  // 878464a 删了 buildSchedule + 调度摘要卡片 + cron 列，本页不展示任何调度相关 UI
  await expect(page.getByText('已生成调度配置')).toHaveCount(0)
  // cron 00 01 是调度卡的特征字符串；现在不再出现
  await expect(page.locator('body')).not.toContainText('00 01')
})
