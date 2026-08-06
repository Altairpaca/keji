import { test, expect } from '@playwright/test';

test.describe('全局搜索工作流', () => {
  test('首页搜索框输入 seed 客户名 → 结果含该客户', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('input[aria-label="全局搜索"]');
    await expect(input).toBeVisible();
    await input.fill('演示-王建国');
    await input.press('Enter');
    await page.waitForURL('**/search/**');
    // 结果区出现指向该客户详情的链接
    const resultLink = page.locator('main a[href^="/customers/"]', {
      hasText: '演示-王建国',
    });
    await expect(resultLink.first()).toBeVisible();
    // 结果页标题含查询词
    await expect(page.locator('main h1')).toContainText('演示-王建国');
  });

  test('搜索无结果 → 显示空状态', async ({ page }) => {
    await page.goto('/search/?q=' + encodeURIComponent('绝对不存在的关键词xyz999'));
    await expect(page.getByText('没有找到相关结果')).toBeVisible();
  });
});
