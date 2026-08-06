import { test, expect, Page } from '@playwright/test';

/** 无横向滚动：documentElement.scrollWidth <= window.innerWidth */
async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow, `横向溢出 ${overflow}px（scrollWidth=${await page.evaluate(() => document.documentElement.scrollWidth)} / innerWidth=${await page.evaluate(() => window.innerWidth)}）`).toBeLessThanOrEqual(0);
}

/** 桌面三栏：左栏约 280px、右栏约 320px、中栏在主内容区 */
async function expectThreeColumns(page: Page) {
  const asides = page.locator('aside');
  await expect(asides.first()).toBeVisible();
  await expect(asides.nth(1)).toBeVisible();
  const left = await asides.first().boundingBox();
  const right = await asides.nth(1).boundingBox();
  expect(left!.width).toBeGreaterThan(260);
  expect(left!.width).toBeLessThan(300);
  expect(right!.width).toBeGreaterThan(300);
  expect(right!.width).toBeLessThan(340);
  // 三栏横向排布：左栏 x < 主栏 x < 右栏 x
  const main = await page.locator('main').boundingBox();
  expect(left!.x).toBeLessThan(main!.x);
  expect(main!.x).toBeLessThan(right!.x);
}

async function firstCustomerUrl(page: Page): Promise<string> {
  await page.goto('/customers/');
  const href = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('main a[href^="/customers/"]'));
    const m = links.map((a) => a.getAttribute('href') ?? '').find((h) => /\/customers\/[0-9a-f-]{36}\/?$/.test(h));
    return m ?? null;
  });
  expect(href, '客户列表应包含客户详情链接').not.toBeNull();
  return href!;
}

test.describe('桌面 1440x900 三栏布局', () => {
  test('客户列表页：三栏可见且无横向滚动', async ({ page }) => {
    await page.goto('/customers/');
    await expectNoHorizontalScroll(page);
    await expectThreeColumns(page);
  });

  test('客户详情页：三栏可见且无横向滚动', async ({ page }) => {
    const url = await firstCustomerUrl(page);
    await page.goto(url);
    await expectNoHorizontalScroll(page);
    await expectThreeColumns(page);
  });

  test('首页与搜索页：无横向滚动', async ({ page }) => {
    await page.goto('/');
    await expectNoHorizontalScroll(page);
    await page.goto('/search/?q=%E5%AE%A2');
    await expectNoHorizontalScroll(page);
  });
});
