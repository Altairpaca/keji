import { test, expect, Page } from '@playwright/test';

/** 唯一后缀：多个 spec / 多次运行不互相干扰 */
function unique(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
}

/** 直接创建客户（表单），返回详情页 URL */
async function createCustomer(page: Page, name: string): Promise<string> {
  await page.goto('/customers/create/');
  await page.fill('#id_name', name);
  await page.fill('#id_age_note', '35岁');
  await page.getByRole('button', { name: '保存' }).click();
  await page.waitForURL(/\/customers\/[0-9a-f-]{36}\/?$/);
  return page.url();
}

test.describe('客户档案工作流', () => {
  test('客户列表可见（seed 演示数据）', async ({ page }) => {
    await page.goto('/customers/');
    await expect(page.locator('main')).toBeVisible();
    // seed 演示客户统一前缀「演示-」应出现在列表
    await expect(page.locator('main').getByText('演示-', { exact: false }).first()).toBeVisible();
    // 列表存在客户详情链接（UUID 形式）
    const href = await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll('main a[href^="/customers/"]'));
      return (
        links
          .map((a) => a.getAttribute('href') ?? '')
          .find((h) => /\/customers\/[0-9a-f-]{36}\/?$/.test(h)) ?? null
      );
    });
    expect(href).not.toBeNull();
  });

  test('创建客户 → 详情页出现姓名', async ({ page }) => {
    const name = unique('E2E客户');
    const url = await createCustomer(page, name);
    await expect(page.locator('h1')).toContainText(name);
    await expect(page.locator('main')).toContainText(name);
    expect(url).toMatch(/\/customers\/[0-9a-f-]{36}\/?$/);
  });

  test('编辑客户 → 姓名更新', async ({ page }) => {
    const name = unique('E2E编辑');
    await createCustomer(page, name);
    await page.getByRole('link', { name: '编辑', exact: true }).click();
    await page.waitForURL(/\/edit\/$/);
    const newName = `${name}-改`;
    await page.fill('#id_name', newName);
    await page.getByRole('button', { name: '保存' }).click();
    await page.waitForURL(/\/customers\/[0-9a-f-]{36}\/?$/);
    await expect(page.locator('h1')).toContainText(newName);
  });

  test('筛选「已见面」→ 列表只含该状态', async ({ page }) => {
    await page.goto('/customers/');
    await page.selectOption('#status', { label: '已见面' });
    await page.getByRole('button', { name: '筛选' }).click();
    await page.waitForURL(/\?.*status=/);
    // 主列表内的状态徽标全部为「已见面」
    const badges = page.locator('main [data-testid="status-badge"]');
    await expect(badges.first()).toBeVisible();
    const texts = await badges.allTextContents();
    expect(texts.length).toBeGreaterThan(0);
    expect(texts.every((t) => t.trim() === '已见面')).toBe(true);
  });

  test('删除客户 → 从列表消失', async ({ page }) => {
    const name = unique('E2E删除');
    await createCustomer(page, name);
    page.on('dialog', (d) => d.accept()); // 接受「确认删除」弹窗
    await page.getByRole('button', { name: '删除', exact: true }).click();
    await page.waitForURL('**/customers/');
    await expect(page.locator('main').getByText(name, { exact: true })).toHaveCount(0);
  });

  test('导出：客户详情导出菜单可见且 CSV 可下载', async ({ page }) => {
    const url = await (async () => {
      await page.goto('/customers/');
      return page.evaluate(() => {
        const links = Array.from(document.querySelectorAll('main a[href^="/customers/"]'));
        return (
          links
            .map((a) => a.getAttribute('href') ?? '')
            .find((h) => /\/customers\/[0-9a-f-]{36}\/?$/.test(h)) ?? '/customers/'
        );
      });
    })();
    await page.goto(url);
    // 打开导出菜单：3 个导出项
    await page.getByRole('button', { name: /导出资料/ }).click();
    const menu = page.getByRole('menu');
    await expect(menu.getByRole('menuitem')).toHaveCount(3);
    // 触发 CSV 下载
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      menu.getByRole('menuitem', { name: '档案摘要（CSV）' }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.csv$/i);
  });
});
