import { test, expect, Page } from '@playwright/test';

function unique(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
}

/** 取列表第一个保单详情 URL */
async function firstPolicyUrl(page: Page): Promise<string> {
  await page.goto('/policies/');
  const href = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('main a[href^="/policies/"]'));
    return (
      links
        .map((a) => a.getAttribute('href') ?? '')
        .find((h) => /\/policies\/[0-9a-f-]{36}\/?$/.test(h)) ?? null
    );
  });
  expect(href, '保单列表应包含详情链接').not.toBeNull();
  return href!;
}

test.describe('保单工作流', () => {
  test('保单列表可见（seed 数据）', async ({ page }) => {
    await page.goto('/policies/');
    await expect(page.locator('main')).toBeVisible();
    const cards = page.locator('[data-testid="policy-card"]');
    expect(await cards.count()).toBeGreaterThan(0);
  });

  test('创建保单（投保人选演示客户）→ 详情含状态', async ({ page }) => {
    const name = unique('E2E重疾险');
    const policyNo = unique('E2EPOL');
    await page.goto('/policies/create/');
    await page.fill('#id_insurer', 'E2E保险公司');
    await page.fill('#id_name', name);
    await page.fill('#id_policy_no', policyNo);
    // 投保人选择 seed 演示客户（label 不支持正则，按文本取 option value）
    const holderValue = await page
      .locator('#id_policyholder option')
      .filter({ hasText: /演示-/ })
      .first()
      .getAttribute('value');
    expect(holderValue, '投保人下拉应包含演示客户').not.toBeNull();
    await page.selectOption('#id_policyholder', holderValue!);
    await page.getByRole('button', { name: '保存' }).click();
    await page.waitForURL(/\/policies\/[0-9a-f-]{36}\/?$/);
    await expect(page.locator('h1')).toContainText(name);
    // 详情含状态「正常有效」（默认 active；标题与信息卡各一个徽标，取首个）
    await expect(page.locator('[data-testid="policy-status-badge"]').first()).toContainText(
      '正常有效',
    );
  });

  test('状态流转（合法迁移）→ 历史出现', async ({ page }) => {
    const url = await firstPolicyUrl(page);
    await page.goto(url);
    // 从 active 合法迁移到「缴费中」
    await page.selectOption('#id_new_status', { label: '缴费中' });
    await page.fill('#id_note', 'E2E状态流转测试');
    await page.getByRole('button', { name: '变更状态' }).click();
    await page.waitForURL(/\/policies\/[0-9a-f-]{36}\/?$/);
    // 当前状态更新为「缴费中」
    await expect(page.locator('[data-testid="policy-status-badge"]').first()).toContainText(
      '缴费中',
    );
    // 状态历史时间线出现一条记录
    await expect(page.locator('main').getByRole('heading', { name: '状态历史' })).toBeVisible();
    await expect(page.locator('main').getByText('E2E状态流转测试')).toBeVisible();
  });
});
