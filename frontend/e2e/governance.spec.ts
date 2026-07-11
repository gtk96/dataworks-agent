/** GovernanceHub 词根字典 e2e — 验证页面渲染 + API 调用 + 搜索交互。 */
import { test, expect } from '@playwright/test'

test('GovernanceHub 词根 Tab 默认加载并展示词根列表', async ({ page }) => {
  await page.goto('/governance')

  // 切换到 词根字典 Tab
  await page.getByRole('tab', { name: '词根字典' }).click()

  // API 调用的响应(json 块)应包含 total: 4
  await expect(page.locator('pre.code-block')).toContainText('"total": 4', { timeout: 10000 })

  // 验证词根渲染 — 至少有 order_id 一条
  await expect(page.locator('pre.code-block')).toContainText('order_id')
})

test('GovernanceHub 词根搜索 — 输入 order_amt 应过滤响应', async ({ page }) => {
  await page.goto('/governance')
  await page.getByRole('tab', { name: '词根字典' }).click()

  // 等默认列表出现
  await expect(page.locator('pre.code-block')).toContainText('order_id', { timeout: 10000 })

  // 输入搜索词
  const search = page.getByPlaceholder('搜索词根（留空显示常用）')
  await search.fill('amt')
  // 等待 debounce 300ms + API 响应
  await page.waitForTimeout(800)

  // 响应文本应包含 amt 相关的词根
  const content = await page.locator('pre.code-block').textContent()
  expect(content).toBeTruthy()
  // total 至少 1(我们 mock 了 order_amt)
  expect(content!.toLowerCase()).toContain('amt')
})

test('GovernanceHub 表名解析 — 输入 dwd_ord_ofc_s_order_hour 解析成功', async ({ page }) => {
  await page.goto('/governance')
  // 表名解析在规范参考 Tab 下的 collapse 中
  await page.getByRole('tab', { name: '规范参考' }).click()

  // 展开命名工具 collapse
  await page.getByText('命名工具（表名解析 + 更新方式推断）').click()

  const input = page.getByPlaceholder('输入表名，如 dwd_ord_s_order_hour')
  await input.fill('dwd_ord_ofc_s_order_hour')
  await page.getByRole('button', { name: '解析', exact: true }).click()

  // 后端返回 {status: "ok", parsed: {layer: "DWD", ...}},前端 JSON.stringify 输出
  await expect(page.locator('pre.code-block')).toContainText('DWD', { timeout: 10000 })
  const content = await page.locator('pre.code-block').textContent()
  expect(content).toBeTruthy()
  expect(content!.length).toBeGreaterThan(20)
})
