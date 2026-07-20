import { expect, test, type Page, type TestInfo } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

type Evidence = { console: string[]; network: Array<{ method: string; url: string }> }

async function send(page: Page, message: string) {
  const response = page.waitForResponse(resp => resp.url().includes('/agent/runs/stream'))
  const composer = page.locator('.composer textarea')
  await composer.fill(message)
  await composer.press('Enter')
  await response
  await expect(composer).toBeEnabled()
}

async function clickOption(page: Page, optionId: string) {
  const response = page.waitForResponse(resp => resp.url().includes('/agent/runs/stream'))
  await page.locator(`[data-interaction-option="${optionId}"]`).click()
  await response
  await expect(page.locator('.composer textarea')).toBeEnabled()
}

async function submitCustom(page: Page, value: string) {
  const response = page.waitForResponse(resp => resp.url().includes('/agent/runs/stream'))
  const card = page.locator('.interaction-card:not(.interaction-card--inactive)')
  await card.locator('.interaction-custom input').fill(value)
  await card.locator('.interaction-custom button').click()
  await response
  await expect(page.locator('.composer textarea')).toBeEnabled()
}

function assistantMessage(page: Page, text: string | RegExp) {
  return page.locator('.message-bubble.assistant .bubble').filter({ hasText: text }).last()
}

test.beforeEach(async ({ page, request }, testInfo) => {
  await request.post('http://127.0.0.1:18085/acceptance/degrade', { data: { mode: '' } })
  const evidence: Evidence = { console: [], network: [] }
  ;(testInfo as TestInfo & { evidence: Evidence }).evidence = evidence
  page.on('console', entry => evidence.console.push(`${entry.type()}: ${entry.text()}`))
  page.on('request', request => evidence.network.push({ method: request.method(), url: request.url() }))
  await page.goto('/')
  await page.waitForLoadState('networkidle')
})

test.afterEach(async ({ page }, testInfo) => {
  const evidence = (testInfo as TestInfo & { evidence: Evidence }).evidence
  const evidenceDir = process.env.AGENT_EVIDENCE_DIR
  if (evidenceDir) {
    mkdirSync(evidenceDir, { recursive: true })
    const slug = testInfo.title.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-|-$/g, '')
    writeFileSync(join(evidenceDir, `${slug}-console.json`), JSON.stringify(evidence.console, null, 2))
    writeFileSync(join(evidenceDir, `${slug}-network.json`), JSON.stringify(evidence.network, null, 2))
  }
  await testInfo.attach('frontend-console', {
    body: Buffer.from(JSON.stringify(evidence.console, null, 2)),
    contentType: 'application/json',
  })
  await testInfo.attach('network-events', {
    body: Buffer.from(JSON.stringify(evidence.network, null, 2)),
    contentType: 'application/json',
  })
  await page.screenshot({ path: testInfo.outputPath('final.png'), fullPage: true })
  const forbidden = evidence.network.filter(item => {
    const path = new URL(item.url).pathname
    return item.method !== 'GET'
      && !path.startsWith('/agent/runs/stream')
      && !path.startsWith('/acceptance/')
  })
  expect(forbidden).toEqual([])
})

test('journey 1: greeting to table columns with natural language', async ({ page }) => {
  await send(page, '你好')
  await expect(assistantMessage(page, '你好！我可以协助你查表、问数、建模和排障。')).toBeVisible()
  await clickOption(page, 'find_table')
  await submitCustom(page, '订单')
  await send(page, '什么意思')
  await send(page, '第二个')
  await send(page, '查看字段')
  await expect(assistantMessage(page, '已读取 dw.dws_orders_summary 的 2 个字段。')).toBeVisible()
})

test('journey 2: layer and custom refinement remain conversational', async ({ page }) => {
  await send(page, '找宽订单表')
  await expect(assistantMessage(page, '找到 10 张候选表，请先选择数据层。')).toBeVisible()
  await send(page, 'DWD')
  await send(page, '退款')
  await send(page, '第一个')
  await send(page, '查看字段')
  await expect(assistantMessage(page, '已读取 dw.dwd_refund_detail 的 2 个字段。')).toBeVisible()
})

test('journey 3: dependency failure recovers and accepts a new goal', async ({ page, request }) => {
  await request.post('http://127.0.0.1:18085/acceptance/degrade', { data: { mode: 'auth' } })
  await send(page, '找订单表')
  const authMessage = assistantMessage(page, '当前表搜索鉴权不可用')
  await expect(authMessage).toBeVisible()
  await expect(authMessage).not.toContainText('没有找到')
  await send(page, '什么意思')
  await request.post('http://127.0.0.1:18085/acceptance/degrade', { data: { mode: '' } })
  await send(page, '找退款表')
  await send(page, '第一个')
  await send(page, '查看字段')
  await expect(assistantMessage(page, '已读取 dw.dwd_refund_detail 的 2 个字段。')).toBeVisible()
})

test('journey 4: broken LLM health does not block deterministic tools', async ({ page }) => {
  await expect(page.getByText('3/11 能力就绪')).toBeVisible()
  await send(page, '你好')
  await send(page, '找订单表')
  await send(page, '什么意思')
  await send(page, '第一个')
  await send(page, '查看字段')
  await expect(assistantMessage(page, '已读取 dw.dwd_orders_detail 的 2 个字段。')).toBeVisible()
})

test('journey 5: refresh restores the authoritative interaction', async ({ page }) => {
  await send(page, '找订单表')
  await expect(page.locator('[data-interaction-option="table_2"]')).toBeEnabled()
  await page.reload()
  await page.waitForLoadState('networkidle')
  await expect(page.locator('[data-interaction-option="table_2"]')).toBeEnabled()
  await send(page, '什么意思')
  await send(page, '第二个')
  await send(page, '查看字段')
  await send(page, '你好')
  await expect(assistantMessage(page, '已读取 dw.dws_orders_summary 的 2 个字段。')).toBeVisible()
})

test('journey 6: backend runtime restart restores SQLite state', async ({ page, request }) => {
  const conversationId = await page.evaluate(() => localStorage.getItem('conversation_id'))
  await request.post('http://127.0.0.1:18085/acceptance/poison-read-only', {
    data: { conversation_id: conversationId },
  })
  await request.post('http://127.0.0.1:18085/acceptance/restart')
  await page.reload()
  await page.waitForLoadState('networkidle')
  await send(page, '你好')
  const restored = await request.get(
    `http://127.0.0.1:18085/agent/messages?conversation_id=${conversationId}`,
  )
  expect((await restored.json()).conversation.status).toBe('recoverable_error')
  await expect(page.locator('body')).not.toContainText('execution_unknown')
  await send(page, '找订单表')
  await send(page, '第二个')
  await send(page, '查看字段')
  await send(page, '什么意思')
  await send(page, '你好')
  await expect(assistantMessage(page, '已读取 dw.dws_orders_summary 的 2 个字段。')).toBeVisible()
})

test('journey 7: two pages reject one stale card answer', async ({ page, context }) => {
  await send(page, '找订单表')
  const conversationId = await page.evaluate(() => localStorage.getItem('conversation_id'))
  const second = await context.newPage()
  await second.goto('/')
  await second.evaluate(id => localStorage.setItem('conversation_id', id || ''), conversationId)
  await second.reload()
  await second.waitForLoadState('networkidle')
  await Promise.all([
    clickOption(page, 'table_1'),
    clickOption(second, 'table_2'),
  ])
  const combined = `${await page.locator('body').innerText()}\n${await second.locator('body').innerText()}`
  expect(combined).toContain('已选择数据表')
  expect(combined).toMatch(/当前没有等待回答的问题|已经更新|已失效/)
  await send(second, '查看字段')
  await expect(assistantMessage(second, /已读取 .* 的 2 个字段。/)).toBeVisible()
})

test('journey 8: switching goals clears prior table state', async ({ page, request }) => {
  await send(page, '找订单表')
  await send(page, '第一个')
  await send(page, '找退款表')
  const conversationId = await page.evaluate(() => localStorage.getItem('conversation_id'))
  const state = await request.get(`http://127.0.0.1:18085/agent/messages?conversation_id=${conversationId}`)
  expect((await state.json()).conversation.selected_resources).toEqual({})
  await send(page, '第二个')
  await send(page, '查看字段')
  await expect(assistantMessage(page, '已读取 dw.dws_refund_summary 的 2 个字段。')).toBeVisible()
})
