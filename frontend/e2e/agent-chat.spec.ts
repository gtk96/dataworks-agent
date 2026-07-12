import { expect, test } from '@playwright/test'

test.describe('Agent conversational query', () => {
  test.use({ viewport: { width: 1280, height: 720 } })

  test('returns business data and keeps the composer usable across turns', async ({ page }) => {
    await page.goto('/')

    const composer = page.locator('textarea')
    await expect(composer).toBeVisible()
    await composer.fill('今天各家族的有效订单是多少')
    await composer.press('Enter')

    const result = page.getByTestId('query-result')
    await expect(result).toBeVisible()
    await expect(result).toContainText('吉喵云')
    await expect(result).toContainText('6560')
    const semanticProof = page.getByTestId('semantic-proof')
    await expect(semanticProof).toBeVisible()
    await expect(semanticProof).toContainText('approved v2')
    await expect(semanticProof).toContainText('giikin_aliyun.tb_rp_ord_order_cnt_hi')
    await expect(semanticProof).toContainText('\u6570\u636e\u4e13\u8f91')
    await expect(semanticProof).toContainText('AK/SK')
    await expect(page.getByText('真实问数完成，返回 2 行，闭环验收通过。')).toBeVisible()
    await expect(page.getByText('Closed Loop Verification')).toBeVisible()

    const firstBox = await composer.boundingBox()
    expect(firstBox).not.toBeNull()
    expect(firstBox!.y).toBeGreaterThanOrEqual(0)
    expect(firstBox!.y + firstBox!.height).toBeLessThanOrEqual(720)

    await composer.fill('再查一次今天各家族的有效订单数')
    await composer.press('Enter')
    await expect(page.getByText('再查一次今天各家族的有效订单数')).toBeVisible()
    await expect(result).toBeVisible()

    const secondBox = await composer.boundingBox()
    expect(secondBox).not.toBeNull()
    expect(secondBox!.y + secondBox!.height).toBeLessThanOrEqual(720)
  })
})
