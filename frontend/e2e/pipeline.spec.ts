/**
 * PipelineHub 管道队列 E2E 测试
 * 验证持久化管道队列页面的渲染
 */
import { test, expect } from '@playwright/test'

test.describe('PipelineHub 管道队列', () => {
  test('页面加载成功', async ({ page }) => {
    await page.goto('/pipeline')

    // 等待页面加载
    await page.waitForLoadState('networkidle')

    // 验证页面 URL 正确
    expect(page.url()).toContain('/pipeline')

    // 验证页面无错误
    await expect(page.locator('body')).not.toContainText('500')
    await expect(page.locator('body')).not.toContainText('Internal Server Error')
  })
})
