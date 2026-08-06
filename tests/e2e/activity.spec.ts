import { test, expect, Page } from '@playwright/test';

function unique(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
}

/** 取列表页第一个客户 UUID */
async function firstCustomerUuid(page: Page): Promise<string> {
  await page.goto('/customers/');
  const id = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('main a[href^="/customers/"]'));
    for (const a of links) {
      const m = (a.getAttribute('href') ?? '').match(/\/customers\/([0-9a-f-]{36})/);
      if (m) return m[1];
    }
    return null;
  });
  expect(id, '客户列表应包含详情链接').not.toBeNull();
  return id!;
}

/** 找一个时间线非空的客户详情 URL（E2E 新建客户无时间线，需命中 seed 演示客户） */
async function customerWithTimeline(page: Page): Promise<string> {
  await page.goto('/customers/');
  const hrefs = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('main a[href^="/customers/"]'));
    return links
      .map((a) => a.getAttribute('href') ?? '')
      .filter((h) => /\/customers\/[0-9a-f-]{36}\/?$/.test(h));
  });
  expect(hrefs.length).toBeGreaterThan(0);
  for (const href of hrefs.slice(0, 12)) {
    await page.goto(href);
    if ((await page.locator('main time[datetime]').count()) > 0) return href;
  }
  return hrefs[0];
}

test.describe('工作事件与时间线工作流', () => {
  test('客户详情时间线区块存在且有 seed 条目', async ({ page }) => {
    const url = await customerWithTimeline(page);
    await page.goto(url);
    // 时间线区块标题可见（exact，避免命中空状态「暂无时间线记录」）
    await expect(
      page.locator('main').getByRole('heading', { name: '时间线', exact: true }),
    ).toBeVisible();
    // seed 后应有条目（含 <time datetime> 的事件卡片），且不显示空状态
    await expect(page.locator('main time[datetime]').first()).toBeVisible();
    await expect(page.getByText('暂无时间线记录')).toHaveCount(0);
  });

  test('新建工作事件（客户页入口）→ 时间线新增', async ({ page }) => {
    const id = await firstCustomerUuid(page);
    const title = unique('E2E跟进事件');

    // 从客户预选入口进入事件新建页
    await page.goto(`/activities/events/new/?customer=${id}`);
    await page.fill('#id_title', title);
    await page.selectOption('#id_event_type', { label: '电话沟通' });
    await page.fill('#id_occurred_at', '2026-08-05T10:30');
    await page.getByRole('button', { name: '保存' }).click();
    // 成功后回到事件列表
    await page.waitForURL('**/activities/');
    await expect(page.locator('main')).toContainText(title);

    // 回到客户详情，时间线出现该事件
    await page.goto(`/customers/${id}/`);
    await expect(page.locator('main').getByText(title, { exact: false }).first()).toBeVisible();
  });
});
