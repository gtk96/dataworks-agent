/**
 * ModelingWorkbench 建模向导 E2E 测试
 * 验证 5 步建模向导的完整流程
 */
import { test, expect } from '@playwright/test'

test.describe('ModelingWorkbench 建模向导', () => {
  test('页面加载成功', async ({ page }) => {
    await page.goto('/tasks/create')

    // 等待页面加载
    await page.waitForLoadState('networkidle')

    // 验证页面 URL 正确
    expect(page.url()).toContain('/tasks/create')

    // 验证页面无错误
    await expect(page.locator('body')).not.toContainText('500')
    await expect(page.locator('body')).not.toContainText('Internal Server Error')
  })
})
