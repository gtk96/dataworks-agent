/**
 * ModelingDashboard 仪表盘 E2E 测试
 * 验证首页仪表盘的渲染和数据展示
 */
import { test, expect } from '@playwright/test'

test.describe('ModelingDashboard 仪表盘', () => {
  test('首页加载成功', async ({ page }) => {
    await page.goto('/')

    // 等待仪表盘加载
    await page.waitForLoadState('networkidle')

    // 验证页面 URL 正确
    expect(page.url()).toContain('/')

    // 验证页面无错误
    await expect(page.locator('body')).not.toContainText('500')
    await expect(page.locator('body')).not.toContainText('Internal Server Error')
  })

  test('首页显示分层分布', async ({ page }) => {
    await page.goto('/')

    // 等待分层数据加载
    await expect(page.locator('body')).toContainText('DWD', { timeout: 10000 })
    await expect(page.locator('body')).toContainText('DIM', { timeout: 10000 })
  })
})
