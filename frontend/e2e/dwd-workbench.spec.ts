/**
 * DwdWorkbench DWD JSON 模式建模 E2E 测试
 * 验证 DWD JSON 模式建模页面的渲染
 */
import { test, expect } from '@playwright/test'

test.describe('DwdWorkbench DWD JSON 模式', () => {
  test('页面加载成功', async ({ page }) => {
    await page.goto('/dwd')

    // 等待页面加载
    await page.waitForLoadState('networkidle')

    // 验证页面 URL 正确
    expect(page.url()).toContain('/dwd')

    // 验证页面无错误
    await expect(page.locator('body')).not.toContainText('500')
    await expect(page.locator('body')).not.toContainText('Internal Server Error')
  })
})
