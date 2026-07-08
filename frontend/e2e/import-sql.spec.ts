/** ImportSql e2e — 验证 SQL 目录解析 + 调度配置生成。 */
import { test, expect } from '@playwright/test'

test('ImportSql 预览真实 SQL 目录 — 展示 3 张 DIM 表', async ({ page }) => {
  await page.goto('/import')

  // 路径默认填了 E:/dw-modeling-template/sql/order-fulfillment
  // 但 mock 服务器返回 mock 数据,直接验证前端渲染

  // 点"预览"按钮
  const previewBtn = page.getByRole('button', { name: '预览' })
  await previewBtn.click()

  // 等预览结果(用 .first() 因为同一个表名在预览表 + 调度表里都出现)
  await expect(page.getByText('dim_ord_ofc_cancel_reason_all').first()).toBeVisible({ timeout: 10000 })
  await expect(page.getByText('dim_ord_oms_platform_all').first()).toBeVisible()
  await expect(page.getByText('dim_ord_oms_payment_all').first()).toBeVisible()
})

test('ImportSql 调度配置摘要 — 默认非 none 调度应出现', async ({ page }) => {
  await page.goto('/import')

  await page.getByRole('button', { name: '预览' }).click()
  await expect(page.getByText('dim_ord_ofc_cancel_reason_all').first()).toBeVisible({ timeout: 10000 })

  // 调度摘要卡片应出现
  await expect(page.getByText('已生成调度配置')).toBeVisible()
  // 调度 cron 应展示 (00 01 03 * * ? 形式)
  await expect(page.locator('body')).toContainText('00 01')
})
