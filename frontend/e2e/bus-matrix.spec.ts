/**
 * BusMatrixView 总线矩阵 E2E 测试
 * 验证总线矩阵可视化页面的渲染
 */
import { test, expect } from '@playwright/test'

test.describe('BusMatrixView 总线矩阵', () => {
  test('页面加载成功', async ({ page }) => {
    await page.goto('/bus-matrix')

    // 等待页面加载
    await page.waitForLoadState('networkidle')

    // 验证页面 URL 正确
    expect(page.url()).toContain('/bus-matrix')

    // 验证页面无错误
    await expect(page.locator('body')).not.toContainText('500')
    await expect(page.locator('body')).not.toContainText('Internal Server Error')
  })
})
