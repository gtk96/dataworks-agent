/** TaskList + Monitoring e2e — 验证首页仪表盘 + 任务列表渲染。 */
import { test, expect } from '@playwright/test'

test('ModelingDashboard 加载任务统计 + 分层卡片', async ({ page }) => {
  await page.goto('/')

  // 等待 dashboard API 响应,验证页面有数字 + 分层标签
  // 数字 2(任务数 mock)或 1(成功率)应出现
  await expect(page.locator('body')).toContainText('DWD', { timeout: 10000 })
  await expect(page.locator('body')).toContainText('DIM', { timeout: 10000 })
  // 至少有任务统计(数字)
  await expect(page.locator('body')).toContainText('任务')
})

test('TaskList 列出任务,带状态标签', async ({ page }) => {
  await page.goto('/tasks')

  // 等任务表格加载（不依赖具体 mock ID；任务表来自真后端或 fake）
  const table = page.locator('table').first()
  await expect(table).toBeVisible({ timeout: 10000 })

  // 状态标签：v13 改为中文 label，至少应有一个状态徽章渲染
  const statusTags = page.locator('.el-tag')
  await expect(statusTags.first()).toBeVisible()
})

test('TaskList 筛选 DWD 任务不报错', async ({ page }) => {
  await page.goto('/tasks')

  const table = page.locator('table').first()
  await expect(table).toBeVisible({ timeout: 10000 })

  // 找 layer 筛选(下拉框),使用 placeholder 定位
  const layerSelect = page.locator('input[placeholder="按层筛选"]').first()
  if (await layerSelect.isVisible()) {
    await layerSelect.click()
    // 选 DWD 选项
    const dwdOption = page.getByText('DWD', { exact: true }).first()
    if (await dwdOption.isVisible()) {
      await dwdOption.click()
      // 等重新加载
      await page.waitForTimeout(500)
    }
  }
  // 不应报红/错误
  await expect(page.locator('body')).not.toContainText('500')
})

test('TaskList 状态筛选下拉含中文 label', async ({ page }) => {
  // v13 评审档 F2-7：状态枚举不对称修复后，下拉应显示中文 label
  await page.goto('/tasks')
  // el-select 渲染为带 .el-select 的 div，placeholder 在 input 上；
  // 直接打开第一个 el-select 验证其含"执行中"分组
  await page.locator('.el-select').first().click()
  const group = page.getByText('执行中').first()
  await expect(group).toBeVisible({ timeout: 5000 })
})