/** DataIntegration e2e — 验证 ODS 集成页面渲染 + Tab 交互（不依赖真机）。 */
import { test, expect } from '@playwright/test'

test('DataIntegration 加载 — ODS DI tab 展示数据源列表', async ({ page }) => {
  await page.goto('/di')

  // 默认 tab 为 ODS Holo；切到 ODS DI 以验证数据源加载链路
  await page.getByRole('radio', { name: 'ODS DI' }).click()

  // fake-server 的 /api/workspace/datasources 返回 dataworks / dataworks_holo 数据源
  await expect(page.getByText('dataworks', { exact: false }).first()).toBeVisible({ timeout: 10000 })
})

test('DataIntegration 批量部署 tab — 渲染表单 + 提交按钮', async ({ page }) => {
  await page.goto('/di')

  await page.getByRole('radio', { name: '批量部署' }).click()

  // 批量部署 tab 含 DDL 目录输入与「批量部署」按钮
  await expect(page.getByText('批量部署 ODS/DWD 表')).toBeVisible()
  await expect(page.getByRole('button', { name: '批量部署' })).toBeVisible()
})
