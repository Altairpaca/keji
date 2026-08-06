import { test, expect } from '@playwright/test';

// 认证流程使用独立会话，不走共享 admin storageState（global-setup 已登录）。
// 注意：storageState 传 undefined 不会覆盖 config 默认值，需显式传空 cookie。
test.use({ storageState: { cookies: [], origins: [] } });

test.describe('认证流程（登录 / 错误密码 / 登出 / 权限）', () => {
  test('登录成功：重定向首页且顶部品牌可见', async ({ page }) => {
    await page.goto('/accounts/login/');
    await page.fill('input[name="username"]', 'admin');
    await page.fill('input[name="password"]', 'Admin!234');
    await page.click('button[type="submit"]');
    await page.waitForURL((url) => url.pathname === '/');
    // 顶部品牌「客迹」可见
    await expect(page.locator('a[aria-label="客迹首页"]')).toBeVisible();
    await expect(page.getByText('客迹', { exact: true })).toBeVisible();
  });

  test('错误密码：留在登录页并显示错误提示', async ({ page }) => {
    await page.goto('/accounts/login/');
    await page.fill('input[name="username"]', 'admin');
    await page.fill('input[name="password"]', 'Wrong!Pass');
    await page.click('button[type="submit"]');
    await expect(page).toHaveURL(/\/accounts\/login\/.*/);
    await expect(page.getByText('无法登录')).toBeVisible();
  });

  test('登出：返回登录页', async ({ page }) => {
    await page.goto('/accounts/login/');
    await page.fill('input[name="username"]', 'admin');
    await page.fill('input[name="password"]', 'Admin!234');
    await page.click('button[type="submit"]');
    await page.waitForURL((url) => url.pathname === '/');
    // 打开用户菜单并退出（退出按钮 role=menuitem，不是 button）
    await page.click('button[aria-haspopup="menu"]');
    await page.getByRole('menuitem', { name: '退出登录' }).click();
    await page.waitForURL('**/accounts/login/**');
    await expect(page.locator('input[name="username"]')).toBeVisible();
  });

  test('普通用户（无权限位）访问 /customers/ → 403', async ({ page }) => {
    // plain_e2e 由 seed/DB 预建，无任何权限位（can_view_customers=False）
    await page.goto('/accounts/login/');
    await page.fill('input[name="username"]', 'plain_e2e');
    await page.fill('input[name="password"]', 'Plain!234');
    await page.click('button[type="submit"]');
    await page.waitForURL((url) => !url.pathname.startsWith('/accounts/login'));
    await page.goto('/customers/');
    // Django 默认 403 页：内容含「403 Forbidden」
    await expect(page.getByText('403', { exact: false }).first()).toBeVisible();
  });
});
