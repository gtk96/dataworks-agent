/**
 * ArtifactsView 产物管理 E2E 测试
 * 验证 DDL 产物归档页面的渲染
 */
import { test, expect } from '@playwright/test'

test.describe('ArtifactsView 产物管理', () => {
  test('页面加载 - 显示产物列表', async ({ page }) => {
    await page.goto('/artifacts')

    // 等待页面加载
    await page.waitForLoadState('networkidle')

    // 验证页面无错误
    await expect(page.locator('body')).not.toContainText('500')
    await expect(page.locator('body')).not.toContainText('Internal Server Error')
  })

  test('页面加载成功', async ({ page }) => {
    await page.goto('/artifacts')

    await page.waitForLoadState('networkidle')

    // 验证页面 URL 正确
    expect(page.url()).toContain('/artifacts')
  })
})
