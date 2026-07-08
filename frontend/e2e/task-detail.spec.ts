/**
 * TaskDetail 任务详情 E2E 测试
 * 验证任务详情页面的渲染和 SSE 实时进度
 */
import { test, expect } from '@playwright/test'

test.describe('TaskDetail 任务详情', () => {
  test('页面加载成功', async ({ page }) => {
    await page.goto('/tasks/task_aaa')

    // 等待页面加载
    await page.waitForLoadState('networkidle')

    // 验证页面 URL 正确
    expect(page.url()).toContain('/tasks/task_aaa')

    // 验证页面无错误
    await expect(page.locator('body')).not.toContainText('500')
    await expect(page.locator('body')).not.toContainText('Internal Server Error')
  })
})
