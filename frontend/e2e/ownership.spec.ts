/**
 * OwnershipView 产权查询 E2E 测试
 * 验证产权查询页面的渲染和交互
 */
import { test, expect } from '@playwright/test'

test.describe('OwnershipView 产权查询', () => {
  test('页面加载成功', async ({ page }) => {
    await page.goto('/ownership')

    // 等待页面加载
    await page.waitForLoadState('networkidle')

    // 验证页面 URL 正确
    expect(page.url()).toContain('/ownership')

    // 验证页面无错误
    await expect(page.locator('body')).not.toContainText('500')
    await expect(page.locator('body')).not.toContainText('Internal Server Error')
  })
})
