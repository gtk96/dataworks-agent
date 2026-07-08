/**
 * DataSourceManager 数据源管理 E2E 测试
 * 验证数据源管理页面的渲染和交互
 */
import { test, expect } from '@playwright/test'

test.describe('DataSourceManager 数据源管理', () => {
  test('页面加载成功', async ({ page }) => {
    await page.goto('/datasources')

    // 等待页面加载
    await page.waitForLoadState('networkidle')

    // 验证页面 URL 正确
    expect(page.url()).toContain('/datasources')

    // 验证页面无错误
    await expect(page.locator('body')).not.toContainText('500')
    await expect(page.locator('body')).not.toContainText('Internal Server Error')
  })
})
