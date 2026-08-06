import { test, expect, Page, chromium } from '@playwright/test';

/** 无横向滚动：documentElement.scrollWidth <= window.innerWidth */
async function expectNoHorizontalScroll(page: Page) {
  const sw = await page.evaluate(() => document.documentElement.scrollWidth);
  const iw = await page.evaluate(() => window.innerWidth);
  expect(sw - iw, `横向溢出 ${sw - iw}px（scrollWidth=${sw} / innerWidth=${iw}）`).toBeLessThanOrEqual(0);
}

/** 手机公共检查：底部导航可见、主内容可见、无横向滚动 */
async function expectMobilePageOk(page: Page, path: string) {
  await page.goto(path);
  await page.waitForLoadState('networkidle');
  const nav = page.locator('nav[aria-label="主导航"]');
  await expect(nav).toBeVisible();
  await expect(page.locator('main')).toBeVisible();
  await expectNoHorizontalScroll(page);
}

/** 主按钮：滚动到可见，且不被底部导航遮挡 */
async function expectPrimaryActionUsable(page: Page) {
  const btn = page.locator('.btn-primary:visible').first();
  if ((await btn.count()) === 0) return; // 无主按钮的页面跳过
  await btn.scrollIntoViewIfNeeded();
  await expect(btn).toBeVisible();
  const box = await btn.boundingBox();
  const navBox = await page.locator('nav[aria-label="主导航"]').boundingBox();
  expect(box!.y + box!.height, '主按钮不应被底部导航遮挡').toBeLessThanOrEqual(navBox!.y + 1);
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

test.describe('手机 390x844 底部导航', () => {
  test('底部导航固定 5 项且文字正确', async ({ page }) => {
    await page.goto('/');
    const nav = page.locator('nav[aria-label="主导航"]');
    await expect(nav).toBeVisible();
    const items = nav.locator('a');
    await expect(items).toHaveCount(5);
    const labels = await items.allTextContents();
    expect(labels.map((t) => t.trim())).toEqual(['首页', '客户', '上传', '待办', '我的']);
  });

  test('点击「待办」跳转 /tasks/', async ({ page }) => {
    await page.goto('/');
    await page.locator('nav[aria-label="主导航"] a', { hasText: '待办' }).click();
    await page.waitForURL('**/tasks/');
    await expect(page.locator('main')).toBeVisible();
  });
});

test.describe('手机 390x844 关键页面无横向滚动', () => {
  test('客户列表 /customers/', async ({ page }) => {
    await expectMobilePageOk(page, '/customers/');
  });

  test('客户详情页', async ({ page }) => {
    const url = await firstCustomerUrl(page);
    await expectMobilePageOk(page, url);
  });

  test('新建客户表单 /customers/create/', async ({ page }) => {
    await expectMobilePageOk(page, '/customers/create/');
    await expectPrimaryActionUsable(page);
  });

  test('上传页 /documents/upload/', async ({ page }) => {
    await expectMobilePageOk(page, '/documents/upload/');
    await expectPrimaryActionUsable(page);
  });

  test('待办列表 /tasks/', async ({ page }) => {
    await expectMobilePageOk(page, '/tasks/');
    await expectPrimaryActionUsable(page);
  });

  test('新建待办 /tasks/new/', async ({ page }) => {
    await expectMobilePageOk(page, '/tasks/new/');
    await expectPrimaryActionUsable(page);
  });

  test('理赔列表 /claims/', async ({ page }) => {
    await expectMobilePageOk(page, '/claims/');
    await expectPrimaryActionUsable(page);
  });

  test('保单列表 /policies/', async ({ page }) => {
    await expectMobilePageOk(page, '/policies/');
  });

  test('相册列表 /documents/albums/', async ({ page }) => {
    await expectMobilePageOk(page, '/documents/albums/');
  });

  test('标签列表 /customers/tags/', async ({ page }) => {
    await expectMobilePageOk(page, '/customers/tags/');
  });

  test('回收站 /documents/trash/', async ({ page }) => {
    await expectMobilePageOk(page, '/documents/trash/');
  });

  test('重复文件 /documents/duplicates/', async ({ page }) => {
    await expectMobilePageOk(page, '/documents/duplicates/');
  });

  test('搜索页 /search/', async ({ page }) => {
    await expectMobilePageOk(page, '/search/?q=%E5%AE%A2');
  });

  test('首页 /', async ({ page }) => {
    await expectMobilePageOk(page, '/');
  });
});

/** 触控目标扫描：main 内可见的 a/button/select 高度 <44px 的全部列出。
 *  行内文本链接（display:inline 的 a，即段落内的 prose 链接）不适用 44px 规则（WCAG 2.5.8 例外）。 */
async function touchTargetViolations(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const bad: string[] = [];
    const els = document.querySelectorAll<HTMLElement>(
      'main a, main button, main input[type="submit"], main select',
    );
    els.forEach((el) => {
      const style = getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return;
      if (el.tagName === 'A' && style.display === 'inline') return;
      const r = el.getBoundingClientRect();
      if (r.height === 0 || r.width === 0) return;
      if (r.height < 44) {
        const cls = (el.className as string).slice(0, 90);
        bad.push(`${el.tagName.toLowerCase()} h=${Math.round(r.height)}px cls="${cls}" text="${(el.textContent ?? '').trim().slice(0, 20)}"`);
      }
    });
    return bad;
  });
}

async function expectTouchTargetsOk(page: Page) {
  const violations = await touchTargetViolations(page);
  expect(violations, `触控目标 <44px（${violations.length} 个）`).toEqual([]);
}

test.describe('手机 390x844 全站扫描（无横向滚动 + 触控 ≥44px）', () => {
  const staticPages: Array<[string, string]> = [
    ['事件列表 /activities/', '/activities/'],
    ['新建事件 /activities/events/new/', '/activities/events/new/'],
    ['新建沟通 /activities/communications/new/', '/activities/communications/new/'],
    ['重复客户 /customers/duplicates/', '/customers/duplicates/'],
    ['新建标签 /customers/tags/create/', '/customers/tags/create/'],
    ['保单列表 /policies/', '/policies/'],
    ['新建保单 /policies/create/', '/policies/create/'],
    ['续保提醒 /policies/reminders/', '/policies/reminders/'],
    ['新建理赔 /claims/create/', '/claims/create/'],
    ['文档列表 /documents/', '/documents/'],
    ['新建相册 /documents/albums/create/', '/documents/albums/create/'],
    ['我的资料 /accounts/profile/', '/accounts/profile/'],
  ];

  for (const [label, path] of staticPages) {
    test(label, async ({ page }) => {
      await expectMobilePageOk(page, path);
      await expectTouchTargetsOk(page);
    });
  }

  test('客户编辑表单 /customers/<id>/edit/', async ({ page }) => {
    const url = await firstCustomerUrl(page);
    await expectMobilePageOk(page, url.replace(/\/?$/, '/edit/'));
    await expectTouchTargetsOk(page);
    await expectPrimaryActionUsable(page);
  });

  test('关系图页 /customers/<id>/graph-page/', async ({ page }) => {
    const url = await firstCustomerUrl(page);
    await expectMobilePageOk(page, url.replace(/\/?$/, '/graph-page/'));
    await expectTouchTargetsOk(page);
  });

  test('保单详情 /policies/<id>/ 与保单文档', async ({ page }) => {
    const id = await firstUuid(page, '/policies/', '/policies/');
    await expectMobilePageOk(page, `/policies/${id}/`);
    await expectTouchTargetsOk(page);
    await expectMobilePageOk(page, `/policies/${id}/documents/`);
    await expectTouchTargetsOk(page);
  });

  test('理赔详情 /claims/<id>/', async ({ page }) => {
    const id = await firstUuid(page, '/claims/', '/claims/');
    await expectMobilePageOk(page, `/claims/${id}/`);
    await expectTouchTargetsOk(page);
  });

  test('相册详情 /documents/albums/<id>/', async ({ page }) => {
    const id = await firstUuid(page, '/documents/albums/', '/documents/albums/');
    await expectMobilePageOk(page, `/documents/albums/${id}/`);
    await expectTouchTargetsOk(page);
  });
});

/** 从列表页取第一个 <prefix><uuid> 形式的 id */
async function firstUuid(page: Page, listPath: string, prefix: string): Promise<string> {
  await page.goto(listPath);
  const id = await page.evaluate((pfx) => {
    const re = new RegExp('^' + pfx.replace(/\//g, '\\/') + '([0-9a-f-]{36})');
    const links = Array.from(document.querySelectorAll('main a[href^="' + pfx + '"]'));
    for (const a of links) {
      const m = (a.getAttribute('href') ?? '').match(re);
      if (m) return m[1];
    }
    return null;
  }, prefix);
  expect(id, `${listPath} 应包含详情链接`).not.toBeNull();
  return id!;
}
