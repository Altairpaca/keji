import { test, expect, Page } from '@playwright/test';

function unique(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
}

/** selectOption 的 label 不支持正则：先按文本定位 option 取 value，再按 value 选中 */
async function selectOptionByText(page: Page, selector: string, text: string | RegExp): Promise<void> {
  const value = await page
    .locator(`${selector} option`)
    .filter({ hasText: text })
    .first()
    .getAttribute('value');
  expect(value, `${selector} 应包含匹配「${text}」的选项`).not.toBeNull();
  await page.selectOption(selector, value!);
}

/** 创建理赔案件（默认状态=客户咨询），返回详情 URL */
async function createClaim(page: Page, name: string): Promise<string> {
  await page.goto('/claims/create/');
  await page.fill('#id_name', name);
  await selectOptionByText(page, '#id_customer', /演示-/);
  await page.selectOption('#id_claim_type', { label: '医疗' });
  await page.fill('#id_incident_date', '2026-07-01');
  await page.getByRole('button', { name: '保存' }).click();
  await page.waitForURL(/\/claims\/[0-9a-f-]{36}\/?$/);
  return page.url();
}

test.describe('理赔工作流', () => {
  test('理赔列表可见（seed 数据）', async ({ page }) => {
    await page.goto('/claims/');
    await expect(page.locator('main')).toBeVisible();
    const cards = page.locator('[data-testid="claim-card"]');
    expect(await cards.count()).toBeGreaterThan(0);
  });

  test('创建理赔（客户+类型）→ 详情含状态', async ({ page }) => {
    const name = unique('E2E理赔案件');
    const url = await createClaim(page, name);
    await expect(page.locator('h1')).toContainText(name);
    // 默认状态「客户咨询」
    await expect(page.locator('main').getByText('客户咨询', { exact: true })).toBeVisible();
    expect(url).toMatch(/\/claims\/[0-9a-f-]{36}\/?$/);
  });

  test('材料清单模板实例化 → 材料行出现', async ({ page }) => {
    const name = unique('E2E材料实例化');
    await createClaim(page, name);
    // 新案件暂无材料
    await expect(page.locator('[data-testid="material-row"]')).toHaveCount(0);
    // 点击「按模板生成」实例化材料清单
    await page.getByRole('button', { name: '按模板生成' }).click();
    await page.waitForURL(/\/claims\/[0-9a-f-]{36}\/?$/);
    const rows = page.locator('[data-testid="material-row"]');
    expect(await rows.count()).toBeGreaterThan(0);
    // 缺料提示出现
    await expect(page.locator('[data-testid="missing-materials-alert"]')).toBeVisible();
  });

  test('材料状态流转：未提交 → 已提交', async ({ page }) => {
    const name = unique('E2E材料流转');
    await createClaim(page, name);
    await page.getByRole('button', { name: '按模板生成' }).click();
    await page.waitForURL(/\/claims\/[0-9a-f-]{36}\/?$/);
    // 第一行材料：默认「未提交」，选择「已提交」并流转
    const firstRow = page.locator('[data-testid="material-row"]').first();
    await expect(firstRow).toContainText('未提交');
    await firstRow.locator('select[name="new_status"]').selectOption({ label: '已提交' });
    await firstRow.getByRole('button', { name: '流转' }).click();
    await page.waitForURL(/\/claims\/[0-9a-f-]{36}\/?$/);
    // 材料状态更新为「已提交」
    await expect(page.locator('[data-testid="material-row"]').first()).toContainText('已提交');
  });
});
